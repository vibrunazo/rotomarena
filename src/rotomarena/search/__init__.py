"""Search, heuristics, and forward simulation for the PokéChamp agent.

Implements the minimax design of PokéChamp by Seth Karten, Andy Luu Nguyen and Chi Jin (ICML 2025,
https://github.com/sethkarten/pokechamp), written from the paper's description; no code from their repository.
Where PokéChamp uses a language model, for actions, opponent replies and positions, this uses hand-written rules.
See CREDITS.md."""

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
