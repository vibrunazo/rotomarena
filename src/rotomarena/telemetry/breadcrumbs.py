"""Per-turn reasoning breadcrumbs logger for post-match inspection and telemetry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# Who actually picked the move: the agent itself, or the fallback after a failure.
DecisionSource = Literal["model", "timeout", "api_error", "parse_error", "invalid", "error"]


class PlayerIdentity(BaseModel):
    """What a player is: the config entry it came from and, for LLMs, the exact model."""

    config_id: str
    display_name: str
    agent_type: str
    provider: Optional[str] = None
    model: Optional[str] = None
    quantization: Optional[str] = None


class MatchPlayer(PlayerIdentity):
    """A player's identity plus its side and team in one match."""

    role: str  # "p1" or "p2", as assigned by Showdown
    team: str = ""


class TurnBreadcrumb(BaseModel):
    """Structured telemetry breadcrumb for a single battle turn."""

    turn: int
    agent_name: str
    agent_type: str
    decision_source: DecisionSource = "model"
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
    ruleset: Dict[str, Any] = Field(default_factory=dict)
    players: List[MatchPlayer] = Field(default_factory=list)
    winner: Optional[str] = None
    total_turns: int = 0
    duration_seconds: float = 0.0
    breadcrumbs: List[TurnBreadcrumb] = Field(default_factory=list)

    def player(self, role: str) -> Optional[MatchPlayer]:
        return next((p for p in self.players if p.role == role), None)

    def save_json(self, output_path: str | Path) -> Path:
        """Serializes telemetry breadcrumbs to a structured JSON file."""
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return p


class BreadcrumbsRecorder:
    """Manages active turn breadcrumbs collection across a match."""

    def __init__(self, match_id: str, format_str: str = "gen9ou", ruleset: Optional[Dict[str, Any]] = None):
        self.match_id = match_id
        self.format_str = format_str
        self.ruleset = ruleset or {}
        self.breadcrumbs: List[TurnBreadcrumb] = []

    def record_turn(self, breadcrumb: TurnBreadcrumb) -> None:
        """Append a breadcrumb record."""
        self.breadcrumbs.append(breadcrumb)

    def finalize(
        self,
        players: List[MatchPlayer],
        winner: Optional[str],
        total_turns: int,
        duration_sec: float,
    ) -> MatchTelemetry:
        """Produce finalized MatchTelemetry object."""
        return MatchTelemetry(
            match_id=self.match_id,
            format=self.format_str,
            ruleset=self.ruleset,
            players=sorted(players, key=lambda p: p.role),
            winner=winner,
            total_turns=total_turns,
            duration_seconds=round(duration_sec, 2),
            breadcrumbs=self.breadcrumbs,
        )
