"""Opponent action sampling and behavior modeling for Minimax lookahead search."""

from __future__ import annotations

from typing import List, Tuple
from poke_env.battle import Battle
from rotomarena.search.heuristics import get_type_effectiveness


def sample_opponent_actions(
    battle: Battle,
    top_k: int = 3,
) -> List[Tuple[str, str, float]]:
    """
    Samples candidate actions for the opponent during lookahead tree search.
    
    Returns:
        List of tuples: (action_type, action_target, prior_probability)
        where action_type is 'MOVE' or 'SWITCH'.
    """
    candidates: List[Tuple[str, str, float]] = []

    opp_active = battle.opponent_active_pokemon
    if not opp_active:
        return [("MOVE", "default", 1.0)]

    # 1. Known opponent moves
    if opp_active.moves:
        for m_id, move in opp_active.moves.items():
            eff = 1.0
            if move.type and battle.active_pokemon:
                player_types = [t.name for t in battle.active_pokemon.types if t]
                eff = get_type_effectiveness(move.type.name, player_types)
            weight = (move.base_power or 50.0) * eff
            candidates.append(("MOVE", m_id, weight))
    else:
        # Generate representative offensive options based on opponent types
        for t in opp_active.types:
            if t:
                candidates.append(("MOVE", f"attack_{t.name.lower()}", 80.0))
        if not candidates:
            candidates.append(("MOVE", "attack_neutral", 80.0))

    # 2. Candidate switches if active opponent is at disadvantage
    opp_types = [t.name for t in opp_active.types if t]
    player_active = battle.active_pokemon
    threatened = False
    if player_active:
        for m in player_active.moves.values():
            if m.type and get_type_effectiveness(m.type.name, opp_types) >= 2.0:
                threatened = True
                break

    if threatened:
        for mon in battle.opponent_team.values():
            if mon != opp_active and not mon.fainted:
                candidates.append(("SWITCH", mon.species, 40.0))

    # Sort by weight descending and normalize top_k
    candidates.sort(key=lambda x: x[2], reverse=True)
    selected = candidates[:top_k]
    total_w = sum(w for _, _, w in selected) or 1.0
    return [(act, tgt, w / total_w) for act, tgt, w in selected]
