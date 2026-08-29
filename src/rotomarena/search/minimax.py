"""PokéChamp Minimax Search Engine with Alpha-Beta Pruning and LLM Value Priors."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from poke_env.battle import Battle
from poke_env.player import BattleOrder, DefaultBattleOrder, SingleBattleOrder
from rotomarena.llm.client import LLMClient
from rotomarena.llm.prompts import format_battle_state
from rotomarena.search.heuristics import evaluate_battle_state
from rotomarena.search.opponent_model import sample_opponent_actions
from rotomarena.search.simulator import simulate_turn_outcome


class SearchTreeTelemetry(BaseModel):
    """Telemetry data captured during a Minimax search."""

    depth: int = 1
    nodes_evaluated: int = 0
    alpha_beta_cutoffs: int = 0
    llm_evaluations: int = 0
    search_duration_ms: float = 0.0
    candidate_scores: Dict[str, float] = Field(default_factory=dict)
    best_action: str = ""
    best_score: float = 0.0


class PokeChampSearchEngine:
    """Minimax search engine implementing the PokéChamp lookahead decision algorithm."""

    def __init__(
        self,
        depth: int = 1,
        use_llm_prior: bool = False,
        llm_client: Optional[LLMClient] = None,
        evaluation_weights: Optional[Dict[str, float]] = None,
        top_k_opp: int = 3,
    ):
        self.depth = max(1, depth)
        self.use_llm_prior = use_llm_prior
        self.llm_client = llm_client
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
        """
        Executes depth-limited Minimax search to find the optimal BattleOrder.
        """
        start_time = time.perf_counter()
        telemetry = SearchTreeTelemetry(depth=self.depth)

        # 1. Enumerate player legal actions
        player_actions: List[Tuple[str, Any, bool, str]] = []  # (type, object, is_tera, label)

        if battle.available_moves:
            for move in battle.available_moves:
                player_actions.append(("MOVE", move, False, f"MOVE:{move.id}"))
                if battle.can_tera:
                    player_actions.append(("MOVE", move, True, f"MOVE:{move.id}[TERA]"))

        if battle.available_switches:
            for switch_mon in battle.available_switches:
                player_actions.append(
                    ("SWITCH", switch_mon, False, f"SWITCH:{switch_mon.species}")
                )

        if not player_actions:
            telemetry.best_action = "DEFAULT"
            telemetry.best_score = evaluate_battle_state(battle, self.evaluation_weights)
            telemetry.search_duration_ms = (time.perf_counter() - start_time) * 1000.0
            return DefaultBattleOrder(), telemetry

        # 2. Minimax evaluation over candidate actions
        best_score = -float("inf")
        best_order: Optional[BattleOrder] = None
        best_label = ""
        alpha = -float("inf")
        beta = float("inf")

        # Sample opponent actions
        opp_actions = sample_opponent_actions(battle, top_k=self.top_k_opp)

        for act_type, act_obj, is_tera, label in player_actions:
            # Simulate worst-case / expected opponent response
            worst_opp_score = float("inf")
            target_id = act_obj.id if act_type == "MOVE" else act_obj.species

            for opp_type, opp_tgt, opp_weight in opp_actions:
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

                if sim_score < worst_opp_score:
                    worst_opp_score = sim_score

                # Alpha-Beta cutoff on opponent branch
                if worst_opp_score <= alpha:
                    telemetry.alpha_beta_cutoffs += 1
                    break

            # If LLM value prior is enabled, blend score for promising actions
            final_action_score = worst_opp_score
            if self.use_llm_prior and self.llm_client and final_action_score > -0.5:
                try:
                    telemetry.llm_evaluations += 1
                    state_summary = format_battle_state(battle)
                    llm_eval = await self.llm_client.evaluate_state(state_summary)
                    # Blend 70% heuristic + 30% LLM prior
                    final_action_score = 0.7 * worst_opp_score + 0.3 * llm_eval.score
                except Exception:
                    pass

            telemetry.candidate_scores[label] = round(final_action_score, 4)

            if final_action_score > best_score:
                best_score = final_action_score
                best_label = label
                if act_type == "MOVE":
                    best_order = SingleBattleOrder(act_obj, terastallize=is_tera)
                else:
                    best_order = SingleBattleOrder(act_obj)

            alpha = max(alpha, best_score)

        telemetry.best_action = best_label
        telemetry.best_score = round(best_score, 4)
        telemetry.search_duration_ms = (time.perf_counter() - start_time) * 1000.0

        if best_order is None:
            best_order = DefaultBattleOrder()

        return best_order, telemetry
