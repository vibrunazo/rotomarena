"""Search, heuristics, and forward simulation package for PokéChamp."""

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
