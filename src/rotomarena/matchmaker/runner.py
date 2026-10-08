"""1v1 Matchup Runner and Series Orchestrator."""

from __future__ import annotations

import datetime
import re
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from pydantic import BaseModel, Field

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.config import RulesetConfig, TelemetryConfig
from rotomarena.teams.loader import Team
from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder, MatchPlayer
from rotomarena.telemetry.replay_saver import save_battle_raw_json, save_battle_replay_html
from rotomarena.telemetry.reporter import generate_match_markdown_report


class MatchResult(BaseModel):
    """Result of a single 1v1 battle."""

    match_id: str
    p1_name: str
    p2_name: str
    winner: Optional[str]
    total_turns: int
    duration_seconds: float
    replay_html_path: Optional[str] = None
    breadcrumbs_json_path: Optional[str] = None
    report_md_path: Optional[str] = None


class SeriesResult(BaseModel):
    """Result of a multi-game series between two agents."""

    a_name: str
    b_name: str
    total_games: int
    a_wins: int = 0
    b_wins: int = 0
    draws: int = 0
    matches: List[MatchResult] = Field(default_factory=list)

    @property
    def a_win_rate(self) -> float:
        return round((self.a_wins / max(1, self.total_games)) * 100, 2)

    @property
    def b_win_rate(self) -> float:
        return round((self.b_wins / max(1, self.total_games)) * 100, 2)


