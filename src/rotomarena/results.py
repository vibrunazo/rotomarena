"""Loading recorded matches and turning them into rated outcomes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from rotomarena.telemetry.breadcrumbs import MatchTelemetry, TurnBreadcrumb


@dataclass
class Outcome:
    """A rated game: config ids of p1 and p2 and p1's score (1 win, 0.5 draw, 0 loss)."""

    match_id: str
    p1: str
    p2: str
    score_p1: float


def load_matches(runs_dir: str | Path, season: Optional[str] = None) -> List[MatchTelemetry]:
    """All recorded matches in `runs_dir`, optionally only those played under one ruleset version."""
    matches = []
    for path in sorted(Path(runs_dir).glob("*/breadcrumbs.json")):
        match = MatchTelemetry.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if season is None or match.ruleset.get("version") == season:
            matches.append(match)
    return matches


def player_turns(match: MatchTelemetry, role: str) -> List[TurnBreadcrumb]:
    player = match.player(role)
    return [b for b in match.breadcrumbs if player and b.agent_name == player.username]


def autopilot_rate(match: MatchTelemetry, role: str) -> float:
    """Share of a side's turns where the fallback, not the agent, picked the move."""
    turns = player_turns(match, role)
    if not turns:
        return 0.0
    return sum(1 for b in turns if b.decision_source != "model") / len(turns)


def void_reason(match: MatchTelemetry, max_autopilot: float) -> Optional[str]:
    """Why a match can't be rated, or None when it counts."""
    p1, p2 = match.player("p1"), match.player("p2")
    if not p1 or not p2:
        return "missing player records"
    if p1.config_id == p2.config_id:
        return "self-play"
    if match.total_turns == 0:
        return "no turns played"
    for role, player in (("p1", p1), ("p2", p2)):
        rate = autopilot_rate(match, role)
        if rate > max_autopilot:
            return f"{player.config_id} was on autopilot for {rate:.0%} of its turns"
    return None


def outcome(match: MatchTelemetry) -> Outcome:
    p1, p2 = match.player("p1"), match.player("p2")
    if match.winner == p1.username:
        score = 1.0
    elif match.winner == p2.username:
        score = 0.0
    else:
        score = 0.5
    return Outcome(match.match_id, p1.config_id, p2.config_id, score)


def rated_outcomes(matches: List[MatchTelemetry], max_autopilot: float) -> List[Outcome]:
    return [outcome(m) for m in matches if void_reason(m, max_autopilot) is None]


def games_between(outcomes: List[Outcome]) -> Dict[frozenset, int]:
    counts: Dict[frozenset, int] = {}
    for o in outcomes:
        key = frozenset((o.p1, o.p2))
        counts[key] = counts.get(key, 0) + 1
    return counts
