"""LLM communication, schemas, and prompt management package."""

from rotomarena.llm.client import LLMClient
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
    format_battle_state,
    format_pokemon_summary,
)

__all__ = [
    "LLMClient",
    "ActionDecision",
    "LLMUsageMetrics",
    "OpponentPrediction",
    "StateEvaluation",
    "SYSTEM_PROMPT_DIRECT_COT",
    "SYSTEM_PROMPT_OPPONENT_PREDICTION",
    "SYSTEM_PROMPT_VALUE_EVALUATION",
    "format_battle_state",
    "format_pokemon_summary",
]
