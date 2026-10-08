"""Provider-agnostic OpenAI-compatible LLM client and decision parser for RotomArena."""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
import openai
from openai import AsyncOpenAI

from rotomarena import local_servers
from rotomarena.config import ProviderConfig, provider_presets
from rotomarena.llm.prompts import SYSTEM_PROMPT_DIRECT_COT, USER_PROMPT_DIRECT_COT_TEMPLATE
from rotomarena.llm.schemas import ActionDecision, LLMUsageMetrics


class ProviderLimitError(RuntimeError):
    """The provider will not answer for a while: out of credits (402), a daily quota, or a rate limit that
    outlasted the backoff. Retrying turn by turn only voids games, so unattended runs stop on it."""


# Backoff for HTTP 429 before giving up: about 6.5 minutes in all.
_RATE_LIMIT_WAITS = [10, 20, 40, 80, 120, 120]


def _is_quota(message: str) -> bool:
    """OpenRouter's free-model cap reads "Rate limit exceeded: free-models-per-day"; waiting minutes won't help."""
    return bool(re.search(r"per[- ]day|daily|quota|credits", message, re.IGNORECASE))


def _error_code(error: Any) -> int:
    code = error.get("code") if isinstance(error, dict) else getattr(error, "code", None)
    try:
        return int(code)
    except (TypeError, ValueError):
        return 0


@dataclass
class Completion:
    text: str
    reasoning: str  # hidden thinking, empty when the provider doesn't return it
    metrics: LLMUsageMetrics


def _extra(obj: Any, name: str) -> Any:
    """A field the OpenAI SDK doesn't declare (provider extensions), if present."""
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value is None and getattr(obj, "model_extra", None):
        value = obj.model_extra.get(name)
    return value


def to_id(text: str) -> str:
    """Showdown's toID: lowercase letters and digits only ('Landorus-Therian' -> 'landorustherian')."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


# One action line, allowing list markers, bold and an "ACTION:" prefix around "MOVE: x" / "SWITCH: x".
_ACTION_LINE = re.compile(
    r"^\s*(?:[-*>•]|\d+[.)])?\s*(?:ACTION\s*:\s*)?\**\s*(MOVE|SWITCH|LEAD)\s*\**\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TERA_TAG = re.compile(r"\[\s*TERA\s*\]", re.IGNORECASE)

class _LocalGate:
    """Local llama.cpp servers share one GPU, CPU and memory bus. Two different models generating at once ran Qwen at
    0.5 tok/s instead of 11.5, so one model generates at a time. Requests to the same model go together: its server
    batches them, which is where games played in parallel gain (2.4x for GPT-OSS at four at once).
    Requests are served in arrival order, so a model can't keep the GPU while another one waits."""

    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._queue: List[Tuple[object, int]] = []
        self._port: Optional[int] = None
        self._active = 0

    def _may_enter(self, entry: Tuple[object, int]) -> bool:
        port = entry[1]
        if self._port not in (None, port):
            return False
        for queued in self._queue:  # only the run of same-model requests at the front of the queue
            if queued is entry:
                return True
            if queued[1] != port:
                return False
        return False

    @asynccontextmanager
    async def use(self, port: int) -> AsyncIterator[None]:
        entry = (object(), port)
        async with self._cond:
            self._queue.append(entry)
            await self._cond.wait_for(lambda: self._may_enter(entry))
            self._queue.remove(entry)
            self._port, self._active = port, self._active + 1
            self._cond.notify_all()  # same-model requests behind this one may go too
        try:
            yield
        finally:
            async with self._cond:
                self._active -= 1
                if not self._active:
                    self._port = None
                self._cond.notify_all()


# asyncio primitives bind to the event loop they first wait in, and `ladder place-all` runs one loop per model.
_gate: Optional[_LocalGate] = None
_gate_loop: Optional[asyncio.AbstractEventLoop] = None


