"""Provider-agnostic OpenAI-compatible LLM client and decision parser for RotomArena."""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Tuple
import openai
from openai import AsyncOpenAI

from rotomarena import local_servers
from rotomarena.config import ProviderConfig, provider_presets
from rotomarena.llm.prompts import SYSTEM_PROMPT_DIRECT_COT, USER_PROMPT_DIRECT_COT_TEMPLATE
from rotomarena.llm.schemas import ActionDecision, LLMUsageMetrics


def to_id(text: str) -> str:
    """Showdown's toID: lowercase letters and digits only ('Landorus-Therian' -> 'landorustherian')."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


# One action line, allowing list markers, bold and an "ACTION:" prefix around "MOVE: x" / "SWITCH: x".
_ACTION_LINE = re.compile(
    r"^\s*(?:[-*>•]|\d+[.)])?\s*(?:ACTION\s*:\s*)?\**\s*(MOVE|SWITCH)\s*\**\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TERA_TAG = re.compile(r"\[\s*TERA\s*\]", re.IGNORECASE)

# Local llama.cpp servers share one GPU, CPU and memory bus. Two models generating at once (both players
# answer the same turn) ran Qwen at 0.5 tok/s instead of 11.5, so local requests take turns.
_local_inference: Optional[asyncio.Lock] = None


def _local_lock() -> asyncio.Lock:
    global _local_inference
    if _local_inference is None:
        _local_inference = asyncio.Lock()
    return _local_inference


def parse_decision(raw_text: str) -> ActionDecision:
    """Parses '<thought>…</thought><decision>MOVE: id [TERA]</decision>' strictly: exactly one action line."""
    thought = re.search(r"<thought>(.*?)</thought>", raw_text, re.DOTALL | re.IGNORECASE)
    reasoning = thought.group(1).strip() if thought else ""

    def failed(reason: str) -> ActionDecision:
        return ActionDecision(reasoning=reasoning, parse_error=reason, raw_response=raw_text)

    block = re.search(r"<decision>(.*?)</decision>", raw_text, re.DOTALL | re.IGNORECASE)
    if not block:
        return failed("missing <decision>...</decision> block")

    actions = _ACTION_LINE.findall(block.group(1))
    if not actions:
        return failed("no MOVE or SWITCH line in <decision>")
    if len(actions) > 1:
        return failed(f"{len(actions)} action lines in <decision>; exactly one is allowed")

    kind, rest = actions[0]
    terastallize = bool(_TERA_TAG.search(rest))
    target = to_id(re.sub(r"\(.*?\)", "", _TERA_TAG.sub("", rest)))
    if not target:
        return failed("empty action target")

    return ActionDecision(
        action_type=kind.upper(),
        target=target,
        terastallize=terastallize and kind.upper() == "MOVE",
        reasoning=reasoning,
        raw_response=raw_text,
    )


class LLMClient:
    """Async OpenAI-compatible LLM client (OpenRouter, local llama.cpp, Gemini, Ollama, vLLM)."""

    def __init__(self, provider_config: ProviderConfig, provider_name: str = "custom"):
        self.config = provider_config
        self.provider_name = provider_name
        self.default_model = provider_config.default_model
        self.temperature = provider_config.temperature
        self._port = urlparse(provider_config.base_url).port

        headers = None
        if provider_config.api_style == "openrouter":
            headers = {"HTTP-Referer": "https://github.com/rotomarena", "X-Title": "RotomArena"}

        self._client = AsyncOpenAI(
            base_url=provider_config.base_url,
            api_key=provider_config.get_api_key() or "dummy",
            timeout=provider_config.timeout,
            max_retries=0,  # retries are handled in generate_completion
            default_headers=headers,
        )

    @classmethod
    def from_provider_name(
        cls,
        name: str,
        providers: Optional[Dict[str, ProviderConfig]] = None,
        model_override: Optional[str] = None,
    ) -> "LLMClient":
        """Builds a client for a named provider profile (config entries first, then built-in presets)."""
        known = {**provider_presets(), **(providers or {})}
        if name not in known:
            raise ValueError(f"Unknown LLM provider '{name}'. Known providers: {', '.join(sorted(known))}")
        config = known[name]
        if model_override:
            config = config.model_copy(update={"default_model": model_override})
        return cls(provider_config=config, provider_name=name)

    def _reasoning_kwargs(self, reasoning: str) -> Dict[str, Any]:
        """Translates the ruleset's reasoning level into this provider's request fields."""
        style = self.config.api_style
        if style == "openrouter":
            setting = {"enabled": False} if reasoning == "off" else {"effort": reasoning}
            return {"extra_body": {"reasoning": setting}}
        if style == "llama.cpp":
            # Chat templates read these: Qwen-style models use enable_thinking; gpt-oss uses
            # reasoning_effort, whose lowest level is "low".
            template_kwargs = {
                "enable_thinking": reasoning != "off",
                "reasoning_effort": "low" if reasoning == "off" else reasoning,
            }
            return {"extra_body": {"chat_template_kwargs": template_kwargs}}
        return {} if reasoning == "off" else {"reasoning_effort": reasoning}

    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning: str = "off",
        max_retries: int = 3,
    ) -> Tuple[str, LLMUsageMetrics]:
        """Calls the chat completions API, retrying server errors and rate limits."""
        target_model = model or self.default_model
        create_kwargs: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            **self._reasoning_kwargs(reasoning),
        }
        if max_tokens:
            create_kwargs["max_tokens"] = max_tokens

        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                if self.config.api_style == "llama.cpp":
                    async with _local_lock():
                        await local_servers.ensure_loaded(self._port)  # swap mode: load this model first
                        start_time = time.perf_counter()  # latency excludes the wait and the load
                        response = await self._client.chat.completions.create(**create_kwargs)
                else:
                    start_time = time.perf_counter()
                    response = await self._client.chat.completions.create(**create_kwargs)
            except openai.APIStatusError as e:
                last_err = e
                if e.status_code < 500 and e.status_code != 429:
                    break  # bad request, auth or unknown model: retrying won't help
                if attempt < max_retries - 1:
                    await asyncio.sleep((10 if e.status_code == 429 else 2) * 2**attempt)
                continue
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                last_err = e
                local_servers.forget(self._port)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * 2**attempt)
                continue

            if not getattr(response, "choices", None):
                # OpenRouter reports some upstream failures as HTTP 200 with an "error" body and no choices
                last_err = RuntimeError(f"no choices in response: {getattr(response, 'error', None) or response}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * 2**attempt)
                continue

            latency = (time.perf_counter() - start_time) * 1000.0
            choice = response.choices[0]
            usage = response.usage
            details = getattr(usage, "completion_tokens_details", None) if usage else None
            metrics = LLMUsageMetrics(
                prompt_tokens=(usage.prompt_tokens or 0) if usage else 0,
                completion_tokens=(usage.completion_tokens or 0) if usage else 0,
                reasoning_tokens=(getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
                total_tokens=(usage.total_tokens or 0) if usage else 0,
                latency_ms=latency,
                finish_reason=choice.finish_reason or "",
                model=target_model,
                provider=self.provider_name,
            )
            return choice.message.content or "", metrics

        raise RuntimeError(f"LLM request failed after {attempt + 1} attempt(s): {last_err}")

    async def generate_cot_decision(
        self,
        battle_state_str: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning: str = "off",
    ) -> ActionDecision:
        """Asks for one turn's decision and parses it. API failures raise; bad answers set parse_error."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_DIRECT_COT},
            {"role": "user", "content": USER_PROMPT_DIRECT_COT_TEMPLATE.format(battle_state=battle_state_str)},
        ]
        raw_text, metrics = await self.generate_completion(
            messages, model=model, temperature=temperature, max_tokens=max_tokens, reasoning=reasoning
        )
        decision = parse_decision(raw_text)
        if decision.parse_error and metrics.finish_reason == "length":
            decision.parse_error = f"answer cut off at the {max_tokens}-token budget ({decision.parse_error})"
        decision.metrics = metrics
        return decision