def series_schedule(n_games: int) -> List[Tuple[bool, bool]]:
    """Per game: (swap_teams, b_challenges). Every 4 games cover both team assignments from both sides."""
    return [((g // 2) % 2 == 1, g % 2 == 1) for g in range(n_games)]


class MatchRunner:
    """Orchestrates 1v1 battle series between two configured players."""

    def __init__(
        self,
        telemetry_config: Optional[TelemetryConfig] = None,
        ruleset: Optional[RulesetConfig] = None,
    ):
        self.telemetry_config = telemetry_config or TelemetryConfig()
        self.ruleset = ruleset or RulesetConfig()
        self.output_dir = Path(self.telemetry_config.output_dir)

    async def run_single_battle(
        self,
        challenger: BaseBenchmarkPlayer,
        opponent: BaseBenchmarkPlayer,
        team_names: Tuple[str, str],
        match_index: int = 1,
    ) -> MatchResult:
        """Executes one battle; `team_names` are the challenger's and the opponent's teams."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_a = re.sub(r"[^\w\s-]", "_", challenger.agent_name).strip()
        safe_b = re.sub(r"[^\w\s-]", "_", opponent.agent_name).strip()
        match_id = f"match_{timestamp}_{safe_a}_vs_{safe_b}_g{match_index}"
        match_dir = self.output_dir / match_id
        match_dir.mkdir(parents=True, exist_ok=True)

        recorder = BreadcrumbsRecorder(
            match_id=match_id,
            format_str=challenger.format,
            ruleset=self.ruleset.model_dump(),
        )
        challenger.set_recorder(recorder)
        opponent.set_recorder(recorder)

        known_battles = set(challenger.battles)
        start_time = time.perf_counter()
        await challenger.battle_against(opponent, n_battles=1)
        duration = time.perf_counter() - start_time

        new_battles = [b for tag, b in challenger.battles.items() if tag not in known_battles]
        if len(new_battles) != 1 or not new_battles[0].finished:
            raise RuntimeError(
                f"Expected one finished battle from this challenge, got {len(new_battles)} new "
                f"({sum(b.finished for b in new_battles)} finished). Was another battle with these bots still open?"
            )
        battle = new_battles[0]
        challenger_role = battle.player_role or "p1"
        opponent_role = "p2" if challenger_role == "p1" else "p1"
        players = [
            MatchPlayer(**challenger.identity.model_dump(), username=challenger.agent_name, role=challenger_role,
                        team=team_names[0]),
            MatchPlayer(**opponent.identity.model_dump(), username=opponent.agent_name, role=opponent_role,
                        team=team_names[1]),
        ]
        names = {challenger_role: challenger.agent_name, opponent_role: opponent.agent_name}

        winner: Optional[str] = None
        if battle.won:
            winner = challenger.agent_name
        elif battle.lost:
            winner = opponent.agent_name
        total_turns = battle.turn

        telemetry = recorder.finalize(
            players=players, winner=winner, total_turns=total_turns, duration_sec=duration
        )

        breadcrumbs_path = None
        replay_html_path = None
        report_md_path = None

        if self.telemetry_config.save_breadcrumbs:
            b_path = match_dir / "breadcrumbs.json"
            telemetry.save_json(b_path)
            breadcrumbs_path = str(b_path)

        raw_logs = getattr(battle, "_replay_data", []) or []

        if self.telemetry_config.save_replays:
            html_p = match_dir / "replay.html"
            save_battle_replay_html(
                match_id=match_id,
                player_1=names["p1"],
                player_2=names["p2"],
                winner=winner,
                total_turns=total_turns,
                duration_seconds=duration,
                raw_logs=raw_logs,
                output_path=html_p,
                format_str=challenger.format,
            )
            replay_html_path = str(html_p)

            save_battle_raw_json(
                match_id=match_id,
                metadata={
                    "winner": winner,
                    "turns": total_turns,
                    "duration_seconds": duration,
                    "players": [p.model_dump() for p in telemetry.players],
                    "ruleset": telemetry.ruleset,
                },
                raw_logs=raw_logs,
                output_path=match_dir / "battle_log.json",
            )

        if self.telemetry_config.save_reports:
            rep_p = match_dir / "report.md"
            generate_match_markdown_report(telemetry, rep_p)
            report_md_path = str(rep_p)

        return MatchResult(
            match_id=match_id,
            p1_name=names["p1"],
            p2_name=names["p2"],
            winner=winner,
            total_turns=total_turns,
            duration_seconds=round(duration, 2),
            replay_html_path=replay_html_path,
            breadcrumbs_json_path=breadcrumbs_path,
            report_md_path=report_md_path,
        )

    async def run_game(
        self, player_a: BaseBenchmarkPlayer, player_b: BaseBenchmarkPlayer, team_1: Team, team_2: Team, game: int
    ) -> MatchResult:
        """Game `game` (0-based) of a set: who challenges and who gets which team follow series_schedule."""
        swap_teams, b_challenges = series_schedule(game + 1)[game]
        team_a, team_b = (team_2, team_1) if swap_teams else (team_1, team_2)
        player_a.update_team(team_a.to_showdown_packed())
        player_b.update_team(team_b.to_showdown_packed())
        if b_challenges:
            return await self.run_single_battle(player_b, player_a, (team_b.name, team_a.name), game + 1)
        return await self.run_single_battle(player_a, player_b, (team_a.name, team_b.name), game + 1)

    async def run_series(
        self,
        player_a: BaseBenchmarkPlayer,
        player_b: BaseBenchmarkPlayer,
        team_1: Team,
        team_2: Team,
        n_games: int = 4,
        first_game: int = 0,
        before_game: Optional[Callable[[], None]] = None,
    ) -> SeriesResult:
        """Runs a series that alternates sides every game and swaps teams every two games.
        `first_game` resumes the schedule after games already played."""
        series = SeriesResult(a_name=player_a.agent_name, b_name=player_b.agent_name, total_games=n_games)

        try:
            for g in range(first_game, first_game + n_games):
                if before_game:
                    before_game()  # e.g. restart a local model server that crashed in the last game
                match_res = await self.run_game(player_a, player_b, team_1, team_2, g)
                series.matches.append(match_res)

                if match_res.winner == player_a.agent_name:
                    series.a_wins += 1
                elif match_res.winner == player_b.agent_name:
                    series.b_wins += 1
                else:
                    series.draws += 1
        finally:
            for p in (player_a, player_b):
                try:
                    if hasattr(p, "ps_client") and hasattr(p.ps_client, "stop_listening"):
                        await p.ps_client.stop_listening()
                except Exception:
                    pass

        return series
