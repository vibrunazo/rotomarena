"""Gen 9 OU Type Chart, Heuristic Evaluation Function, and Positional Scoring."""

from __future__ import annotations

import math
from typing import Dict, List, Optional
from poke_env.battle import Battle, SideCondition, Status


# Gen 9 Type Effectiveness Chart: TYPE_CHART[attacker_type][defender_type] -> float
TYPE_CHART: Dict[str, Dict[str, float]] = {
    "NORMAL": {
        "ROCK": 0.5, "GHOST": 0.0, "STEEL": 0.5
    },
    "FIRE": {
        "FIRE": 0.5, "WATER": 0.5, "GRASS": 2.0, "ICE": 2.0, "BUG": 2.0,
        "ROCK": 0.5, "DRAGON": 0.5, "STEEL": 2.0
    },
    "WATER": {
        "FIRE": 2.0, "WATER": 0.5, "GRASS": 0.5, "GROUND": 2.0, "ROCK": 2.0, "DRAGON": 0.5
    },
    "GRASS": {
        "FIRE": 0.5, "WATER": 2.0, "GRASS": 0.5, "POISON": 0.5, "GROUND": 2.0,
        "FLYING": 0.5, "BUG": 0.5, "ROCK": 2.0, "DRAGON": 0.5, "STEEL": 0.5
    },
    "ELECTRIC": {
        "WATER": 2.0, "GRASS": 0.5, "ELECTRIC": 0.5, "GROUND": 0.0, "FLYING": 2.0, "DRAGON": 0.5
    },
    "ICE": {
        "FIRE": 0.5, "WATER": 0.5, "GRASS": 2.0, "ICE": 0.5, "GROUND": 2.0,
        "FLYING": 2.0, "DRAGON": 2.0, "STEEL": 0.5
    },
    "FIGHTING": {
        "NORMAL": 2.0, "ICE": 2.0, "POISON": 0.5, "FLYING": 0.5, "PSYCHIC": 0.5,
        "BUG": 0.5, "ROCK": 2.0, "GHOST": 0.0, "DARK": 2.0, "STEEL": 2.0, "FAIRY": 0.5
    },
    "POISON": {
        "GRASS": 2.0, "POISON": 0.5, "GROUND": 0.5, "ROCK": 0.5, "GHOST": 0.5,
        "STEEL": 0.0, "FAIRY": 2.0
    },
    "GROUND": {
        "FIRE": 2.0, "GRASS": 0.5, "ELECTRIC": 2.0, "POISON": 2.0, "FLYING": 0.0,
        "BUG": 0.5, "ROCK": 2.0, "STEEL": 2.0
    },
    "FLYING": {
        "GRASS": 2.0, "ELECTRIC": 0.5, "FIGHTING": 2.0, "BUG": 2.0, "ROCK": 0.5, "STEEL": 0.5
    },
    "PSYCHIC": {
        "FIGHTING": 2.0, "POISON": 2.0, "PSYCHIC": 0.5, "DARK": 0.0, "STEEL": 0.5
    },
    "BUG": {
        "FIRE": 0.5, "GRASS": 2.0, "FIGHTING": 0.5, "POISON": 0.5, "FLYING": 0.5,
        "PSYCHIC": 2.0, "GHOST": 0.5, "DARK": 2.0, "STEEL": 0.5, "FAIRY": 0.5
    },
    "ROCK": {
        "FIRE": 2.0, "ICE": 2.0, "FIGHTING": 0.5, "GROUND": 0.5, "FLYING": 2.0,
        "BUG": 2.0, "STEEL": 0.5
    },
    "GHOST": {
        "NORMAL": 0.0, "PSYCHIC": 2.0, "GHOST": 2.0, "DARK": 0.5
    },
    "DRAGON": {
        "DRAGON": 2.0, "STEEL": 0.5, "FAIRY": 0.0
    },
    "STEEL": {
        "FIRE": 0.5, "WATER": 0.5, "ELECTRIC": 0.5, "ICE": 2.0, "ROCK": 2.0,
        "STEEL": 0.5, "FAIRY": 2.0
    },
    "DARK": {
        "FIGHTING": 0.5, "PSYCHIC": 2.0, "GHOST": 2.0, "DARK": 0.5, "FAIRY": 0.5
    },
    "FAIRY": {
        "FIRE": 0.5, "FIGHTING": 2.0, "POISON": 0.5, "DRAGON": 2.0, "DARK": 2.0, "STEEL": 0.5
    },
    "STELLAR": {}
}


def get_type_effectiveness(attack_type: str, defender_types: List[str]) -> float:
    """Calculate type effectiveness multiplier for a move against defending types."""
    if not attack_type:
        return 1.0
    
    atk = attack_type.upper()
    if atk == "STELLAR":
        return 1.2

    mult = 1.0
    for def_t in defender_types:
        if not def_t:
            continue
        d = def_t.upper()
        if atk in TYPE_CHART and d in TYPE_CHART[atk]:
            mult *= TYPE_CHART[atk][d]
    return mult


