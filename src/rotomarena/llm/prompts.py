"""Prompt engineering templates and battle state formatters for Gen 9 OU battles."""

from __future__ import annotations

from typing import Any, List, Optional
from poke_env.battle import Battle, Pokemon


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


def _condition_names(conditions: Any) -> str:
    """Weather / terrain dicts ({Weather.RAINDANCE: 3}) as readable names."""
    if not conditions:
        return "None"
    return ", ".join(c.name.replace("_", " ").title() for c in conditions)


def _event_actor(ident: str, role: Optional[str]) -> str:
    """'p2a: Heatran' -> 'Opposing Heatran' (or 'Your Heatran' on our side)."""
    side, _, name = ident.partition(": ")
    mine = role is not None and side.startswith(role)
    return f"{'Your' if mine else 'Opposing'} {name or side}"


def _format_event(msg: List[str], role: Optional[str]) -> Optional[str]:
    """One protocol message (['', 'move', 'p1a: Great Tusk', 'Earthquake', ...]) as a short sentence."""
    if len(msg) < 2:
        return None
    kind, args = msg[1], msg[2:]
    who = _event_actor(args[0], role) if args else ""
    source = next((a for a in args[1:] if a.startswith("[from]")), "")
    source = f" {source}" if source else ""
    if kind == "move" and len(args) >= 2:
        return f"{who} used {args[1]}"
    if kind in ("switch", "drag") and len(args) >= 2:
        side = who.split(" ")[0]
        return f"{side} {args[1].split(',')[0]} came in"
    if kind == "faint":
        return f"{who} fainted"
    if kind in ("-damage", "-heal") and len(args) >= 2:
        verb = "is at" if kind == "-damage" else "healed to"
        return f"{who} {verb} {args[1]} HP{source}"
    simple = {
        "-supereffective": "It was super effective",
        "-resisted": "It was not very effective",
        "-crit": "A critical hit",
    }
    if kind in simple:
        return simple[kind]
    if kind == "-immune":
        return f"{who} was immune"
    if kind == "-miss":
        return f"{who} missed"
    if kind == "-status" and len(args) >= 2:
        return f"{who} got status {args[1]}"
    if kind in ("-boost", "-unboost") and len(args) >= 3:
        sign = "+" if kind == "-boost" else "-"
        return f"{who}: {args[1]} {sign}{args[2]}"
    if kind == "-terastallize" and len(args) >= 2:
        return f"{who} terastallized into {args[1]}"
    if kind in ("-sidestart", "-sideend") and len(args) >= 2:
        verb = "set on" if kind == "-sidestart" else "removed from"
        side = "your" if role and args[0].startswith(role) else "the opposing"
        return f"{args[1].replace('move: ', '')} {verb} {side} side"
    if kind in ("-item", "-enditem") and len(args) >= 2:
        return f"{who}'s item: {args[1]}{source}"
    if kind == "-ability" and len(args) >= 2:
        return f"{who}'s ability: {args[1]}"
    if kind == "-weather" and args:
        return f"Weather: {args[0]}"
    if kind == "-fieldstart" and args:
        return f"Field: {args[0].replace('move: ', '')}"
    return None


def format_recent_events(battle: Battle, max_lines: int = 16) -> List[str]:
    """What happened since the start of the previous turn, read from the battle's protocol log."""
    data = getattr(battle, "_replay_data", None) or []
    turn_marks = [i for i, m in enumerate(data) if len(m) > 2 and m[1] == "turn"]
    start = turn_marks[-2] + 1 if len(turn_marks) >= 2 else 0
    role = getattr(battle, "player_role", None)
    lines = [line for line in (_format_event(m, role) for m in data[start:]) if line]
    return lines[-max_lines:]


def format_battle_state(battle: Battle) -> str:
    """Serializes the current poke-env Battle state into a structured context string."""
    lines = [
        f"### Turn {battle.turn} | Format: {battle.format} | Weather: {_condition_names(battle.weather)}"
        f" | Field: {_condition_names(battle.fields)}",
    ]

    events = format_recent_events(battle)
    if events:
        lines.append("\n#### LAST TURN:")
        lines.extend(f"- {e}" for e in events)

    lines.append("\n#### YOUR TEAM:")
    lines.append(f"Active Pokémon:\n{format_pokemon_summary(battle.active_pokemon, is_active=True, is_opponent=False)}")

    bench = [mon for mon in battle.team.values() if mon != battle.active_pokemon]
    lines.append("\nBench Pokémon:")
    if bench:
        for mon in bench:
            lines.append(format_pokemon_summary(mon, is_active=False, is_opponent=False))
    else:
        lines.append("- (No bench Pokémon remaining)")

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

    seen = {mon.species for mon in battle.opponent_team.values()}
    preview = [mon.species for mon in getattr(battle, "teampreview_opponent_team", None) or []]
    unseen = [s for s in preview if s not in seen]
    if unseen:
        lines.append(f"Not yet seen in battle (from team preview): {', '.join(unseen)}")

    opp_side_conds = [k.name.title() for k in battle.opponent_side_conditions.keys()]
    lines.append(f"\nOpponent Side Hazards / Conditions: {', '.join(opp_side_conds) if opp_side_conds else 'None'}")
    lines.append(f"Opponent Terastallized: {'Yes' if getattr(battle, 'opponent_used_tera', False) else 'No'}")

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

    for i, act in enumerate(legal_actions, 1):
        lines.append(f"{i}. {act}")

    return "\n".join(lines)


SYSTEM_PROMPT_DIRECT_COT = """You are an expert competitive Pokémon player and Gen 9 OU tournament grandmaster.
Analyze the battle state and choose the single best action for this turn.

RULES:
1. Keep your <thought> under 200 words. Focus on the decisive factor (speed tier, knockout threshold, or switch need).
2. Your <decision> block must contain exactly one action line, copied from LEGAL ACTIONS without its number:
   MOVE: <move_id>   or   MOVE: <move_id> [TERA]   or   SWITCH: <species>
3. If your action is not in LEGAL ACTIONS, or your answer is cut off, the first legal move is played for you.

Output format:
<thought>
Your concise reasoning.
</thought>
<decision>
MOVE: move_id
</decision>
"""


USER_PROMPT_DIRECT_COT_TEMPLATE = """Here is the current battle state:

{battle_state}

Choose exactly one action from LEGAL ACTIONS."""
