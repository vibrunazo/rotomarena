"""Prompt engineering templates and battle state formatters for Gen 9 OU battles."""

from __future__ import annotations

from typing import Any, List, Optional
from poke_env.battle import Battle, Pokemon, Move


def format_pokemon_summary(mon: Optional[Pokemon], is_active: bool = False, is_opponent: bool = False) -> str:
    """Format a single Pokemon state for prompt injection with full competitive details."""
    if mon is None:
        return "None"

    status_str = f" [{mon.status.name}]" if mon.status else ""
    if mon.fainted:
        status_str = " [FAINTED]"

    hp_pct = round(mon.current_hp_fraction * 100, 1)
    hp_info = f"{hp_pct}% HP"
    if not is_opponent and mon.current_hp is not None and mon.max_hp is not None:
        hp_info = f"{mon.current_hp}/{mon.max_hp} ({hp_pct}%)"

    types_str = "/".join([t.name.title() for t in mon.types if t])
    tera_type_str = mon.tera_type.name.title() if mon.tera_type else None
    is_terad = getattr(mon, "_terastallized", False) or getattr(mon, "is_terastallized", False)

    tera_str = ""
    if is_terad and tera_type_str:
        tera_str = f" [TERASTALLIZED: {tera_type_str}]"
    elif tera_type_str:
        tera_str = f" (Tera Type: {tera_type_str})"

    info = f"- **{mon.species}** ({types_str}){status_str}: {hp_info}{tera_str}"

    if not is_opponent:
        # YOUR TEAM: Include Item, Ability, Stats, and Moves for ALL Pokémon (active and bench)
        details = []
        if mon.item:
            details.append(f"Item: {mon.item}")
        else:
            details.append("Item: None")

        if mon.ability:
            details.append(f"Ability: {mon.ability}")

        if mon.stats:
            stat_strs = [f"{k.upper()}: {v}" for k, v in mon.stats.items() if v is not None]
            if stat_strs:
                details.append(f"Stats: [{', '.join(stat_strs)}]")

        if is_active:
            boosts = [f"{k.upper()}: {v:+d}" for k, v in mon.boosts.items() if v != 0]
            if boosts:
                details.append(f"Boosts: [{', '.join(boosts)}]")

        if details:
            info += f"\n  {' | '.join(details)}"

        # Moves with PP, Category, Type, Power, Accuracy
        if mon.moves:
            move_strs = []
            for m in mon.moves.values():
                cat = m.category.name.title() if m.category else "Status"
                m_type = m.type.name.title() if m.type else "Normal"
                bp = m.base_power if m.base_power > 0 else "-"
                move_strs.append(f"{m.id} ({m_type}/{cat}, BP:{bp}, PP:{m.current_pp}/{m.max_pp})")
            info += f"\n  Moves: {', '.join(move_strs)}"

    else:
        # OPPONENT TEAM: Include revealed Item, Ability, Base Stats, Boosts, and Revealed Moves
        details = []
        if mon.item:
            details.append(f"Item: {mon.item}")
        else:
            details.append("Item: Unknown")

        if mon.ability:
            details.append(f"Ability: {mon.ability}")
        else:
            details.append("Ability: Unknown")

        if mon.base_stats:
            b_stats = [f"{k.upper()}: {v}" for k, v in mon.base_stats.items() if v is not None]
            if b_stats:
                details.append(f"Base Stats: [{', '.join(b_stats)}]")

        if is_active:
            boosts = [f"{k.upper()}: {v:+d}" for k, v in mon.boosts.items() if v != 0]
            if boosts:
                details.append(f"Boosts: [{', '.join(boosts)}]")

        if details:
            info += f"\n  {' | '.join(details)}"

        if mon.moves:
            move_strs = []
            for m in mon.moves.values():
                cat = m.category.name.title() if m.category else "Status"
                m_type = m.type.name.title() if m.type else "Normal"
                bp = m.base_power if m.base_power > 0 else "-"
                move_strs.append(f"{m.id} ({m_type}/{cat}, BP:{bp})")
            info += f"\n  Revealed Moves: {', '.join(move_strs)}"
        else:
            info += f"\n  Revealed Moves: None yet"

    return info