# Positive weights burden the side they are on (entry hazards); negative ones help it.
SIDE_CONDITION_WEIGHTS: Dict[SideCondition, float] = {
    SideCondition.STEALTH_ROCK: 1.0,
    SideCondition.SPIKES: 0.6,  # per layer
    SideCondition.TOXIC_SPIKES: 0.6,  # per layer
    SideCondition.STICKY_WEB: 0.6,
    SideCondition.REFLECT: -0.5,
    SideCondition.LIGHT_SCREEN: -0.5,
    SideCondition.AURORA_VEIL: -0.8,
    SideCondition.TAILWIND: -0.5,
}
_LAYERED = {SideCondition.SPIKES, SideCondition.TOXIC_SPIKES}


def side_condition_load(conditions: Dict[SideCondition, int]) -> float:
    """How much a side's conditions hurt it: hazards add, screens and Tailwind subtract."""
    return sum(
        SIDE_CONDITION_WEIGHTS.get(cond, 0.0) * (value if cond in _LAYERED else 1)
        for cond, value in conditions.items()
    )


STATUS_PENALTIES: Dict[Optional[Status], float] = {
    Status.TOX: 0.35,
    Status.SLP: 0.40,
    Status.FRZ: 0.45,
    Status.BRN: 0.25,
    Status.PAR: 0.25,
    Status.PSN: 0.15,
    None: 0.0,
}


def evaluate_battle_state(
    battle: Battle,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """
    Computes a normalized positional evaluation score in [-1.0, 1.0] from Player perspective.
    
    Factors considered:
    1. Alive Pokémon count difference
    2. Total team HP fraction sum
    3. Status conditions
    4. Active stat boosts (Atk, SpA, Spe)
    5. Side hazard differential
    6. Active matchup advantage
    7. Terastallization availability
    """
    w = {
        "alive_pokemon": 3.0,
        "hp_diff": 2.0,
        "status": 1.0,
        "boosts": 0.5,
        "hazards": 0.5,
        "matchup": 1.0,
        **(weights or {}),
    }

    # 1. Alive Pokémon count
    player_alive = sum(1 for mon in battle.team.values() if not mon.fainted)
    opp_alive = sum(1 for mon in battle.opponent_team.values() if not mon.fainted)
    # Opponent unrevealed count
    opp_unrevealed = max(0, 6 - len(battle.opponent_team))
    opp_total_alive = opp_alive + opp_unrevealed
    alive_score = (player_alive - opp_total_alive) / 6.0

    # 2. HP fraction difference
    player_hp_sum = sum(mon.current_hp_fraction for mon in battle.team.values())
    opp_hp_sum = sum(mon.current_hp_fraction for mon in battle.opponent_team.values()) + opp_unrevealed * 1.0
    hp_score = (player_hp_sum - opp_hp_sum) / 6.0

    # 3. Status penalty
    player_status_pen = sum(STATUS_PENALTIES.get(mon.status, 0.0) for mon in battle.team.values())
    opp_status_pen = sum(STATUS_PENALTIES.get(mon.status, 0.0) for mon in battle.opponent_team.values())
    status_score = (opp_status_pen - player_status_pen) / 6.0

    # 4. Boost stages on active Pokémon
    boost_score = 0.0
    if battle.active_pokemon:
        boost_score += sum(battle.active_pokemon.boosts.values()) * 0.1
    if battle.opponent_active_pokemon:
        boost_score -= sum(battle.opponent_active_pokemon.boosts.values()) * 0.1

    # 5. Hazards hurt the side they are on; screens and Tailwind help it
    hazard_score = 0.15 * (side_condition_load(battle.opponent_side_conditions) - side_condition_load(battle.side_conditions))

    # 6. Active matchup advantage
    matchup_score = 0.0
    if battle.active_pokemon and battle.opponent_active_pokemon:
        player_types = [t.name for t in battle.active_pokemon.types if t]
        opp_types = [t.name for t in battle.opponent_active_pokemon.types if t]

        # Check offensive effectiveness
        max_atk_eff = max(
            [
                get_type_effectiveness(m.type.name, opp_types)
                for m in battle.active_pokemon.moves.values()
                if m.type
            ]
            or [1.0]
        )
        if max_atk_eff >= 2.0:
            matchup_score += 0.2
        elif max_atk_eff <= 0.5:
            matchup_score -= 0.2

    # Weighted combination
    total_score = (
        w["alive_pokemon"] * alive_score
        + w["hp_diff"] * hp_score
        + w["status"] * status_score
        + w["boosts"] * boost_score
        + w["hazards"] * hazard_score
        + w["matchup"] * matchup_score
    )

    # Normalize roughly to [-1.0, 1.0] via hyperbolic tangent
    return math.tanh(total_score / 3.0)
