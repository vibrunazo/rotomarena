"""Decision models ("System One"): instead of writing text, they answer typed questions about a state with a
probability for every option (OpenRouter's Decisions API, POST /api/alpha/decisions). RotomArena only asks Choice
questions: which action this turn, which Pokémon, item or move."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from rotomarena.config import AppConfig, ProviderConfig
from rotomarena.llm.client import _RATE_LIMIT_WAITS, ProviderLimitError, _is_quota
from rotomarena.llm.schemas import LLMUsageMetrics

MAX_OPTIONS = 255  # per Choice question
DECISIONS_PATH = "/api/alpha/decisions"


@dataclass
class Choice:
    """One answered Choice question: the pick and the probability of every option."""

    choice: str
    probabilities: Dict[str, float]
    confidence: Optional[float] = None

    def summary(self, top: int = 3) -> str:
        """'71% MOVE: earthquake, 18% SWITCH: Corviknight, 6% ...' (the top options)."""
        best = sorted(self.probabilities.items(), key=lambda kv: kv[1], reverse=True)[:top]
        return ", ".join(f"{p * 100:.0f}% {k}" for k, p in best)


@dataclass
class Usage:
    requests: int = 0
    input_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    model: str = ""

    def add(self, other: "Usage") -> None:
        self.requests += other.requests
        self.input_tokens += other.input_tokens
        self.cost_usd += other.cost_usd
        self.latency_ms += other.latency_ms
        self.model = other.model or self.model

    def metrics(self, provider: str) -> LLMUsageMetrics:
        return LLMUsageMetrics(prompt_tokens=self.input_tokens, total_tokens=self.input_tokens,
                               latency_ms=self.latency_ms, finish_reason="decision", cost_usd=self.cost_usd,
                               model=self.model, provider=provider)


@dataclass
class Question:
    instructions: str
    options: Dict[str, str]  # {option key: what it means}


@dataclass
class _Plan:
    """A question split into chunks of at most MAX_OPTIONS (asked side by side), then a final among their picks."""

    question: Question
    chunks: List[Dict[str, str]] = field(default_factory=list)


class DecisionClient:
    """Asks a decision model Choice questions through OpenRouter."""

    def __init__(self, provider: ProviderConfig, model: str, provider_name: str = "openrouter"):
        root = provider.base_url.rstrip("/")
        self.url = (root[: -len("/api/v1")] if root.endswith("/api/v1") else root) + DECISIONS_PATH
        self.api_key = provider.get_api_key()
        self.model = model
        self.provider_name = provider_name

    @classmethod
    def for_model(cls, model: str, app_cfg: AppConfig, provider: str = "openrouter") -> "DecisionClient":
        return cls(app_cfg.providers[provider], model, provider)

    async def _post(self, state: Any, questions: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Any], Usage]:
        body = {"model": self.model, "state": state, "questions": questions}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        waits = list(_RATE_LIMIT_WAITS)
        errors = 0
        while True:
            start = time.perf_counter()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.url, json=body, headers=headers,
                                            timeout=aiohttp.ClientTimeout(total=120)) as r:
                        data = await r.json(content_type=None)
                        status = r.status
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                errors += 1
                if errors >= 3:
                    raise RuntimeError(f"decision request failed after 3 attempts: {e}") from e
                await asyncio.sleep(2 * errors)
                continue
            message = str((data or {}).get("error") or data)[:500] if status != 200 else ""
            if status == 402 or (status == 429 and _is_quota(message)):
                raise ProviderLimitError(f"{status}: {message}")
            if status == 429:
                if not waits:
                    raise ProviderLimitError(f"rate limited for minutes: {message}")
                await asyncio.sleep(waits.pop(0))
                continue
            if status >= 500 or "answers" not in (data or {}):
                errors += 1
                if errors >= 3:
                    raise RuntimeError(f"decision request failed ({status}): {message or str(data)[:500]}")
                await asyncio.sleep(2 * errors)
                continue
            usage = data.get("usage") or {}
            return data["answers"], Usage(requests=1, input_tokens=int(usage.get("input_tokens") or 0),
                                          cost_usd=float(usage.get("cost") or 0.0),
                                          latency_ms=(time.perf_counter() - start) * 1000,
                                          model=data.get("model") or self.model)

    async def choose(self, state: Any, questions: Dict[str, Question]) -> Tuple[Dict[str, Choice], Usage]:
        """Answers every question (independent of each other) in one request, or two when a question has more
        than MAX_OPTIONS options: its chunks are asked side by side, then a final among the chunks' picks.
        A question with one option has nothing to decide (and OpenAI's endpoint refuses it): it is answered here."""
        out: Dict[str, Choice] = {name: Choice(next(iter(q.options)), {next(iter(q.options)): 1.0}, 1.0)
                                  for name, q in questions.items() if len(q.options) == 1}
        plans = {name: _Plan(q, _chunks(q.options)) for name, q in questions.items() if name not in out}
        if not plans:
            return out, Usage()
        first: Dict[str, Dict[str, Any]] = {}
        for name, plan in plans.items():
            for i, chunk in enumerate(plan.chunks):
                key = name if len(plan.chunks) == 1 else f"{name}__part{i + 1}"
                first[key] = _choice_question(plan.question.instructions, chunk)
        answers, usage = await self._post(state, first)

        finals: Dict[str, Dict[str, Any]] = {}
        for name, plan in plans.items():
            if len(plan.chunks) == 1:
                out[name] = _parse(answers[name], plan.question.options)
            else:
                picks = [_parse(answers[f"{name}__part{i + 1}"], chunk).choice for i, chunk in enumerate(plan.chunks)]
                finals[name] = _choice_question(plan.question.instructions,
                                                {k: plan.question.options[k] for k in picks})
        if finals:
            answers, more = await self._post(state, finals)
            usage.add(more)
            for name in finals:
                out[name] = _parse(answers[name], {k: "" for k in finals[name]["criteria"]})
        return out, usage


def _chunks(options: Dict[str, str]) -> List[Dict[str, str]]:
    items = list(options.items())
    n = math.ceil(len(items) / MAX_OPTIONS) or 1
    size = math.ceil(len(items) / n) or 1
    return [dict(items[i:i + size]) for i in range(0, len(items), size)]


def _choice_question(instructions: str, options: Dict[str, str]) -> Dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def _parse(answer: Dict[str, Any], options: Dict[str, str]) -> Choice:
    choice = answer.get("choice")
    if choice not in options:
        raise RuntimeError(f"the decision model answered {choice!r}, not one of the options")
    probabilities = {k: float(v) for k, v in (answer.get("probabilities") or {}).items()}
    return Choice(choice=choice, probabilities=probabilities, confidence=answer.get("confidence"))
