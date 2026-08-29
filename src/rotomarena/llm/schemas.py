"""Pydantic schemas for LLM inputs, decisions, evaluations, and telemetry."""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class LLMUsageMetrics(BaseModel):
    """Token and latency metrics for an LLM API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    model: str = ""
    provider: str = ""


class ActionDecision(BaseModel):
    """Structured decision output from an LLM agent."""

    action_type: Literal["MOVE", "SWITCH"] = Field(
        ..., description="Type of action: MOVE or SWITCH"
    )
    target: str = Field(
        ..., description="Name of the move to use or Pokémon to switch into"
    )
    terastallize: bool = Field(
        default=False, description="Whether to Terastallize this turn"
    )
    reasoning: str = Field(
        default="", description="Strategic reasoning and Chain-of-Thought behind the decision"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence score for this action"
    )
    metrics: Optional[LLMUsageMetrics] = None


class StateEvaluation(BaseModel):
    """Leaf state evaluation score from an LLM for PokéChamp Minimax."""

    score: float = Field(
        ..., ge=-1.0, le=1.0, description="Estimated state advantage from -1.0 (loss) to +1.0 (win)"
    )
    win_probability: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Estimated probability of winning"
    )
    explanation: str = Field(
        default="", description="Brief evaluation reasoning"
    )
    metrics: Optional[LLMUsageMetrics] = None


class OpponentPrediction(BaseModel):
    """Predicted opponent action distribution."""

    predicted_action: str = Field(
        ..., description="Opponent's most likely move or switch"
    )
    probability: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Probability estimate"
    )
    rationale: str = Field(
        default="", description="Reasoning for opponent prediction"
    )
    metrics: Optional[LLMUsageMetrics] = None
