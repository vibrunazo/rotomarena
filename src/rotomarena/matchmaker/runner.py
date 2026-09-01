"""1v1 Matchup Runner and Series Orchestrator."""

from __future__ import annotations

import datetime
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from poke_env.player.player import Player
from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.config import TelemetryConfig
from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder, MatchTelemetry
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
    commentary_json_path: Optional[str] = None


class SeriesResult(BaseModel):
    """Result of a multi-game series between two agents."""

    p1_name: str
    p2_name: str
    total_games: int
    p1_wins: int = 0
    p2_wins: int = 0
    draws: int = 0
    matches: List[MatchResult] = Field(default_factory=list)

    @property
    def p1_win_rate(self) -> float:
        return round((self.p1_wins / max(1, self.total_games)) * 100, 2)

    @property
    def p2_win_rate(self) -> float:
        return round((self.p2_wins / max(1, self.total_games)) * 100, 2)


class MatchRunner:
    """Orchestrates 1v1 battle series between two configured players."""

    def __init__(self, telemetry_config: Optional[TelemetryConfig] = None):
        self.telemetry_config = telemetry_config or TelemetryConfig()
        self.output_dir = Path(self.telemetry_config.output_dir)

    async def run_single_battle(
        self,
        player_1: BaseBenchmarkPlayer,
        player_2: BaseBenchmarkPlayer,
        match_index: int = 1,
    ) -> MatchResult:
        """Executes a single battle between player_1 and player_2."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_p1 = re.sub(r"[^\w\s-]", "_", player_1.agent_name).strip()
        safe_p2 = re.sub(r"[^\w\s-]", "_", player_2.agent_name).strip()
        match_id = f"match_{timestamp}_{safe_p1}_vs_{safe_p2}_g{match_index}"
        match_dir = self.output_dir / match_id
        match_dir.mkdir(parents=True, exist_ok=True)

        recorder = BreadcrumbsRecorder(
            match_id=match_id,
            p1_name=player_1.agent_name,
            p2_name=player_2.agent_name,
            format_str=player_1.format,
        )
        player_1.set_recorder(recorder)
        player_2.set_recorder(recorder)

        start_time = time.perf_counter()

        # Execute battle via poke-env
        await player_1.battle_against(player_2, n_battles=1)

        duration = time.perf_counter() - start_time

        # Retrieve the latest battle
        last_battle_p1 = list(player_1.battles.values())[-1]
        
        winner: Optional[str] = None
        if last_battle_p1.won:
            winner = player_1.agent_name
        elif last_battle_p1.lost:
            winner = player_2.agent_name

        total_turns = last_battle_p1.turn

        # Finalize telemetry
        telemetry = recorder.finalize(
            winner=winner, total_turns=total_turns, duration_sec=duration
        )

        # Save outputs
        breadcrumbs_path = None
        replay_html_path = None
        report_md_path = None

        if self.telemetry_config.save_breadcrumbs:
            b_path = match_dir / "breadcrumbs.json"
            telemetry.save_json(b_path)
            breadcrumbs_path = str(b_path)

        # Get logs from battle if available
        raw_logs = getattr(last_battle_p1, "_replay_data", []) or []
        if not raw_logs and hasattr(last_battle_p1, "observations"):
            raw_logs = [str(obs) for obs in last_battle_p1.observations.values()]

        commentary = None
        commentary_path = None
        if self.telemetry_config.generate_commentary:
            try:
                from rotomarena.commentary.generator import CommentaryGenerator
                gen = CommentaryGenerator()
                commentary = await gen.generate_commentary(
                    raw_logs=raw_logs,
                    p1_name=player_1.agent_name,
                    p2_name=player_2.agent_name,
                    match_id=match_id,
                    winner=winner,
                    total_turns=total_turns,
                    format_str=player_1.format,
                    breadcrumbs=[b.model_dump() for b in telemetry.breadcrumbs],
                )
                comm_p = match_dir / "commentary.json"
                comm_p.write_text(commentary.model_dump_json(indent=2), encoding="utf-8")
                commentary_path = str(comm_p)
            except Exception as e:
                import logging
                logging.getLogger("rotomarena").warning(f"Failed to generate commentary: {e}")

        if self.telemetry_config.save_replays:
            html_p = match_dir / "replay.html"
            save_battle_replay_html(
                match_id=match_id,
                player_1=player_1.agent_name,
                player_2=player_2.agent_name,
                winner=winner,
                total_turns=total_turns,
                duration_seconds=duration,
                raw_logs=raw_logs,
                output_path=html_p,
                format_str=player_1.format,
                commentary=commentary,
            )
            replay_html_path = str(html_p)

            raw_json_p = match_dir / "battle_log.json"
            save_battle_raw_json(
                match_id=match_id,
                metadata={
                    "winner": winner,
                    "turns": total_turns,
                    "duration_seconds": duration,
                },
                raw_logs=raw_logs,
                output_path=raw_json_p,
            )

        if self.telemetry_config.save_reports:
            rep_p = match_dir / "report.md"
            generate_match_markdown_report(telemetry, rep_p)
            report_md_path = str(rep_p)

        return MatchResult(
            match_id=match_id,
            p1_name=player_1.agent_name,
            p2_name=player_2.agent_name,
            winner=winner,
            total_turns=total_turns,
            duration_seconds=round(duration, 2),
            replay_html_path=replay_html_path,
            breadcrumbs_json_path=breadcrumbs_path,
            report_md_path=report_md_path,
            commentary_json_path=commentary_path,
        )

    async def run_series(
        self,
        player_1: BaseBenchmarkPlayer,
        player_2: BaseBenchmarkPlayer,
        n_games: int = 2,
    ) -> SeriesResult:
        """Runs a multi-game series between two players."""
        series = SeriesResult(
            p1_name=player_1.agent_name,
            p2_name=player_2.agent_name,
            total_games=n_games,
        )

        try:
            for g in range(1, n_games + 1):
                match_res = await self.run_single_battle(player_1, player_2, match_index=g)
                series.matches.append(match_res)

                if match_res.winner == player_1.agent_name:
                    series.p1_wins += 1
                elif match_res.winner == player_2.agent_name:
                    series.p2_wins += 1
                else:
                    series.draws += 1
        finally:
            for p in (player_1, player_2):
                try:
                    if hasattr(p, "ps_client") and hasattr(p.ps_client, "stop_listening"):
                        await p.ps_client.stop_listening()
                except Exception:
                    pass

        return series