def _local_gate() -> _LocalGate:
    global _gate, _gate_loop
    loop = asyncio.get_running_loop()
    if _gate is None or _gate_loop is not loop:
        _gate, _gate_loop = _LocalGate(), loop
    return _gate


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
        return failed("no MOVE, SWITCH or LEAD line in <decision>")
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
            # usage.include: OpenRouter reports what each request cost
            return {"extra_body": {"reasoning": setting, "usage": {"include": True}}}
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
    ) -> Completion:
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
        attempt = 0  # server and connection failures; rate limits have their own budget
        limited = 0
        while True:
            status, message = 0, ""
            try:
                if self.config.api_style == "llama.cpp":
                    async with _local_gate().use(self._port):
                        await local_servers.ensure_loaded(self._port)  # swap mode: load this model first
                        start_time = time.perf_counter()  # latency excludes the wait and the load
                        response = await self._client.chat.completions.create(**create_kwargs)
                else:
                    start_time = time.perf_counter()
                    response = await self._client.chat.completions.create(**create_kwargs)
            except openai.APIStatusError as e:
                last_err, status, message = e, e.status_code, str(e)
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                last_err = e
                local_servers.forget(self._port)
            else:
                if getattr(response, "choices", None):
                    break
                # OpenRouter reports some upstream failures as HTTP 200 with an "error" body and no choices
                error = _extra(response, "error")
                last_err = RuntimeError(f"no choices in response: {error or response}")
                status, message = _error_code(error), str(error or "")

            if status == 402 or (status == 429 and _is_quota(message)):
                raise ProviderLimitError(f"{self.provider_name} {target_model}: HTTP {status}: {message}") from last_err
            if status == 429:
                if limited == len(_RATE_LIMIT_WAITS):
                    raise ProviderLimitError(
                        f"{self.provider_name} {target_model}: still rate limited after "
                        f"{sum(_RATE_LIMIT_WAITS)} s of backoff: {message}"
                    ) from last_err
                await asyncio.sleep(_RATE_LIMIT_WAITS[limited])
                limited += 1
                continue
            attempt += 1
            if 0 < status < 500 or attempt >= max_retries:  # 4xx: bad request, auth or unknown model
                raise RuntimeError(f"LLM request failed after {attempt} attempt(s): {last_err}")
            await asyncio.sleep(2 * 2 ** (attempt - 1))

        latency = (time.perf_counter() - start_time) * 1000.0
        choice = response.choices[0]
        usage = response.usage
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        cost = _extra(usage, "cost")
        metrics = LLMUsageMetrics(
            prompt_tokens=(usage.prompt_tokens or 0) if usage else 0,
            completion_tokens=(usage.completion_tokens or 0) if usage else 0,
            reasoning_tokens=(getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
            total_tokens=(usage.total_tokens or 0) if usage else 0,
            latency_ms=latency,
            finish_reason=choice.finish_reason or "",
            cost_usd=float(cost) if cost else 0.0,
            model=target_model,
            provider=self.provider_name,
        )
        # Hidden thinking, when the provider returns it: llama.cpp and DeepSeek use reasoning_content,
        # OpenRouter uses reasoning. Some providers (OpenAI) return none, others a summary.
        hidden = _extra(choice.message, "reasoning_content") or _extra(choice.message, "reasoning") or ""
        return Completion(choice.message.content or "", str(hidden), metrics)

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
        completion = await self.generate_completion(
            messages, model=model, temperature=temperature, max_tokens=max_tokens, reasoning=reasoning
        )
        raw_text, metrics = completion.text, completion.metrics
        hidden = completion.reasoning
        if "<decision>" not in raw_text.lower() and "<decision>" in hidden.lower():
            # The server didn't recognise the model's end-of-thinking tag (K2-Horizon's "</ifm|think>"), so the
            # answer was filed under reasoning: the answer is whatever follows the last closing think tag.
            ends = list(re.finditer(r"</[^>\s]*think[^>]*>", hidden, re.IGNORECASE))
            cut = ends[-1].end() if ends else hidden.lower().rfind("<thought>")
            raw_text, hidden = hidden[max(cut, 0):], hidden[:max(cut, 0)]
        decision = parse_decision(raw_text)
        if decision.parse_error and metrics.finish_reason == "length":
            decision.parse_error = f"answer cut off at the {max_tokens}-token budget ({decision.parse_error})"
        decision.metrics = metrics
        decision.hidden_reasoning = hidden
        return decision
