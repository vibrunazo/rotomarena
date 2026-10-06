"""LLM communication, schemas, and prompt management package."""

from rotomarena.llm.client import LLMClient, parse_decision, to_id
from rotomarena.llm.schemas import ActionDecision, LLMUsageMetrics
from rotomarena.llm.prompts import (
    SYSTEM_PROMPT_DIRECT_COT,
    format_battle_state,
    format_pokemon_summary,
)

__all__ = [
    "LLMClient",
    "parse_decision",
    "to_id",
    "ActionDecision",
    "LLMUsageMetrics",
    "SYSTEM_PROMPT_DIRECT_COT",
    "format_battle_state",
    "format_pokemon_summary",
]
