"""Preset Gen 9 OU teams and helper discovery functions."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
from rotomarena.teams.loader import Team, load_team_file, parse_smogon_team


def get_default_teams_dir() -> Path:
    """Find the default teams directory."""
    # Check data/teams in project root or relative to package
    candidates = [
        Path("data/teams"),
        Path(__file__).parent.parent.parent.parent / "data" / "teams",
        Path(__file__).parent / "data",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    return Path("data/teams")


def list_available_teams(teams_dir: Optional[Path] = None) -> List[Path]:
    """List all .txt team files in the teams directory."""
    target_dir = teams_dir or get_default_teams_dir()
    if not target_dir.exists():
        return []
    return sorted(list(target_dir.glob("*.txt")))


def load_preset_team(team_identifier: str, teams_dir: Optional[Path] = None) -> Team:
    """Load a team by file path, name stem, or filename."""
    target_dir = teams_dir or get_default_teams_dir()
    path = Path(team_identifier)

    # 1. Exact path
    if path.exists() and path.is_file():
        return load_team_file(path)

    # 2. Check in teams dir
    candidate = target_dir / f"{team_identifier}.txt"
    if candidate.exists():
        return load_team_file(candidate)

    # 3. Check with prefix gen9ou_
    candidate = target_dir / f"gen9ou_{team_identifier}.txt"
    if candidate.exists():
        return load_team_file(candidate)

    # 4. Partial match
    for f in target_dir.glob("*.txt"):
        if team_identifier.lower() in f.stem.lower():
            return load_team_file(f)

    raise ValueError(
        f"Could not find team '{team_identifier}'. Available teams in {target_dir}: "
        f"{[f.stem for f in list_available_teams(target_dir)]}"
    )
