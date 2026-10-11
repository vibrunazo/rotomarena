"""PokéChamp one-turn maximin search over our actions and sampled opponent replies."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from poke_env.battle import Battle
from poke_env.player import BattleOrder, DefaultBattleOrder, SingleBattleOrder
from rotomarena.search.heuristics import evaluate_battle_state
from rotomarena.search.opponent_model import sample_opponent_actions
from rotomarena.search.simulator import simulate_turn_outcome


class SearchTreeTelemetry(BaseModel):
    """Telemetry data captured during a search."""

    nodes_evaluated: int = 0
    alpha_beta_cutoffs: int = 0
    search_duration_ms: float = 0.0
    candidate_scores: Dict[str, float] = Field(default_factory=dict)
    best_action: str = ""
    best_score: float = 0.0


class PokeChampSearchEngine:
    """Scores each legal action by its worst outcome against the opponent's likeliest replies."""

    def __init__(
        self,
        evaluation_weights: Optional[Dict[str, float]] = None,
        top_k_opp: int = 3,
    ):
        self.evaluation_weights = evaluation_weights or {
            "alive_pokemon": 3.0,
            "hp_diff": 2.0,
            "status": 1.0,
            "boosts": 0.5,
            "hazards": 0.5,
            "matchup": 1.0,
        }
        self.top_k_opp = top_k_opp

    async def search(self, battle: Battle) -> Tuple[BattleOrder, SearchTreeTelemetry]:
        """Picks the action whose worst simulated outcome is best (alpha-beta pruned)."""
        start_time = time.perf_counter()
        telemetry = SearchTreeTelemetry()

        player_actions: List[Tuple[str, Any, bool, str]] = []  # (type, object, is_tera, label)
        if battle.available_moves:
            for move in battle.available_moves:
                player_actions.append(("MOVE", move, False, f"MOVE:{move.id}"))
                if battle.can_tera:
                    player_actions.append(("MOVE", move, True, f"MOVE:{move.id}[TERA]"))
        if battle.available_switches:
            for switch_mon in battle.available_switches:
                player_actions.append(("SWITCH", switch_mon, False, f"SWITCH:{switch_mon.species}"))

        if not player_actions:
            telemetry.best_action = "DEFAULT"
            telemetry.best_score = evaluate_battle_state(battle, self.evaluation_weights)
            telemetry.search_duration_ms = (time.perf_counter() - start_time) * 1000.0
            return DefaultBattleOrder(), telemetry

        best_score = -float("inf")
        best_order: Optional[BattleOrder] = None
        best_label = ""
        alpha = -float("inf")
        opp_actions = sample_opponent_actions(battle, top_k=self.top_k_opp)

        for act_type, act_obj, is_tera, label in player_actions:
            worst_opp_score = float("inf")
            target_id = act_obj.id if act_type == "MOVE" else act_obj.species

            for opp_type, opp_tgt, _ in opp_actions:
                telemetry.nodes_evaluated += 1
                sim_score = simulate_turn_outcome(
                    battle,
                    player_action_type=act_type,
                    player_action_target=target_id,
                    player_tera=is_tera,
                    opp_action_type=opp_type,
                    opp_action_target=opp_tgt,
                    weights=self.evaluation_weights,
                )
                worst_opp_score = min(worst_opp_score, sim_score)
                if worst_opp_score <= alpha:
                    telemetry.alpha_beta_cutoffs += 1
                    break

            telemetry.candidate_scores[label] = round(worst_opp_score, 4)
            if worst_opp_score > best_score:
                best_score = worst_opp_score
                best_label = label
                # Champions: Mega Evolve at the first chance, as strong players do (a free ~100 base stat points)
                best_order = (SingleBattleOrder(act_obj, terastallize=is_tera, mega=bool(battle.can_mega_evolve))
                              if act_type == "MOVE" else SingleBattleOrder(act_obj))
            alpha = max(alpha, best_score)

        telemetry.best_action = best_label
        telemetry.best_score = round(best_score, 4)
        telemetry.search_duration_ms = (time.perf_counter() - start_time) * 1000.0
        return best_order or DefaultBattleOrder(), telemetry
