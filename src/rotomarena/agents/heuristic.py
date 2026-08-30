"""Baseline Heuristic Players (MaxDamage and 1-ply Evaluator) for calibration."""

from __future__ import annotations

from typing import Dict, Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.search.heuristics import evaluate_battle_state
from rotomarena.search.simulator import estimate_damage_fraction, simulate_turn_outcome


class MaxDamagePlayer(BaseBenchmarkPlayer):
    """Simple baseline player that always selects the highest calculated damage move."""

    def __init__(
        self,
        player_name: str = "MaxDamageBot",
        battle_format: str = "gen9ou",
        team: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            player_name=player_name,
            agent_type="max_damage",
            battle_format=battle_format,
            team=team,
            **kwargs,
        )

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        if not battle.available_moves:
            order = self.choose_default_order(battle)
            self.record_turn_telemetry(battle, order, reasoning="No moves available, switching.")
            return order

        best_move = battle.available_moves[0]
        max_dmg = -1.0
        should_tera = False

        if battle.active_pokemon and battle.opponent_active_pokemon:
            for move in battle.available_moves:
                dmg = estimate_damage_fraction(
                    move, battle.active_pokemon, battle.opponent_active_pokemon, is_tera=False
                )
                if dmg > max_dmg:
                    max_dmg = dmg
                    best_move = move
                    should_tera = False

                if battle.can_tera:
                    dmg_tera = estimate_damage_fraction(
                        move, battle.active_pokemon, battle.opponent_active_pokemon, is_tera=True
                    )
                    if dmg_tera > max_dmg:
                        max_dmg = dmg_tera
                        best_move = move
                        should_tera = True

        order = self.create_order(best_move, terastallize=should_tera)
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=order,
            reasoning=f"MaxDamage selected '{best_move.id}' (Estimated damage: {max_dmg*100:.1f}% HP, Tera: {should_tera})",
        )
        return order


class HeuristicPlayer(BaseBenchmarkPlayer):
    """1-ply heuristic player evaluating all candidate moves and switches."""

    def __init__(
        self,
        player_name: str = "HeuristicBot",
        evaluation_weights: Optional[Dict[str, float]] = None,
        battle_format: str = "gen9ou",
        team: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            player_name=player_name,
            agent_type="heuristic",
            battle_format=battle_format,
            team=team,
            **kwargs,
        )
        self.weights = evaluation_weights

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        best_score = -float("inf")
        best_order = self.choose_default_order(battle)
        best_reason = "Default fallback"

        # Check moves
        if battle.available_moves:
            for move in battle.available_moves:
                score = simulate_turn_outcome(
                    battle,
                    player_action_type="MOVE",
                    player_action_target=move.id,
                    player_tera=False,
                    opp_action_type="MOVE",
                    opp_action_target="attack_neutral",
                    weights=self.weights,
                )
                if score > best_score:
                    best_score = score
                    best_order = self.create_order(move, terastallize=False)
                    best_reason = f"Evaluated move '{move.id}' score: {score:.3f}"

                if battle.can_tera:
                    score_tera = simulate_turn_outcome(
                        battle,
                        player_action_type="MOVE",
                        player_action_target=move.id,
                        player_tera=True,
                        opp_action_type="MOVE",
                        opp_action_target="attack_neutral",
                        weights=self.weights,
                    )
                    if score_tera > best_score:
                        best_score = score_tera
                        best_order = self.create_order(move, terastallize=True)
                        best_reason = f"Evaluated Tera move '{move.id}' score: {score_tera:.3f}"

        # Check switches
        if battle.available_switches:
            for s in battle.available_switches:
                score_sw = simulate_turn_outcome(
                    battle,
                    player_action_type="SWITCH",
                    player_action_target=s.species,
                    player_tera=False,
                    opp_action_type="MOVE",
                    opp_action_target="attack_neutral",
                    weights=self.weights,
                )
                if score_sw > best_score:
                    best_score = score_sw
                    best_order = self.create_order(s)
                    best_reason = f"Evaluated switch to '{s.species}' score: {score_sw:.3f}"

        self.record_turn_telemetry(
            battle=battle,
            chosen_order=best_order,
            reasoning=best_reason,
        )
        return best_order
