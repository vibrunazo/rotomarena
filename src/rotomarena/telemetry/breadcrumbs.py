"""Per-turn reasoning breadcrumbs logger for post-match inspection and telemetry."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# Who actually picked the move: the agent itself, or the fallback after a failure.
# "forced": only one action was legal, played without asking (battle state 3); not the model's, not autopilot either
DecisionSource = Literal["model", "timeout", "api_error", "parse_error", "invalid", "error", "forced"]


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

    # The Showdown name it played under; breadcrumbs and the winner refer to it. It differs from display_name when
    # several games of a set run at once (lane 2 is "Qwen3.8 27B 2") or in a mirror match.
    username: str
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
    hidden_reasoning: str = ""
    search_telemetry: Optional[Dict[str, Any]] = None
    llm_metrics: Optional[Dict[str, Any]] = None
    # A decision model's probability for every option it was offered ({"MOVE: earthquake": 0.62, ...})
    probabilities: Optional[Dict[str, float]] = None
    # Tries the decision took (ruleset.answer_attempts), and why the first one failed with what it said
    attempts: int = 1
    first_try: str = ""
    # The model's visible answer as written, tags and all (its last try): format slips show here, such as Opus 5.5's
    # thought without its <thought> tags, which the parser still reads
    answer: str = ""
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
    tags: List[str] = Field(
        default_factory=list,
        description="Labels set by hand. 'superseded:<label>:<config id>': that player played under an earlier form of "
        "its version's rules (c5's medium effort before its 4,096-token budget); the game still counts until "
        "retired (voided) once enough games under the new rule are in",
    )
    voided: Optional[str] = Field(
        default=None, description="Why this game was voided after it was played (set by hand); a voided game is not rated"
    )

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

    def __init__(self, match_id: str, format_str: str = "gen9ou", ruleset: Optional[Dict[str, Any]] = None,
                 live_dir: Optional[Path] = None):
        self.match_id = match_id
        self.format_str = format_str
        self.ruleset = ruleset or {}
        self.breadcrumbs: List[TurnBreadcrumb] = []
        # Each decision is also appended to <live_dir>/<battle tag>.jsonl as it is made, for watching a game live.
        # Files of games over a day old are removed when a new game starts; the saved game has everything.
        self.live_dir = live_dir
        self.live_files: List[Path] = []
        if live_dir is not None and live_dir.exists():
            for old in live_dir.glob("*.jsonl"):
                if time.time() - old.stat().st_mtime > 86400:
                    old.unlink(missing_ok=True)

    def record_turn(self, breadcrumb: TurnBreadcrumb, battle_tag: Optional[str] = None) -> None:
        """Append a breadcrumb record (and its live line, when the battle is known)."""
        self.breadcrumbs.append(breadcrumb)
        if self.live_dir is None or not battle_tag:
            return
        path = self.live_dir / f"{battle_tag}.jsonl"
        first = path not in self.live_files
        if first:  # a new game: start the file over, in case an old battle had the same tag
            self.live_files.append(path)
            path.parent.mkdir(parents=True, exist_ok=True)
        metrics = breadcrumb.llm_metrics or {}
        line = {"turn": breadcrumb.turn, "player": breadcrumb.agent_name, "source": breadcrumb.decision_source,
                "action": breadcrumb.chosen_action, "thought": breadcrumb.reasoning,
                "seconds": round((metrics.get("latency_ms") or 0) / 1000, 1),
                "thinking_tokens": metrics.get("reasoning_tokens") or 0}
        if breadcrumb.probabilities:
            line["probabilities"] = breadcrumb.probabilities
        with open(path, "w" if first else "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

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
