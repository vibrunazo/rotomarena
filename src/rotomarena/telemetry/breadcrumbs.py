"""Per-turn reasoning breadcrumbs logger for post-match inspection and telemetry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TurnBreadcrumb(BaseModel):
    """Structured telemetry breadcrumb for a single battle turn."""

    turn: int
    agent_name: str
    agent_type: str
    active_pokemon: str = ""
    active_hp_pct: float = 100.0
    opponent_active: str = ""
    opponent_hp_pct: float = 100.0
    legal_actions: List[str] = Field(default_factory=list)
    chosen_action: str = ""
    reasoning: str = ""
    search_telemetry: Optional[Dict[str, Any]] = None
    llm_metrics: Optional[Dict[str, Any]] = None
    timestamp: str = ""


class MatchTelemetry(BaseModel):
    """Full telemetry recording for a single completed battle."""

    match_id: str
    format: str = "gen9ou"
    player_1: str
    player_2: str
    winner: Optional[str] = None
    total_turns: int = 0
    duration_seconds: float = 0.0
    breadcrumbs: List[TurnBreadcrumb] = Field(default_factory=list)

    def save_json(self, output_path: str | Path) -> Path:
        """Serializes telemetry breadcrumbs to a structured JSON file."""
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return p


class BreadcrumbsRecorder:
    """Manages active turn breadcrumbs collection across a match."""

    def __init__(self, match_id: str, p1_name: str, p2_name: str, format_str: str = "gen9ou"):
        self.match_id = match_id
        self.p1_name = p1_name
        self.p2_name = p2_name
        self.format_str = format_str
        self.breadcrumbs: List[TurnBreadcrumb] = []

    def record_turn(self, breadcrumb: TurnBreadcrumb) -> None:
        """Append a breadcrumb record."""
        self.breadcrumbs.append(breadcrumb)

    def finalize(self, winner: Optional[str], total_turns: int, duration_sec: float) -> MatchTelemetry:
        """Produce finalized MatchTelemetry object."""
        return MatchTelemetry(
            match_id=self.match_id,
            format=self.format_str,
            player_1=self.p1_name,
            player_2=self.p2_name,
            winner=winner,
            total_turns=total_turns,
            duration_seconds=round(duration_sec, 2),
            breadcrumbs=self.breadcrumbs,
        )