def format_battle_state(battle: Battle) -> str:
    """Serializes the current poke-env Battle state into a structured context string."""
    lines = [
        f"### Turn {battle.turn} | Format: {battle.format} | Weather: {battle.weather or 'None'} | Terrain: {battle.fields or 'None'}",
        "",
        "#### YOUR TEAM:",
    ]

    # Active
    lines.append(f"Active Pokémon:\n{format_pokemon_summary(battle.active_pokemon, is_active=True, is_opponent=False)}")
    
    # Bench
    bench = [mon for mon in battle.team.values() if mon != battle.active_pokemon]
    lines.append("\nBench Pokémon:")
    if bench:
        for mon in bench:
            lines.append(format_pokemon_summary(mon, is_active=False, is_opponent=False))
    else:
        lines.append("- (No bench Pokémon remaining)")

    # Side conditions / Hazards
    side_conds = [k.name.title() for k in battle.side_conditions.keys()]
    lines.append(f"\nYour Side Hazards / Conditions: {', '.join(side_conds) if side_conds else 'None'}")
    lines.append(f"Terastallization Available: {'Yes' if battle.can_tera else 'No'}")

    lines.append("\n#### OPPONENT TEAM:")
    lines.append(f"Active Pokémon:\n{format_pokemon_summary(battle.opponent_active_pokemon, is_active=True, is_opponent=True)}")

    opp_bench = [mon for mon in battle.opponent_team.values() if mon != battle.opponent_active_pokemon]
    lines.append("\nRevealed Opponent Bench:")
    if opp_bench:
        for mon in opp_bench:
            lines.append(format_pokemon_summary(mon, is_active=False, is_opponent=True))
    else:
        lines.append("- (No other Pokémon revealed yet)")

    opp_side_conds = [k.name.title() for k in battle.opponent_side_conditions.keys()]
    lines.append(f"\nOpponent Side Hazards / Conditions: {', '.join(opp_side_conds) if opp_side_conds else 'None'}")
    lines.append(f"Opponent Terastallized: {'Yes' if getattr(battle, 'opponent_used_tera', False) else 'No'}")

    # Available moves and switches
    lines.append("\n#### LEGAL ACTIONS THIS TURN:")
    legal_actions = []
    
    if battle.available_moves:
        for m in battle.available_moves:
            m_type = m.type.name.title() if m.type else "Normal"
            legal_actions.append(f"MOVE: {m.id} (Type: {m_type}, BP: {m.base_power or '-'}, Acc: {m.accuracy or '-'})")
            if battle.can_tera:
                legal_actions.append(f"MOVE: {m.id} [TERA]")

    if battle.available_switches:
        for s in battle.available_switches:
            s_hp = round(s.current_hp_fraction * 100, 1)
            legal_actions.append(f"SWITCH: {s.species} ({s_hp}% HP)")

    if not legal_actions:
        legal_actions.append("MOVE: default")

    for i, act in enumerate(legal_actions, 1):
        lines.append(f"{i}. {act}")

    return "\n".join(lines)


SYSTEM_PROMPT_DIRECT_COT = """You are an expert competitive Pokémon player and Gen 9 OU tournament grandmaster.
Your goal is to analyze the battle state quickly and choose the single best strategic action for the current turn.

CRITICAL TOURNAMENT RULES:
1. Keep your <thought> analysis strictly under 200 words total.
2. Focus only on the single decisive tactical factor (speed tier, knockout threshold, or switch need).
3. Do not write lengthy paragraphs or list every Pokémon. Get straight to the point.

Output your response strictly following this format:
<thought>
Concise tactical reasoning under 200 words.
</thought>
<decision>
ACTION: <MOVE: move_id | MOVE: move_id [TERA] | SWITCH: pokemon_species>
</decision>
"""


USER_PROMPT_DIRECT_COT_TEMPLATE = """Here is the current battle state:

{battle_state}

Select the optimal action from the LEGAL ACTIONS list.
Remember: Keep your <thought> strictly under 200 words total. Including thought is mandatory. Your <decision> tag must contain exactly one valid action."""


SYSTEM_PROMPT_VALUE_EVALUATION = """You are an evaluation engine for competitive Pokémon battles.
Assess the given Gen 9 OU game position from the perspective of Player 1.
Score the position from -1.0 (certain defeat) to +1.0 (certain victory), with 0.0 being completely even.

Keep your explanation small (under 150 words).

Output your evaluation in strict JSON format:
{
  "score": float (-1.0 to 1.0),
  "win_probability": float (0.0 to 1.0),
  "explanation": "small reasoning under 150 words"
}"""


SYSTEM_PROMPT_OPPONENT_PREDICTION = """You are a predictive opponent modeling engine for competitive Pokémon battles.
Analyze the current turn state and predict the opponent's most probable action.

Keep your rationale small (under 150 words).

Output your prediction in strict JSON format:
{
  "predicted_action": "move_id or switch_species",
  "probability": float (0.0 to 1.0),
  "rationale": "small reasoning under 150 words"
}"""
