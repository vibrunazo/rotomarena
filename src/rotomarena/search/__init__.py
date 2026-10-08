"""Search, heuristics, and forward simulation for the PokéChamp agent.

Based on PokéChamp by Seth Karten, Andy Luu Nguyen and Chi Jin (ICML 2025, https://github.com/sethkarten/pokechamp),
MIT-licensed; see THIRD_PARTY_NOTICES.md. This version has no language model: actions, opponent replies and
positions come from hand-written rules instead."""

from rotomarena.search.heuristics import (
    TYPE_CHART,
    evaluate_battle_state,
    get_type_effectiveness,
)
from rotomarena.search.minimax import (
    PokeChampSearchEngine,
    SearchTreeTelemetry,
)
from rotomarena.search.opponent_model import sample_opponent_actions
from rotomarena.search.simulator import (
    estimate_damage_fraction,
    simulate_turn_outcome,
)

__all__ = [
    "TYPE_CHART",
    "evaluate_battle_state",
    "get_type_effectiveness",
    "PokeChampSearchEngine",
    "SearchTreeTelemetry",
    "sample_opponent_actions",
    "estimate_damage_fraction",
    "simulate_turn_outcome",
]
