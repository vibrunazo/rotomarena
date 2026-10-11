"""Fast battle forward simulator and damage estimation model for lookahead search."""

from __future__ import annotations

from typing import Dict, List, Optional
from poke_env.battle import Battle, Move, MoveCategory, Pokemon, SideCondition, Status
from rotomarena.search.heuristics import evaluate_battle_state, get_type_effectiveness


DEFAULT_SWITCH_COST = 0.1  # sweep vs MaxDamage, 40 games per value: 0 -> 43% wins, 0.1 -> 66% (best for both bots)


def _level(mon: Pokemon) -> int:
    return getattr(mon, "level", None) or 100


def _estimate_stat(mon: Pokemon, key: str) -> float:
    """The stat at the Pokémon's own level (50 in Champions, 100 in Gen 9 OU) from its base stats, assuming 31 IVs,
    84 EVs (about 10 of Champions' Stat Points) and a neutral nature. Estimating at level 100 against our own
    level-50 stats made every opponent look twice as fast and strong in Champions: each move scored the same, a
    knockout taken first, and the bot switched turn after turn (1 win in 40 against the max-damage and random bots)."""
    base = (mon.base_stats or {}).get(key, 80)
    core = (2 * base + 31 + 21) * _level(mon) // 100
    return core + _level(mon) + 10 if key == "hp" else core + 5


def _stat(mon: Pokemon, key: str) -> float:
    """The real stat when known (our own Pokémon), else an estimate (opponents)."""
    value = (mon.stats or {}).get(key)
    return float(value) if value else _estimate_stat(mon, key)


def _max_hp(mon: Pokemon) -> float:
    """poke-env reports opposing HP as a percentage (max_hp == 100); only our own Pokémon have real HP."""
    if (mon.stats or {}).get("atk"):
        return float(mon.max_hp or _estimate_stat(mon, "hp"))
    return _estimate_stat(mon, "hp")


# Abilities that make a Pokémon immune to a type. PokéChamp kept using Earthquake on a Levitate Rotom-Wash, turn
# after turn: the type chart alone says Ground hits Electric hard.
_ABILITY_IMMUNITIES = {
    "levitate": "GROUND", "eartheater": "GROUND", "flashfire": "FIRE", "wellbakedbody": "FIRE",
    "waterabsorb": "WATER", "stormdrain": "WATER", "dryskin": "WATER", "voltabsorb": "ELECTRIC",
    "lightningrod": "ELECTRIC", "motordrive": "ELECTRIC", "sapsipper": "GRASS",
}


def _immune_by_ability(defender: Pokemon, move_type: str) -> bool:
    """Its ability (once revealed, or when every ability it could have does) makes it immune to this type."""
    known = getattr(defender, "ability", None)
    abilities = [known] if known else list(getattr(defender, "possible_abilities", None) or [])
    ids = ["".join(c for c in str(a).lower() if c.isalnum()) for a in abilities]
    return bool(ids) and all(_ABILITY_IMMUNITIES.get(a) == move_type for a in ids)


def _type_names(mon: Pokemon) -> List[str]:
    return [t.name.upper() for t in mon.types if t]


def _boosted(stat: float, stage: int) -> float:
    return stat * max(2, 2 + stage) / max(2, 2 - stage)


def _damage_fraction(
    power: float,
    move_type: str,
    physical: bool,
    attacker: Pokemon,
    defender: Pokemon,
    is_tera: bool = False,
) -> float:
    """Fraction of the defender's max HP a hit of this power and type deals (level-100 damage formula)."""
    type_mult = get_type_effectiveness(move_type, _type_names(defender))
    if type_mult == 0.0 or _immune_by_ability(defender, move_type):
        return 0.0

    stab = 1.0
    if is_tera and attacker.tera_type and attacker.tera_type.name.upper() == move_type:
        stab = 2.0
    elif move_type in _type_names(attacker):
        stab = 1.5

    atk_key, def_key = ("atk", "def") if physical else ("spa", "spd")
    atk_stat = _boosted(_stat(attacker, atk_key), attacker.boosts.get(atk_key, 0))
    def_stat = _boosted(_stat(defender, def_key), defender.boosts.get(def_key, 0))
    if physical and attacker.status == Status.BRN and attacker.ability != "guts":
        atk_stat *= 0.5

    level_factor = 2 * _level(attacker) / 5 + 2  # 42 at level 100, 22 at level 50
    raw_damage = (level_factor * power * (atk_stat / max(1.0, def_stat))) / 50.0 + 2.0
    return min(1.0, max(0.0, raw_damage * stab * type_mult / _max_hp(defender)))


def estimate_damage_fraction(
    move: Move,
    attacker: Pokemon,
    defender: Pokemon,
    is_tera: bool = False,
) -> float:
    """Estimates the fraction of defender max HP that the given move will inflict."""
    if not move or move.category == MoveCategory.STATUS or move.base_power <= 0:
        return 0.0
    move_type = move.type.name.upper() if move.type else "NORMAL"
    return _damage_fraction(
        move.base_power, move_type, move.category == MoveCategory.PHYSICAL, attacker, defender, is_tera
    )


def estimate_typed_attack(attack_type: str, attacker: Pokemon, defender: Pokemon) -> float:
    """An unrevealed 80 BP attack of the given type, physical or special by the attacker's better stat."""
    physical = _stat(attacker, "atk") >= _stat(attacker, "spa")
    return _damage_fraction(80, attack_type.upper(), physical, attacker, defender)


