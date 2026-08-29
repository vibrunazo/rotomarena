"""Round-Robin Tournament Bracket Orchestrator."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.agents.direct_llm import DirectLLMPlayer
from rotomarena.agents.heuristic import HeuristicPlayer, MaxDamagePlayer
from rotomarena.agents.pokechamp import PokeChampPlayer
from rotomarena.agents.random import RandomBenchmarkPlayer
from rotomarena.config import AgentConfig, AppConfig, TournamentConfig
from rotomarena.llm.client import LLMClient
from rotomarena.matchmaker.elo import EloRatingSystem
from rotomarena.matchmaker.runner import MatchResult, MatchRunner
from rotomarena.teams.presets import load_preset_team


class TournamentSummary(BaseModel):
    """Overall results of a completed round-robin tournament."""

    tournament_name: str
    format: str = "gen9ou"
    total_matches: int = 0
    leaderboard: List[Dict[str, Any]] = Field(default_factory=list)
    matches: List[MatchResult] = Field(default_factory=list)


def create_agent_instance(
    agent_cfg: AgentConfig,
    app_config: AppConfig,
    team_str: Optional[str] = None,
) -> BaseBenchmarkPlayer:
    """Factory to instantiate a Benchmark player from its configuration model."""
    a_type = agent_cfg.type.lower()
    
    # Resolve LLM client if needed
    llm_client = None
    if agent_cfg.provider:
        llm_client = LLMClient.from_provider_name(
            agent_cfg.provider,
            providers_dict=app_config.providers,
            model_override=agent_cfg.model,
        )

    import uuid
    unique_player_name = f"{agent_cfg.name[:13]}_{uuid.uuid4().hex[:4]}"

    from poke_env.ps_client import ServerConfiguration
    server_conf = ServerConfiguration(
        app_config.server.websocket_url,
        "https://play.pokemonshowdown.com/action.php?",
    )

    if a_type == "pokechamp":
        return PokeChampPlayer(
            player_name=unique_player_name,
            depth=agent_cfg.depth,
            use_llm_prior=agent_cfg.use_llm_prior,
            llm_client=llm_client,
            evaluation_weights=agent_cfg.evaluation_weights,
            team=team_str,
            server_configuration=server_conf,
        )
    elif a_type == "direct_llm":
        return DirectLLMPlayer(
            player_name=unique_player_name,
            llm_client=llm_client,
            model=agent_cfg.model,
            temperature=agent_cfg.temperature,
            team=team_str,
            server_configuration=server_conf,
        )
    elif a_type == "max_damage":
        return MaxDamagePlayer(
            player_name=unique_player_name, team=team_str, server_configuration=server_conf
        )
    elif a_type == "heuristic":
        return HeuristicPlayer(
            player_name=unique_player_name,
            evaluation_weights=agent_cfg.evaluation_weights,
            team=team_str,
            server_configuration=server_conf,
        )
    else:
        return RandomBenchmarkPlayer(
            player_name=unique_player_name, team=team_str, server_configuration=server_conf
        )


class TournamentOrchestrator:
    """Runs round-robin tournament brackets among registered agents."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.tournament_config = config.tournament or TournamentConfig()
        self.elo_system = EloRatingSystem(
            initial_elo=self.tournament_config.initial_elo,
            k_factor=self.tournament_config.k_factor,
        )
        self.runner = MatchRunner(telemetry_config=config.telemetry)
        self.console = Console()

    async def run_tournament(self) -> TournamentSummary:
        """Executes full round-robin tournament bracket."""
        participants = self.tournament_config.participants
        if not participants:
            participants = list(self.config.agents.keys())

        if len(participants) < 2:
            raise ValueError(
                f"Tournament requires at least 2 participants. Found: {participants}"
            )

        self.console.rule(f"[bold cyan]⚡ RotomArena Tournament: {self.tournament_config.name}[/bold cyan]")
        self.console.print(f"Participants: [green]{', '.join(participants)}[/green]")
        self.console.print(f"Rounds per pair: {self.tournament_config.rounds_per_pair}")

        # Load default teams
        team_paths = self.tournament_config.teams
        loaded_teams = [
            load_preset_team(t_path).to_showdown_packed()
            for t_path in team_paths
        ] if team_paths else [None]

        pairs = list(itertools.combinations(participants, 2))
        all_matches: List[MatchResult] = []

        for p1_name, p2_name in pairs:
            p1_cfg = self.config.agents.get(p1_name, AgentConfig(name=p1_name))
            p2_cfg = self.config.agents.get(p2_name, AgentConfig(name=p2_name))

            for round_idx in range(1, self.tournament_config.rounds_per_pair + 1):
                # Pick teams for round
                t1 = loaded_teams[(round_idx - 1) % len(loaded_teams)]
                t2 = loaded_teams[round_idx % len(loaded_teams)]

                # Alternate side assignments
                if round_idx % 2 == 1:
                    player_a = create_agent_instance(p1_cfg, self.config, team_str=t1)
                    player_b = create_agent_instance(p2_cfg, self.config, team_str=t2)
                else:
                    player_a = create_agent_instance(p2_cfg, self.config, team_str=t2)
                    player_b = create_agent_instance(p1_cfg, self.config, team_str=t1)

                self.console.print(
                    f"\n[bold yellow]▶ Match:[/bold yellow] [cyan]{player_a.agent_name}[/cyan] vs [magenta]{player_b.agent_name}[/magenta] (Game {round_idx}/{self.tournament_config.rounds_per_pair})"
                )

                match_res = await self.runner.run_single_battle(
                    player_a, player_b, match_index=round_idx
                )
                all_matches.append(match_res)

                # Update Elo
                new_a, new_b = self.elo_system.record_match(
                    player_a.agent_name, player_b.agent_name, winner=match_res.winner
                )

                winner_str = f"[bold green]{match_res.winner}[/bold green]" if match_res.winner else "[dim]Draw[/dim]"
                self.console.print(
                    f"  Result: Winner = {winner_str} in {match_res.total_turns} turns ({match_res.duration_seconds}s)"
                )
                self.console.print(
                    f"  Elo: {player_a.agent_name} -> {new_a:.1f} | {player_b.agent_name} -> {new_b:.1f}"
                )

        # Print Leaderboard
        leaderboard = self.elo_system.get_leaderboard()
        self.display_leaderboard(leaderboard)

        # Save tournament summary
        summary = TournamentSummary(
            tournament_name=self.tournament_config.name,
            format=self.tournament_config.format,
            total_matches=len(all_matches),
            leaderboard=[s.model_dump() for s in leaderboard],
            matches=all_matches,
        )

        out_path = Path(self.config.telemetry.output_dir) / "tournament_summary.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")

        return summary

    def display_leaderboard(self, leaderboard: List[Any]) -> None:
        """Renders leaderboard table to console."""
        table = Table(title="🏆 RotomArena Tournament Leaderboard", show_header=True, header_style="bold magenta")
        table.add_column("Rank", justify="center", style="dim", width=6)
        table.add_column("Agent", style="bold cyan")
        table.add_column("Elo Rating", justify="right", style="bold yellow")
        table.add_column("Win Rate", justify="right", style="green")
        table.add_column("Record (W-L-D)", justify="center")

        for rank, stats in enumerate(leaderboard, 1):
            table.add_row(
                str(rank),
                stats.name,
                f"{stats.elo:.1f}",
                f"{stats.win_rate}%",
                f"{stats.wins}-{stats.losses}-{stats.draws}",
            )

        self.console.print("\n")
        self.console.print(table)
