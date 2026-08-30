"""Provider-agnostic OpenAI-compatible LLM client for RotomArena."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import openai
from openai import AsyncOpenAI

from rotomarena.config import ProviderConfig
from rotomarena.llm.schemas import (
    ActionDecision,
    LLMUsageMetrics,
    OpponentPrediction,
    StateEvaluation,
)
from rotomarena.llm.prompts import (
    SYSTEM_PROMPT_DIRECT_COT,
    SYSTEM_PROMPT_OPPONENT_PREDICTION,
    SYSTEM_PROMPT_VALUE_EVALUATION,
    USER_PROMPT_DIRECT_COT_TEMPLATE,
    format_battle_state,
)


class LLMClient:
    """Async OpenAI-compatible LLM Client supporting Gemini, OpenRouter, and Ollama."""

    def __init__(
        self,
        provider_config: Optional[ProviderConfig] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        provider_name: str = "custom",
    ):
        if provider_config:
            self.base_url = provider_config.base_url
            self.api_key = provider_config.get_api_key()
            self.default_model = provider_config.default_model
            self.temperature = provider_config.temperature
            self.timeout = provider_config.timeout
            self.provider_name = provider_name
            self.reasoning_effort = getattr(provider_config, "reasoning_effort", None)
            if not self.reasoning_effort and ("openrouter" in (provider_name or "").lower() or "openrouter.ai" in (self.base_url or "").lower()):
                self.reasoning_effort = "medium"
        else:
            self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
            self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY", "dummy")
            self.default_model = default_model or os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
            self.temperature = 0.2
            self.timeout = 30.0
            self.provider_name = provider_name
            self.reasoning_effort = "medium" if ("openrouter" in (provider_name or "").lower() or "openrouter.ai" in (self.base_url or "").lower()) else None

        headers = {}
        if "openrouter.ai" in self.base_url:
            headers = {
                "HTTP-Referer": "https://github.com/rotomarena",
                "X-Title": "RotomArena",
            }

        self._client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key or "dummy",
            timeout=self.timeout,
            default_headers=headers if headers else None,
        )

    @classmethod
    def from_provider_name(
        cls,
        name: str,
        providers_dict: Optional[Dict[str, ProviderConfig]] = None,
        model_override: Optional[str] = None,
    ) -> "LLMClient":
        """Factory method to instantiate a client for a named provider profile."""
        if providers_dict and name in providers_dict:
            config = providers_dict[name]
            if model_override:
                config = config.model_copy(update={"default_model": model_override})
            return cls(provider_config=config, provider_name=name)

        # Built-in presets
        if name == "gemini":
            return cls(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", ""),
                default_model=model_override or os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
                provider_name="gemini",
            )
        elif name == "openrouter":
            return cls(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY", ""),
                default_model=model_override or "anthropic/claude-3.5-sonnet",
                provider_name="openrouter",
            )
        elif name == "ollama":
            return cls(
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                api_key="ollama",
                default_model=model_override or "llama3.3:70b",
                provider_name="ollama",
            )
        elif name == "vllm":
            return cls(
                base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
                api_key="vllm",
                default_model=model_override or "meta-llama/Llama-3.3-70B-Instruct",
                provider_name="vllm",
            )

        return cls(provider_name=name, default_model=model_override)

    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
        max_retries: int = 3,
    ) -> Tuple[str, LLMUsageMetrics]:
        """Calls the OpenAI-compatible API with retry and telemetry collection."""
        target_model = model or self.default_model
        temp = temperature if temperature is not None else self.temperature
        effort = reasoning_effort or self.reasoning_effort

        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            start_time = time.perf_counter()
            try:
                create_kwargs: Dict[str, Any] = {
                    "model": target_model,
                    "messages": messages,
                    "temperature": temp,
                }
                if effort:
                    create_kwargs["extra_body"] = {"reasoning": {"effort": effort}}

                response = await self._client.chat.completions.create(**create_kwargs)
                latency = (time.perf_counter() - start_time) * 1000.0

                content = response.choices[0].message.content or ""
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0
                if response.usage:
                    prompt_tokens = response.usage.prompt_tokens or 0
                    completion_tokens = response.usage.completion_tokens or 0
                    total_tokens = response.usage.total_tokens or 0

                metrics = LLMUsageMetrics(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency,
                    model=target_model,
                    provider=self.provider_name,
                )
                return content, metrics

            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)

        raise RuntimeError(
            f"LLM request failed after {max_retries} attempts: {last_err}"
        )

    async def generate_cot_decision(
        self,
        battle_state_str: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> ActionDecision:
        """Executes a single-call Chain-of-Thought decision for a battle turn."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_DIRECT_COT},
            {
                "role": "user",
                "content": USER_PROMPT_DIRECT_COT_TEMPLATE.format(
                    battle_state=battle_state_str
                ),
            },
        ]

        raw_text, metrics = await self.generate_completion(
            messages, model=model, temperature=temperature
        )

        # Parse reasoning & decision
        reasoning = ""
        thought_match = re.search(r"<thought>(.*?)</thought>", raw_text, re.DOTALL | re.IGNORECASE)
        if thought_match:
            reasoning = thought_match.group(1).strip()
        else:
            reasoning = raw_text

        decision_block = raw_text
        decision_match = re.search(r"<decision>(.*?)</decision>", raw_text, re.DOTALL | re.IGNORECASE)
        if decision_match:
            decision_block = decision_match.group(1).strip()

        # Extract MOVE or SWITCH
        is_tera = "[TERA]" in decision_block.upper() or "TERA" in decision_block.upper()
        
        switch_match = re.search(r"SWITCH:\s*([a-zA-Z0-9_\-\s]+)", decision_block, re.IGNORECASE)
        move_match = re.search(r"MOVE:\s*([a-zA-Z0-9_\-\s]+)", decision_block, re.IGNORECASE)
        action_match = re.search(r"ACTION:\s*([a-zA-Z0-9_\-\s:]+)", decision_block, re.IGNORECASE)

        if "SWITCH" in decision_block.upper() and switch_match:
            target = switch_match.group(1).split("[")[0].strip().lower().replace(" ", "").replace("-", "")
            return ActionDecision(
                action_type="SWITCH",
                target=target,
                terastallize=False,
                reasoning=reasoning,
                metrics=metrics,
            )
        elif move_match:
            raw_target = move_match.group(1).split("[")[0].strip().lower().replace(" ", "").replace("-", "")
            return ActionDecision(
                action_type="MOVE",
                target=raw_target,
                terastallize=is_tera,
                reasoning=reasoning,
                metrics=metrics,
            )
        elif action_match:
            act_text = action_match.group(1).strip()
            if "switch" in act_text.lower():
                target = act_text.lower().split("switch:")[-1].split("[")[0].strip().replace(" ", "").replace("-", "")
                return ActionDecision(
                    action_type="SWITCH",
                    target=target,
                    terastallize=False,
                    reasoning=reasoning,
                    metrics=metrics,
                )
            else:
                target = act_text.lower().replace("move:", "").split("[")[0].strip().replace(" ", "").replace("-", "")
                return ActionDecision(
                    action_type="MOVE",
                    target=target,
                    terastallize=is_tera,
                    reasoning=reasoning,
                    metrics=metrics,
                )
        else:
            clean_str = decision_block.lower().replace("action:", "").replace("move:", "").split("[")[0].strip().replace(" ", "").replace("-", "")
            return ActionDecision(
                action_type="MOVE",
                target=clean_str,
                terastallize=is_tera,
                reasoning=reasoning,
                metrics=metrics,
            )

    async def evaluate_state(
        self,
        battle_state_str: str,
        model: Optional[str] = None,
    ) -> StateEvaluation:
        """Evaluates a leaf board position using LLM value function prior."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_VALUE_EVALUATION},
            {
                "role": "user",
                "content": f"Evaluate this battle position:\n\n{battle_state_str}",
            },
        ]
        raw_text, metrics = await self.generate_completion(
            messages, model=model, temperature=0.0
        )
        try:
            # Clean JSON markdown fences if present
            cleaned = re.sub(r"^```json\s*", "", raw_text.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)
            data = json.loads(cleaned)
            score = float(data.get("score", 0.0))
            win_prob = float(data.get("win_probability", 0.5))
            explanation = str(data.get("explanation", ""))
            return StateEvaluation(
                score=max(-1.0, min(1.0, score)),
                win_probability=max(0.0, min(1.0, win_prob)),
                explanation=explanation,
                metrics=metrics,
            )
        except Exception:
            return StateEvaluation(score=0.0, win_probability=0.5, metrics=metrics)

    async def predict_opponent(
        self,
        battle_state_str: str,
        model: Optional[str] = None,
    ) -> OpponentPrediction:
        """Predicts the opponent's next action."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_OPPONENT_PREDICTION},
            {
                "role": "user",
                "content": f"Predict opponent action for state:\n\n{battle_state_str}",
            },
        ]
        raw_text, metrics = await self.generate_completion(
            messages, model=model, temperature=0.1
        )
        try:
            cleaned = re.sub(r"^```json\s*", "", raw_text.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)
            data = json.loads(cleaned)
            return OpponentPrediction(
                predicted_action=str(data.get("predicted_action", "attack")),
                probability=float(data.get("probability", 0.5)),
                rationale=str(data.get("rationale", "")),
                metrics=metrics,
            )
        except Exception:
            return OpponentPrediction(predicted_action="attack", metrics=metrics)
