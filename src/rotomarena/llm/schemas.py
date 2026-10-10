"""Pydantic schemas for LLM decisions and telemetry."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class LLMUsageMetrics(BaseModel):
    """Token and latency metrics for an LLM API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = ""
    cost_usd: float = 0.0  # as reported by the provider (OpenRouter); 0 for local models
    cost_estimated: bool = False  # OpenRouter reported no cost: tokens x its list prices (llm/pricing.py)
    model: str = ""
    provider: str = ""


class ActionDecision(BaseModel):
    """An LLM's parsed answer for one turn. `parse_error` is set when the answer has no usable action."""

    action_type: Optional[Literal["MOVE", "SWITCH", "LEAD"]] = Field(
        default=None, description="MOVE, SWITCH or (at team preview) LEAD; None when parsing failed"
    )
    target: str = Field(
        default="", description="Showdown id of the move or species (lowercase letters and digits)"
    )
    mega_evolve: bool = Field(
        default=False, description="True only when the action line carries a [MEGA] tag (Mega Evolve, then move)"
    )
    terastallize: bool = Field(
        default=False, description="True only when the action line carries a [TERA] tag"
    )
    reasoning: str = Field(
        default="", description="Contents of the <thought> block"
    )
    parse_error: Optional[str] = None
    hidden_reasoning: str = ""
    raw_response: str = ""
    metrics: Optional[LLMUsageMetrics] = None