def estimate_best_hit(attacker: Pokemon, defender: Pokemon) -> float:
    """The attacker's strongest hit: its known damaging moves, else an 80 BP attack of each of its types."""
    known = [estimate_damage_fraction(m, attacker, defender) for m in attacker.moves.values()]
    if any(known):
        return max(known)
    return max((estimate_typed_attack(t, attacker, defender) for t in _type_names(attacker)), default=0.0)


def entry_hazard_damage(battle: Battle, switch_in: Pokemon) -> float:
    """HP fraction lost to Stealth Rock and Spikes on our side when this Pokémon switches in."""
    damage = 0.0
    if SideCondition.STEALTH_ROCK in battle.side_conditions:
        damage += 0.125 * get_type_effectiveness("ROCK", _type_names(switch_in))
    layers = battle.side_conditions.get(SideCondition.SPIKES, 0)
    if layers and "FLYING" not in _type_names(switch_in):
        damage += {1: 1 / 8, 2: 1 / 6}.get(layers, 1 / 4)
    return damage


def _opponent_attack(battle: Battle, opp_action_type: str, opp_action_target: str, target: Pokemon) -> float:
    """Damage the opponent's sampled action deals to `target` (0 when the opponent switches)."""
    opp = battle.opponent_active_pokemon
    if opp_action_type == "SWITCH":
        return 0.0
    known_move = opp.moves.get(opp_action_target)
    if known_move:
        return estimate_damage_fraction(known_move, opp, target)
    if opp_action_target.startswith("attack_") and opp_action_target != "attack_neutral":
        return estimate_typed_attack(opp_action_target[len("attack_"):], opp, target)
    return estimate_best_hit(opp, target)


def simulate_turn_outcome(
    battle: Battle,
    player_action_type: str,  # 'MOVE' or 'SWITCH'
    player_action_target: str,  # move_id or species
    player_tera: bool,
    opp_action_type: str,
    opp_action_target: str,
    weights: Optional[Dict[str, float]] = None,
    just_switched: bool = False,
) -> float:
    """
    Simulates a 1-turn transition between player action and opponent action,
    returning the estimated resulting state score. `just_switched`: our active Pokémon came in by our own switch
    last turn, so switching it straight back out costs more (the ping-pong brake).
    """
    base_eval = evaluate_battle_state(battle, weights)
    active = battle.active_pokemon
    opp = battle.opponent_active_pokemon
    if not active or not opp:
        return base_eval

    # 1. Player switch: the switch-in takes the opponent's hit and hazards, then threatens next turn.
    if player_action_type == "SWITCH":
        switch_in = next((m for m in battle.available_switches if m.species == player_action_target), None)
        if switch_in is None:
            return base_eval
        incoming = _opponent_attack(battle, opp_action_type, opp_action_target, switch_in)
        hazards = entry_hazard_damage(battle, switch_in)
        threat_next_turn = estimate_best_hit(switch_in, opp)
        # switch_cost: the tempo a switch gives away; without it the bots switched on half their turns
        switch_cost = (weights or {}).get("switch_cost", DEFAULT_SWITCH_COST)
        # Two turns, not one: a switch-in that won't survive this hit, or then can't stand against the opponent
        # (survive its best hit next turn, or outspeed it and threaten a knockout), only delays the loss. Scored like
        # one, it no longer beats staying in: switching Steelix and Blastoise back and forth into Rotom-Wash's Hydro
        # Pump, six turns running, each time "saving" the Pokémon about to faint.
        hp_after = switch_in.current_hp_fraction - incoming - hazards
        outspeeds = _stat(switch_in, "spe") > _stat(opp, "spe")
        holds = hp_after > 0 and (estimate_best_hit(opp, switch_in) < hp_after
                                  or (outspeeds and threat_next_turn >= opp.current_hp_fraction))
        if holds:
            delta = 0.4 * (0.5 * threat_next_turn - incoming - hazards) - switch_cost
            if _opponent_attack(battle, opp_action_type, opp_action_target, active) >= active.current_hp_fraction:
                delta += 0.2  # staying in would have cost the active Pokémon
        else:
            delta = -0.5 - switch_cost
        if just_switched:
            delta -= switch_cost
        return max(-1.0, min(1.0, base_eval + delta))

    # 2. Player move
    player_move = active.moves.get(player_action_target)
    if not player_move:
        return base_eval

    player_dmg = estimate_damage_fraction(player_move, active, opp, is_tera=player_tera)
    if opp_action_type == "SWITCH":
        player_dmg *= 0.5  # the hit lands on a switch-in, likely one that resists it
    opp_dmg = _opponent_attack(battle, opp_action_type, opp_action_target, active)

    opp_move = opp.moves.get(opp_action_target) if opp_action_type == "MOVE" else None
    priority = (player_move.priority or 0) - ((opp_move.priority or 0) if opp_move else 0)
    if priority > 0 or (priority == 0 and _stat(active, "spe") >= _stat(opp, "spe")):  # priority, then speed
        # Player moves first: a KO means the opponent never attacks
        if opp_action_type != "SWITCH" and player_dmg >= opp.current_hp_fraction:
            delta = 0.5
        else:
            delta = (player_dmg - opp_dmg) * 0.4
    else:
        if opp_dmg >= active.current_hp_fraction:
            delta = -0.5  # KO suffered before moving
        else:
            delta = (player_dmg - opp_dmg) * 0.4

    return max(-1.0, min(1.0, base_eval + delta))
