"""Fast battle forward simulator and damage estimation model for lookahead search."""

from __future__ import annotations

from typing import Dict, Optional, Tuple
from poke_env.battle import Battle, Move, MoveCategory, Pokemon, Status
from rotomarena.search.heuristics import evaluate_battle_state, get_type_effectiveness


def estimate_damage_fraction(
    move: Move,
    attacker: Pokemon,
    defender: Pokemon,
    is_tera: bool = False,
) -> float:
    """Estimates the fraction of defender max HP that the given move will inflict."""
    if not move or move.category == MoveCategory.STATUS or move.base_power <= 0:
        return 0.0

    power = float(move.base_power)
    move_type = move.type.name.upper() if move.type else "NORMAL"

    # Defending types
    def_types = [t.name.upper() for t in defender.types if t]
    type_mult = get_type_effectiveness(move_type, def_types)
    if type_mult == 0.0:
        return 0.0

    # STAB (Same-Type Attack Bonus)
    attacker_types = [t.name.upper() for t in attacker.types if t]
    stab = 1.0
    if is_tera and attacker.tera_type and attacker.tera_type.name.upper() == move_type:
        stab = 2.0
    elif move_type in attacker_types:
        stab = 1.5

    # Stat approximation (Base level 100)
    # Physical vs Special
    if move.category == MoveCategory.PHYSICAL:
        atk_stat = attacker.stats.get("atk", 300) or 300
        # Account for boosts
        atk_boost = attacker.boosts.get("atk", 0)
        atk_stat = atk_stat * max(2, 2 + atk_boost) / max(2, 2 - atk_boost)

        def_stat = defender.stats.get("def", 250) or 250
        def_boost = defender.boosts.get("def", 0)
        def_stat = def_stat * max(2, 2 + def_boost) / max(2, 2 - def_boost)

        if attacker.status == Status.BRN and attacker.ability != "guts":
            atk_stat *= 0.5
    else:
        atk_stat = attacker.stats.get("spa", 300) or 300
        atk_boost = attacker.boosts.get("spa", 0)
        atk_stat = atk_stat * max(2, 2 + atk_boost) / max(2, 2 - atk_boost)

        def_stat = defender.stats.get("spd", 250) or 250
        def_boost = defender.boosts.get("spd", 0)
        def_stat = def_stat * max(2, 2 + def_boost) / max(2, 2 - def_boost)

    # Standard damage formula: ( (42 * Power * Atk / Def) / 50 + 2 ) * modifiers
    raw_damage = ((42.0 * power * (atk_stat / max(1.0, def_stat))) / 50.0 + 2.0)
    final_damage = raw_damage * stab * type_mult

    # Estimate defender HP
    max_hp = defender.max_hp or 300
    damage_fraction = final_damage / float(max_hp)
    return min(1.0, max(0.0, damage_fraction))


def simulate_turn_outcome(
    battle: Battle,
    player_action_type: str,  # 'MOVE' or 'SWITCH'
    player_action_target: str,  # move_id or species
    player_tera: bool,
    opp_action_type: str,
    opp_action_target: str,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """
    Simulates a 1-turn transition between player action and opponent action,
    returning the estimated resulting state score.
    """
    base_eval = evaluate_battle_state(battle, weights)
    if not battle.active_pokemon or not battle.opponent_active_pokemon:
        return base_eval

    # 1. Player switch action
    if player_action_type == "SWITCH":
        # Check hazard penalty on switch-in
        hazard_pen = 0.0
        if "STEALTH_ROCK" in battle.side_conditions:
            hazard_pen += 0.125
        # Opponent free attack on switch-in
        opp_damage = 0.35  # Approximate neutral hit
        delta = - (hazard_pen + opp_damage) * 0.3
        return max(-1.0, min(1.0, base_eval + delta))

    # 2. Player move action
    player_move = battle.active_pokemon.moves.get(player_action_target)
    if not player_move:
        return base_eval

    player_dmg = estimate_damage_fraction(
        player_move,
        battle.active_pokemon,
        battle.opponent_active_pokemon,
        is_tera=player_tera,
    )

    # Opponent response
    opp_move = battle.opponent_active_pokemon.moves.get(opp_action_target) if battle.opponent_active_pokemon else None
    if opp_move:
        opp_dmg = estimate_damage_fraction(
            opp_move,
            battle.opponent_active_pokemon,
            battle.active_pokemon,
            is_tera=False,
        )
    else:
        opp_dmg = 0.25  # Approximate response damage

    # Speed check
    player_spe = battle.active_pokemon.stats.get("spe", 250) or 250
    opp_spe = battle.opponent_active_pokemon.stats.get("spe", 250) or 250

    if player_spe >= opp_spe:
        # Player moves first: if KO, opp does 0 damage
        if player_dmg >= battle.opponent_active_pokemon.current_hp_fraction:
            delta = 0.5  # Major advantage (KO scored)
        else:
            delta = (player_dmg - opp_dmg) * 0.4
    else:
        # Opponent moves first
        if opp_dmg >= battle.active_pokemon.current_hp_fraction:
            delta = -0.5  # KO suffered
        else:
            delta = (player_dmg - opp_dmg) * 0.4

    return max(-1.0, min(1.0, base_eval + delta))
