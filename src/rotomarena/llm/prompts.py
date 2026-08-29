"""Prompt engineering templates and battle state formatters for Gen 9 OU battles."""

from __future__ import annotations

from typing import Any, List, Optional
from poke_env.battle import Battle, Pokemon, Move


def format_pokemon_summary(mon: Optional[Pokemon], is_active: bool = False, is_opponent: bool = False) -> str:
    """Format a single Pokemon state for prompt injection."""
    if mon is None:
        return "None"

    status_str = f" [{mon.status.name}]" if mon.status else ""
    hp_pct = round(mon.current_hp_fraction * 100, 1)
    types_str = "/".join([t.name.title() for t in mon.types if t])
    tera_str = f" (Tera: {mon.tera_type.name.title()})" if mon.tera_type else ""

    info = f"- **{mon.species}** ({types_str}){status_str}: {hp_pct}% HP{tera_str}"

    if is_active:
        # Boosts
        boosts = [f"{k.upper()}: {v:+d}" for k, v in mon.boosts.items() if v != 0]
        if boosts:
            info += f" | Boosts: [{', '.join(boosts)}]"
        if mon.item and not is_opponent:
            info += f" | Item: {mon.item}"
        if mon.ability and not is_opponent:
            info += f" | Ability: {mon.ability}"

        # Moves
        if mon.moves:
            move_strs = []
            for m in mon.moves.values():
                cat = m.category.name.title() if m.category else "Unknown"
                m_type = m.type.name.title() if m.type else "Normal"
                bp = m.base_power if m.base_power > 0 else "-"
                move_strs.append(f"{m.id} ({m_type}/{cat}, BP:{bp}, PP:{m.current_pp}/{m.max_pp})")
            info += f"\n  Moves: {', '.join(move_strs)}"

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
Your goal is to analyze the battle state carefully and choose the single best strategic action for the current turn.

When evaluating the turn:
1. Speed & Priority: Determine who moves first and if priority moves (e.g., Extreme Speed, Sucker Punch, Grassy Glide) threaten a knockout.
2. Type Effectiveness & Damage: Calculate potential damage output and defensive resistances.
3. Win Conditions: Protect your setup sweepers, preserve your defensive walls, and position for end-game advantages.
4. Opponent Prediction: Anticipate whether the opponent will attack, setup, switch to a counter, or Terastallize.
5. Risk vs Reward: Avoid high-risk plays if you have momentum, or take calculated risks if behind.

Output your response strictly following this format:
<thought>
Step-by-step tactical Chain-of-Thought analysis.
</thought>
<decision>
ACTION: <MOVE: move_id | MOVE: move_id [TERA] | SWITCH: pokemon_species>
</decision>
"""


USER_PROMPT_DIRECT_COT_TEMPLATE = """Here is the current battle state:

{battle_state}

Analyze the situation and select the optimal move or switch from the LEGAL ACTIONS list.
Make sure your <decision> tag contains exactly one valid action matching the legal options list."""


SYSTEM_PROMPT_VALUE_EVALUATION = """You are an evaluation engine for competitive Pokémon battles.
Assess the given Gen 9 OU game position from the perspective of Player 1.
Score the position from -1.0 (certain defeat) to +1.0 (certain victory), with 0.0 being completely even.

Consider:
- Number of alive Pokémon on each team
- Total remaining HP percentage across the teams
- Active matchup advantage / speed tiers
- Entry hazards and field conditions
- Status conditions (toxic/burn/paralysis)
- Unused Terastallization

Output your evaluation in strict JSON format:
{
  "score": float (-1.0 to 1.0),
  "win_probability": float (0.0 to 1.0),
  "explanation": "concise reasoning"
}"""


SYSTEM_PROMPT_OPPONENT_PREDICTION = """You are a predictive opponent modeling engine for competitive Pokémon battles.
Analyze the current turn state and predict the opponent's most probable action.

Output your prediction in strict JSON format:
{
  "predicted_action": "move_id or switch_species",
  "probability": float (0.0 to 1.0),
  "rationale": "concise reasoning"
}"""
