"""Prompt engineering templates and battle state formatters for Gen 9 OU battles."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional
from poke_env.battle import Battle, Move, Pokemon

# Showdown's tooltip texts (scripts/dump_dex_text.js), quoted by battle state 2
DEX_DIR = Path(__file__).resolve().parents[3] / "data" / "dex"
STATS = ["hp", "atk", "def", "spa", "spd", "spe"]
STAT_NAMES = {"hp": "HP", "atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}


def dex_mod(fmt: str) -> str:
    """The Showdown data mod a format plays: Champions has its own (moves it changed), the rest Gen 9's."""
    return "champions" if "champions" in fmt else "gen9"


@lru_cache(maxsize=4)
def _dex(mod: str) -> Dict[str, Any]:
    return json.loads((DEX_DIR / f"{mod}.json").read_text(encoding="utf-8"))


def _desc(kind: str, ident: Optional[str], fmt: str) -> str:
    """Showdown's one-line description of a move, ability or item ('' when unknown)."""
    key = "".join(c for c in (ident or "").lower() if c.isalnum())
    return (_dex(dex_mod(fmt))[kind].get(key) or {}).get("desc", "")


def stat_range(mon: Pokemon, stat: str) -> tuple:
    """(lowest, highest) the stat can be at the Pokemon's level: no investment and a hindering nature, up to full
    investment (252 EVs; Champions' 32 Stat Points give the same at level 50) and a boosting one. Showdown's tooltip
    shows the same range for an opposing Pokemon."""
    base, level = (mon.base_stats or {}).get(stat) or 0, mon.level or 100
    if stat == "hp":
        return (2 * base + 31) * level // 100 + level + 10, (2 * base + 31 + 63) * level // 100 + level + 10
    low = ((2 * base + 31) * level // 100 + 5) * 9 // 10
    high = ((2 * base + 31 + 63) * level // 100 + 5) * 11 // 10
    return low, high


def _boosted(value: float, stage: int) -> int:
    return int(value * ((2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)))


def speed_line(battle: Battle) -> str:
    """Who moves first: our active's speed against the opposing one's possible range, both after boosts and
    paralysis (and reversed under Trick Room). Priority moves go first regardless, as each move's line says."""
    mine, theirs = battle.active_pokemon, battle.opponent_active_pokemon
    if not mine or not theirs or mine.fainted or theirs.fainted or not mine.stats or not mine.stats.get("spe"):
        return ""  # nothing to race (a forced switch after a faint)

    def adjust(value: float, mon: Pokemon) -> int:
        value = _boosted(value, mon.boosts.get("spe", 0))
        return value // 2 if mon.status and mon.status.name == "PAR" else value

    me = adjust(mine.stats["spe"], mine)
    low, high = (adjust(v, theirs) for v in stat_range(theirs, "spe"))
    trick_room = any("trick" in f.name.lower() for f in (battle.fields or {}))
    if me > high:
        verdict = "you move first" if not trick_room else "it moves first (Trick Room)"
    elif me < low:
        verdict = "it moves first" if not trick_room else "you move first (Trick Room)"
    else:
        verdict = "either could move first, depending on its investment"
    return (f"Speed: your {mine.species} {me} vs opposing {theirs.species} {low}-{high} (possible range): {verdict}, "
            f"unless a move has priority.")


def _move_line(move: Move, battle: Battle, fmt: str) -> str:
    """A legal move as battle state 2 lists it: type, category, power, accuracy, priority, effectiveness on the
    opposing active Pokemon (as Showdown's move buttons show) and its tooltip line."""
    m_type = move.type.name.title() if move.type else "Normal"
    cat = move.category.name.title() if move.category else "Status"
    acc = "never misses" if move.accuracy is True else f"{round(move.accuracy * 100)}% accuracy"
    parts = [f"{m_type}, {cat}", f"power {move.base_power}" if move.base_power else "", acc]
    if move.priority:
        parts.append(f"priority {move.priority:+d}")
    target = battle.opponent_active_pokemon
    if target and cat != "Status" and move.type:
        mult = target.damage_multiplier(move)
        if mult != 1:
            parts.append({0: f"no effect on {target.species}", 0.25: f"1/4x on {target.species}",
                          0.5: f"not very effective on {target.species}", 2: f"super effective on {target.species}",
                          4: f"4x super effective on {target.species}"}.get(mult, f"{mult}x on {target.species}"))
    desc = _desc("moves", move.id, fmt)
    return f"MOVE: {move.id} | {', '.join(p for p in parts if p)}" + (f" | {desc}" if desc else "")


def _effects_line(mon: Pokemon, fmt: str, is_opponent: bool) -> str:
    """The active Pokemon's ability and item, with what they do (an opponent's when revealed, else its possible
    abilities, as Showdown's tooltip lists them)."""
    parts = []
    if mon.ability:
        parts.append(f"{mon.ability}: {_desc('abilities', mon.ability, fmt)}")
    elif is_opponent and mon.possible_abilities:
        parts.append("possible abilities: " + "; ".join(f"{a} ({_desc('abilities', a, fmt)})"
                                                         for a in mon.possible_abilities))
    if mon.item and mon.item != "unknown_item":
        parts.append(f"{mon.item}: {_desc('items', mon.item, fmt)}")
    return "  Effects: " + " | ".join(parts) if parts else ""


def format_pokemon_summary(mon: Optional[Pokemon], is_active: bool = False, is_opponent: bool = False,
                           state: int = 1, fmt: str = "gen9ou") -> str:
    """Format a single Pokemon state for prompt injection with full competitive details. Battle state 2 gives an
    opponent's stats as their possible range at its level (base stats alone invited comparing them with our real
    ones), the active Pokemon's ability and item effects, and no Tera type in Champions."""
    if mon is None:
        return "None"
    champions = state >= 2 and dex_mod(fmt) == "champions"

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
    if champions:
        pass  # no Terastallization in Champions
    elif is_terad and tera_type_str:
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

        if mon.base_stats and state >= 2:
            ranges = [f"{STAT_NAMES[k]} {'-'.join(map(str, stat_range(mon, k)))}" for k in STATS]
            details.append(f"Stats at level {mon.level} (possible range): [{', '.join(ranges)}]")
        elif mon.base_stats:
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

    if state >= 2 and is_active and not mon.fainted:
        effects = _effects_line(mon, fmt, is_opponent)
        if effects:
            info += f"\n{effects}"
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


def _format_event(msg: List[str], role: Optional[str], full: bool = False) -> Optional[str]:
    """One protocol message (['', 'move', 'p1a: Great Tusk', 'Earthquake', ...]) as a short sentence. `full`
    (ruleset.turn_events) adds the events that explain a turn: failed moves, lost turns, Protect and other
    activations, Mega Evolution, volatile conditions, and what caused a stat change."""
    if len(msg) < 2:
        return None
    kind, args = msg[1], msg[2:]
    who = _event_actor(args[0], role) if args else ""
    source = next((a for a in args[1:] if a.startswith("[from]")), "")
    source = f" {source}" if source else ""
    if full:
        line = _full_event(kind, args, who, source)
        if line is not None:
            return line or None  # "": a message the full events leave out (a faint's "0 fnt" damage line)
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


def _full_event(kind: str, args: List[str], who: str, source: str) -> Optional[str]:
    """The events only turn_events "full" reports (and boosts with their cause)."""
    def effect(text: str) -> str:
        return text.replace("move: ", "").replace("ability: ", "").replace("item: ", "")

    if kind in ("-damage", "-heal") and len(args) >= 2:
        hp, _, status = args[1].partition(" ")
        if status == "fnt":
            return ""  # the faint line says it
        current, _, top = hp.partition("/")
        amount = f"{current}%" if who.startswith("Opposing") and top == "100" else f"{hp} HP"
        verb = "is at" if kind == "-damage" else "healed to"
        return f"{who} {verb} {amount}{f' ({status})' if status else ''}{source}"
    if kind == "-fail":
        what = f" ({effect(args[1])})" if len(args) >= 2 and args[1] else ""
        return f"{who}'s move failed{what}"
    if kind == "cant" and len(args) >= 2:
        reasons = {"par": "paralysis", "slp": "sleep", "frz": "freeze", "flinch": "flinched", "recharge": "recharging"}
        return f"{who} couldn't move ({reasons.get(args[1], effect(args[1]))})"
    if kind == "-activate" and len(args) >= 2:
        return f"{who}: {effect(args[1])} activated"
    if kind == "-mega" and len(args) >= 2:
        return f"{who} Mega Evolved"
    if kind in ("-start", "-end") and len(args) >= 2:
        return f"{who}: {effect(args[1])} {'started' if kind == '-start' else 'ended'}{source}"
    if kind in ("-boost", "-unboost") and len(args) >= 3:
        sign = "+" if kind == "-boost" else "-"
        return f"{who}: {args[1]} {sign}{args[2]}{source}"
    if kind == "-setboost" and len(args) >= 3:
        return f"{who}: {args[1]} set to {args[2]}{source}"
    if kind in ("-clearboost", "-clearallboost", "-clearnegativeboost"):
        return f"{who}'s stat changes were cleared" if who else "All stat changes were cleared"
    if kind == "-curestatus" and len(args) >= 2:
        return f"{who} was cured of {args[1]}"
    if kind == "-hitcount" and len(args) >= 2:
        return f"Hit {args[1]} times"
    return None


def format_recent_turns(battle: Battle, turns: int = 3, max_lines: int = 40, full: bool = False) -> List[str]:
    """The last few turns of the battle, grouped by turn, read from the battle's protocol log.
    Events after `|turn|k` are the resolution of turn k; turn 0 is the leads coming in."""
    data = getattr(battle, "_replay_data", None) or []
    role = getattr(battle, "player_role", None)
    groups: Dict[int, List[str]] = {}
    turn = 0
    for msg in data:
        if len(msg) > 2 and msg[1] == "turn":
            turn = int(msg[2])
            continue
        line = _format_event(msg, role, full)
        if line:
            groups.setdefault(turn, []).append(line)
    lines: List[str] = []
    for t in sorted(groups):
        if t >= battle.turn - turns:
            lines.append(f"Turn {t}:" if t else "Leads:")
            lines.extend(f"- {e}" for e in groups[t])
    return lines[-max_lines:]


def bench_of(battle: Battle, brought: Optional[List[str]] = None) -> list:
    """The player's bench. In a bring-N format poke-env still lists all six from team preview, so only the Pokémon
    it brought count."""
    return [mon for mon in battle.team.values()
            if mon != battle.active_pokemon and (brought is None or mon.species in brought)]


def unseen_line(preview: List[str], seen: set, pick: Optional[int] = None) -> str:
    """The opponent's Pokémon from team preview not seen yet; in a bring-N format, how many of them can still come."""
    unseen = [s for s in preview if s not in seen]
    if not unseen:
        return ""
    if not pick or pick >= len(preview):
        return f"Not yet seen in battle (from team preview): {', '.join(unseen)}"
    still = max(pick - len(seen), 0)
    if not still:
        return f"The opponent brought {pick} of the {len(preview)} it showed at team preview: all have been seen."
    return (f"The opponent brought {pick} of the {len(preview)} it showed at team preview: {still} more "
            f"{'is' if still == 1 else 'are'} still to come in, from: {', '.join(unseen)}")


def format_battle_state(battle: Battle, brought: Optional[List[str]] = None, pick: Optional[int] = None,
                        state: int = 1) -> str:
    """Serializes the battle for the prompt. Sections that rarely change (the benches) come first and the
    turn-specific ones last, so a local server can reuse more of its prompt cache from the previous turn.
    `state` is the ruleset's battle_state version (2: what Showdown's interface shows, see RulesetConfig)."""
    fmt = battle.format or "gen9ou"
    champions = state >= 2 and dex_mod(fmt) == "champions"
    lines = ["#### YOUR BENCH:"]
    bench = bench_of(battle, brought)
    if bench:
        lines.extend(format_pokemon_summary(mon, False, False, state, fmt) for mon in bench)
    else:
        lines.append("- (No bench Pokémon remaining)")

    lines.append("\n#### OPPONENT'S REVEALED BENCH:")
    opp_bench = [mon for mon in battle.opponent_team.values() if mon != battle.opponent_active_pokemon]
    if opp_bench:
        lines.extend(format_pokemon_summary(mon, False, True, state, fmt) for mon in opp_bench)
    else:
        lines.append("- (No other Pokémon revealed yet)")
    seen = {mon.species for mon in battle.opponent_team.values()}
    preview = [mon.species for mon in getattr(battle, "teampreview_opponent_team", None) or []]
    unseen = [s for s in preview if s not in seen]
    line = unseen_line(preview, seen, pick)
    if line:
        lines.append(line)

    lines.append(
        f"\n### Turn {battle.turn} | Format: {battle.format} | Weather: {_condition_names(battle.weather)}"
        f" | Field: {_condition_names(battle.fields)}"
    )
    recent = format_recent_turns(battle, full=state >= 2)
    if recent:
        lines.append("\n#### RECENT TURNS:")
        lines.extend(recent)

    lines.append("\n#### YOUR ACTIVE POKÉMON:")
    lines.append(format_pokemon_summary(battle.active_pokemon, True, False, state, fmt))
    side_conds = [k.name.title() for k in battle.side_conditions.keys()]
    lines.append(f"Your side hazards / conditions: {', '.join(side_conds) if side_conds else 'None'}")
    mine = battle.active_pokemon.species if battle.active_pokemon else "your Pokemon"
    if champions:
        lines.append(f"Mega Evolution available: Yes, {mine} can Mega Evolve this turn (add [MEGA] to a move)"
                     if battle.can_mega_evolve else "Mega Evolution available: No")
    else:
        lines.append(f"Terastallization available: {'Yes' if battle.can_tera else 'No'}")

    lines.append("\n#### OPPONENT'S ACTIVE POKÉMON:")
    lines.append(format_pokemon_summary(battle.opponent_active_pokemon, True, True, state, fmt))
    opp_side_conds = [k.name.title() for k in battle.opponent_side_conditions.keys()]
    lines.append(f"Opponent side hazards / conditions: {', '.join(opp_side_conds) if opp_side_conds else 'None'}")
    if champions:
        lines.append(f"Opponent Mega Evolved: {'Yes' if getattr(battle, 'opponent_used_mega_evolve', False) else 'No'}")
    else:
        lines.append(f"Opponent terastallized: {'Yes' if getattr(battle, 'opponent_used_tera', False) else 'No'}")
    if state >= 2 and speed_line(battle):
        lines.append(speed_line(battle))

    lines.append("\n#### LEGAL ACTIONS THIS TURN:")
    legal_actions = []
    if battle.available_moves:
        for m in battle.available_moves:
            m_type = m.type.name.title() if m.type else "Normal"
            legal_actions.append(_move_line(m, battle, fmt) if state >= 2 else
                                 f"MOVE: {m.id} (Type: {m_type}, BP: {m.base_power or '-'}, Acc: {m.accuracy or '-'})")
            if battle.can_tera:
                legal_actions.append(f"MOVE: {m.id} [TERA]")
            if battle.can_mega_evolve:  # Champions: Mega Evolve this turn, then use the move
                legal_actions.append(f"MOVE: {m.id} [MEGA]" + (f" | Mega Evolve {mine} first, then use {m.id}"
                                                                if state >= 2 else ""))
    if battle.available_switches:
        for s in battle.available_switches:
            s_hp = round(s.current_hp_fraction * 100, 1)
            legal_actions.append(f"SWITCH: {s.species} ({s_hp}% HP)")
    for i, act in enumerate(legal_actions, 1):
        lines.append(f"{i}. {act}")

    return "\n".join(lines)


def format_team_preview(battle: Battle, pick: Optional[int] = None, state: int = 1) -> str:
    """Team preview: both teams before the battle; the player picks its lead, or, in a bring-N format, the N
    Pokémon it brings in order (the first leads)."""
    choosing = pick is not None and pick < len(battle.team)
    lines = [
        f"### Team preview (before turn 1) | Format: {battle.format}",
        (f"Both teams are shown before the battle starts. You bring {pick} of your {len(battle.team)} Pokémon (so does "
         f"your opponent): the only legal action is choosing them, in order (BRING: <species>, <species>, ...). The "
         f"first one leads; the others wait in the back. The rest sit this battle out." if choosing else
         "Both teams are shown before the battle starts. No moves can be used yet: the only legal action is "
         "choosing the Pokémon you lead with (LEAD: <species>). The rest of your team stays in its current order."),
        "\n#### YOUR TEAM:",
    ]
    fmt = battle.format or "gen9ou"
    lines.extend(format_pokemon_summary(mon, False, False, state, fmt) for mon in battle.team.values())
    lines.append("\n#### OPPONENT'S TEAM:")
    for mon in getattr(battle, "teampreview_opponent_team", None) or []:
        types = "/".join(t.name.title() for t in mon.types if t)
        if state >= 2:
            ranges = ", ".join(f"{STAT_NAMES[k]} {'-'.join(map(str, stat_range(mon, k)))}" for k in STATS)
            abilities = ", ".join(mon.possible_abilities or [])
            lines.append(f"- **{mon.species}** ({types}) | Stats at level {mon.level} (possible range): [{ranges}]"
                         + (f" | Possible abilities: {abilities}" if abilities else ""))
        else:
            stats = ", ".join(f"{k.upper()}: {v}" for k, v in (mon.base_stats or {}).items())
            lines.append(f"- **{mon.species}** ({types}) | Base Stats: [{stats}]")
    lines.append("\n#### LEGAL ACTIONS THIS TURN:")
    if choosing:
        lines.append(f"BRING: any {pick} different Pokémon from YOUR TEAM, comma-separated, the leader first "
                     f"(for example BRING: {', '.join(m.species for m in list(battle.team.values())[:pick])})")
    else:
        lines.extend(f"{i}. LEAD: {mon.species}" for i, mon in enumerate(battle.team.values(), 1))
    return "\n".join(lines)


# Facts of a format the battle prompt states, which a model would otherwise have to guess
FORMAT_FACTS = {"gen9championsrotomarenabssregmb": "All Pokémon in this battle are level 50."}
# How the battle prompt names a format other than Gen 9 OU (the prompt was written for it)
FORMAT_NAMES = {"gen9championsrotomarenarandombss": "Pokémon Champions singles (bring 6, pick 3)",
                "gen9championsrotomarenabssregmb": "Pokémon Champions singles (bring 6, pick 3)"}


def system_prompt_for(fmt: str, pick: Optional[int] = None, attempts: int = 1, state: int = 1) -> str:
    """The battle system prompt for this format: unchanged for Gen 9 OU. With a second try (ruleset.answer_attempts)
    rule 3 says so; battle state 2 gives Champions a Champions example (the Gen 9 OU one named Great Tusk)."""
    prompt = SYSTEM_PROMPT_DIRECT_COT
    if attempts > 1:
        prompt = prompt.replace(
            "3. If your action is not in LEGAL ACTIONS, or your answer is cut off, the first legal move is played for you.",
            "3. If your action is not in LEGAL ACTIONS, or your answer is empty or cut off, you get one more try, told\n"
            "   what was wrong; if that one fails too, the first legal move is played for you.")
    if fmt == "gen9ou":
        return prompt
    prompt = prompt.replace("Gen 9 OU", FORMAT_NAMES.get(fmt, fmt))
    if state >= 2 and dex_mod(fmt) == "champions":
        prompt = prompt.replace(
            "Heatran is 4x weak to Ground and slower than Great Tusk, so Headlong Rush should knock it out before it moves.",
            "Kingambit is 4x weak to Fighting and slower than Annihilape, so Drain Punch should knock it out before it moves.")
        prompt = prompt.replace("MOVE: headlongrush", "MOVE: drainpunch")
    if fmt in FORMAT_FACTS:
        prompt = prompt.replace("Choose the single best action for this turn.",
                                f"{FORMAT_FACTS[fmt]} Choose the single best action for this turn.")
    if pick:
        prompt = prompt.replace("(at team preview: LEAD: <species>)",
                                f"(at team preview: BRING: <{pick} species, comma-separated>)")
    if fmt in FORMAT_FACTS:  # Champions: Mega Evolution, not Terastallization
        prompt = prompt.replace("MOVE: <move_id> [TERA]", "MOVE: <move_id> [MEGA]")
    return prompt


SYSTEM_PROMPT_DIRECT_COT = """You are an expert competitive Pokémon player and Gen 9 OU tournament grandmaster.
Choose the single best action for this turn.

RULES:
1. Keep <thought> to 2-4 short sentences (80 words at most). Name the deciding factor: speed, a likely
   knockout, or a bad matchup to switch out of. Do not write out damage formulas or go through every option.
2. Your <decision> block must contain exactly one action line, copied from LEGAL ACTIONS without its number:
   MOVE: <move_id>   or   MOVE: <move_id> [TERA]   or   SWITCH: <species>   (at team preview: LEAD: <species>)
3. If your action is not in LEGAL ACTIONS, or your answer is cut off, the first legal move is played for you.

Example answer:
<thought>
Heatran is 4x weak to Ground and slower than Great Tusk, so Headlong Rush should knock it out before it moves.
</thought>
<decision>
MOVE: headlongrush
</decision>
"""


USER_PROMPT_DIRECT_COT_TEMPLATE = """Here is the current battle state:

{battle_state}

Choose exactly one action from LEGAL ACTIONS."""
