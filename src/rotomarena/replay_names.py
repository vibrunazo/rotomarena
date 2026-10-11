"""Replays under the names RotomArena shows. A Showdown log carries each player's username, which for the ladder's
parallel games has a lane number ("Opus 5.5 2": Showdown names must be unique), and is cut to 16-18 characters;
the replay viewers show the model's display name instead. The recorded logs keep the usernames."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from rotomarena.config import AppConfig

RANK_MARKS = " +%@*#&~^☆"  # what Showdown puts before a name in |j| and chat lines
TAGS = re.compile(r"^(.*?)(?: \d+)+$")  # lane numbers and mirror tags at the end of a username


def shown_names(players: Dict[str, Optional[str]]) -> Dict[str, str]:
    """{username: display name} for a game's players. Empty when two players would share a name (a mirror match
    keeps its numbered usernames), or when a name is unknown."""
    if not players or any(not d for d in players.values()) or len(set(players.values())) < len(players):
        return {}
    return {u: d for u, d in players.items() if u != d}


def live_names(usernames: List[str], app_cfg: AppConfig) -> Dict[str, str]:
    """shown_names for a battle still playing, which has no record yet: each username resolved through the registry
    (its Showdown name, tags dropped)."""
    from rotomarena.agents.factory import format_bot_display_name, resolved_model

    bases: Dict[str, str] = {}
    for agent in app_cfg.agents.values():
        base = format_bot_display_name(agent, resolved_model=resolved_model(agent, app_cfg))
        bases.setdefault(base, agent.display_name or base)

    def resolve(username: str) -> Optional[str]:
        if username in bases:
            return bases[username]
        tagged = TAGS.match(username)
        if not tagged:
            return None
        stem = tagged.group(1)
        # a long name loses its end to make room for the tag: then it is a prefix of the full one
        hits = {d for b, d in bases.items() if b == stem} or {d for b, d in bases.items() if stem and b.startswith(stem)}
        return hits.pop() if len(hits) == 1 else None

    return shown_names({u: resolve(u) for u in usernames})


def rename_players(lines: List[str], names: Dict[str, str]) -> List[str]:
    """The log with every player's username replaced by its display name."""
    if not names:
        return lines
    out = []
    for line in lines:
        parts = line.split("|")
        for i in range(2, len(parts)):
            field = parts[i]
            if field in names:
                parts[i] = names[field]
            elif field[:1] in RANK_MARKS and field[1:] in names:
                parts[i] = field[0] + names[field[1:]]
            elif len(parts) > 1 and parts[1] in ("-message", "raw", "html", "inactive", "inactiveoff"):
                for username, shown in names.items():  # "Opus 5.5 2 forfeited."
                    field = re.sub(rf"(?<![\w.]){re.escape(username)}(?![\w.])", shown, field)
                parts[i] = field
        out.append("|".join(parts))
    return out
