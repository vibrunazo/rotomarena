"""RotomArena CLI Application."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rotomarena.config import AgentConfig, AppConfig
from rotomarena.matchmaker.runner import MatchRunner
from rotomarena.matchmaker.tournament import TournamentOrchestrator, create_agent_instance
from rotomarena.server.manager import ShowdownServerManager
from rotomarena.teams.loader import load_team_file, parse_smogon_team
from rotomarena.teams.presets import list_available_teams, load_preset_team

app = typer.Typer(
    name="rotomarena",
    help="RotomArena: Local Pokemon AI Battle Benchmarking Testbed for Gen 9 OU",
    add_completion=False,
)
server_app = typer.Typer(help="Manage local Pokemon Showdown server")
teams_app = typer.Typer(help="Inspect and manage Gen 9 OU teams")
replay_app = typer.Typer(help="Inspect and view battle replays and telemetry")

app.add_typer(server_app, name="server")
app.add_typer(teams_app, name="teams")
app.add_typer(replay_app, name="replay")

console = Console(legacy_windows=False)


# ---------------------------------------------------------------------
# Server Commands
# ---------------------------------------------------------------------


@server_app.command("setup")
def server_setup(
    force: bool = typer.Option(
        False, "--force", "-f", help="Force re-clone and re-install Showdown"
    )
):
    """Setup and configure local Pokémon Showdown repository."""
    manager = ShowdownServerManager()
    console.print("[yellow]Setting up Pokémon Showdown headless server...[/yellow]")
    ok, msg = manager.setup(force_reclone=force)
    if ok:
        console.print(f"[bold green][OK] {msg}[/bold green]")
    else:
        console.print(f"[bold red][ERROR] {msg}[/bold red]")
        raise typer.Exit(1)


@server_app.command("start")
def server_start():
    """Start local Pokémon Showdown server in the background."""
    manager = ShowdownServerManager()
    ok, msg = manager.start()
    if ok:
        console.print(f"[bold green][OK] {msg}[/bold green]")
        console.print(
            f"WebSocket URL: [cyan]{manager.config.websocket_url}[/cyan] (Clock managed by RotomArena: 120s turn / 15m bank)"
        )
    else:
        console.print(f"[bold red][ERROR] {msg}[/bold red]")
        raise typer.Exit(1)


@server_app.command("stop")
def server_stop():
    """Stop running Pokémon Showdown background server."""
    manager = ShowdownServerManager()
    ok, msg = manager.stop()
    if ok:
        console.print(f"[bold green][OK] {msg}[/bold green]")
    else:
        console.print(f"[bold red][ERROR] {msg}[/bold red]")
        raise typer.Exit(1)


@server_app.command("status")
def server_status():
    """Check status and health of Pokémon Showdown server."""
    manager = ShowdownServerManager()
    pid = manager.get_pid()

    async def _check():
        healthy = await manager.is_server_healthy(timeout=2.0)
        return healthy

    healthy = asyncio.run(_check())

    table = Table(title="Pokémon Showdown Server Status", show_header=True)
    table.add_column("Property", style="bold")
    table.add_column("Value", style="cyan")

    table.add_row("Process State", "[green]Running[/green]" if pid else "[red]Stopped[/red]")
    table.add_row("PID", str(pid) if pid else "None")
    table.add_row("WebSocket URL", manager.config.websocket_url)
    table.add_row("Health Check", "[green]Online & Ready[/green]" if healthy else "[yellow]Unreachable[/yellow]")

    console.print(table)


# ---------------------------------------------------------------------
# Teams Commands
# ---------------------------------------------------------------------


@teams_app.command("list")
def teams_list():
    """List all available Gen 9 OU sample and custom teams."""
    teams = list_available_teams()
    if not teams:
        console.print("[yellow]No team files found in data/teams.[/yellow]")
        return

    table = Table(title="Available Gen 9 OU Teams", show_header=True)
    table.add_column("Team Name", style="bold cyan")
    table.add_column("File Path", style="dim")
    table.add_column("Members", style="green")

    for t_path in teams:
        try:
            team = load_team_file(t_path)
            species_list = ", ".join(m.species for m in team.members)
            table.add_row(team.name, str(t_path), species_list)
        except Exception as e:
            table.add_row(t_path.stem, str(t_path), f"[red]Error: {e}[/red]")

    console.print(table)


@teams_app.command("show")
def teams_show(team_name: str = typer.Argument(..., help="Team name or path")):
    """Show details and export format for a team."""
    try:
        team = load_preset_team(team_name)
        console.print(Panel(team.to_smogon_text(), title=f"Team: {team.name}", expand=False))
    except Exception as e:
        console.print(f"[bold red]Error loading team:[/bold red] {e}")
        raise typer.Exit(1)


@teams_app.command("validate")
def teams_validate(file_path: str = typer.Argument(..., help="Path to team .txt file")):
    """Validate a Smogon format team file."""
    p = Path(file_path)
    if not p.exists():
        console.print(f"[bold red]File not found: {p}[/bold red]")
        raise typer.Exit(1)

    try:
        team = load_team_file(p)
        if team.is_valid:
            console.print(f"[bold green][OK] Team '{team.name}' is valid with {len(team.members)} Pokemon.[/bold green]")
            for m in team.members:
                console.print(f"  - [cyan]{m.species}[/cyan] ({', '.join(m.moves)})")
        else:
            console.print(f"[bold red][ERROR] Team has {len(team.members)} Pokemon (must be 1-6).[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Validation error:[/bold red] {e}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------
# Replay Commands
# ---------------------------------------------------------------------


@replay_app.command("list")
def replay_list(output_dir: str = typer.Option("./runs", "--dir", "-d")):
    """List recent match runs and replays."""
    p = Path(output_dir)
    if not p.exists():
        console.print("[yellow]No runs directory found.[/yellow]")
        return

    matches = sorted([d for d in p.iterdir() if d.is_dir()], reverse=True)
    if not matches:
        console.print("[yellow]No recorded matches found.[/yellow]")
        return

    table = Table(title="Recent RotomArena Match Runs", show_header=True)
    table.add_column("Match ID", style="bold cyan")
    table.add_column("Replay HTML", style="green")
    table.add_column("Breadcrumbs JSON", style="yellow")
    table.add_column("Report MD", style="magenta")

    for m in matches[:15]:
        has_html = "Yes" if (m / "replay.html").exists() else "-"
        has_json = "Yes" if (m / "breadcrumbs.json").exists() else "-"
        has_md = "Yes" if (m / "report.md").exists() else "-"
        table.add_row(m.name, has_html, has_json, has_md)

    console.print(table)


# ---------------------------------------------------------------------
# Battle & Tournament Commands
# ---------------------------------------------------------------------


@app.command("battle")
def run_battle(
    p1: str = typer.Option("pokechamp", "--p1", help="Player 1 agent type (pokechamp, direct_llm, heuristic, random)"),
    p2: str = typer.Option("heuristic", "--p2", help="Player 2 agent type"),
    p1_provider: Optional[str] = typer.Option(None, "--p1-provider", help="LLM Provider for Player 1 (gemini, openrouter, ollama)"),
    p1_model: Optional[str] = typer.Option(None, "--p1-model", help="LLM Model for Player 1"),
    p1_depth: int = typer.Option(1, "--p1-depth", help="Minimax depth for Player 1 (PokéChamp)"),
    p1_llm_prior: bool = typer.Option(False, "--p1-llm-prior", help="Enable LLM value prior for P1 PokéChamp"),
    p2_provider: Optional[str] = typer.Option(None, "--p2-provider", help="LLM Provider for Player 2 (gemini, openrouter, ollama)"),
    p2_model: Optional[str] = typer.Option(None, "--p2-model", help="LLM Model for Player 2"),
    p2_depth: int = typer.Option(1, "--p2-depth", help="Minimax depth for Player 2 (PokéChamp)"),
    p2_llm_prior: bool = typer.Option(False, "--p2-llm-prior", help="Enable LLM value prior for P2 PokéChamp"),
    team1: str = typer.Option("balance", "--team1", help="Team for Player 1"),
    team2: str = typer.Option("hyper_offense", "--team2", help="Team for Player 2"),
    games: int = typer.Option(1, "--games", "-n", help="Number of games in series"),
    turn_timeout: float = typer.Option(120.0, "--turn-timeout", "-t", help="Per-turn decision timer in seconds (default: 120s)"),
    bank_timeout: float = typer.Option(900.0, "--bank-timeout", "-b", help="Total match chess-clock bank in seconds (default: 900s / 15 min)"),
    provider: str = typer.Option("gemini", "--provider", help="Default LLM Provider if not specified per player"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Default LLM Model override if not specified per player"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
):
    """Run a 1v1 battle series between two configured AI agents."""
    app_cfg = AppConfig.load_from_yaml(config_file) if config_file else AppConfig.default_config()

    # Load teams
    t1 = load_preset_team(team1).to_showdown_packed()
    t2 = load_preset_team(team2).to_showdown_packed()

    # Configure agents
    p1_cfg = AgentConfig(
        name=f"{p1}_p1",
        type=p1,
        depth=p1_depth,
        use_llm_prior=p1_llm_prior,
        provider=p1_provider or provider,
        model=p1_model or model,
        turn_timeout=turn_timeout,
        bank_timeout=bank_timeout,
    )
    p2_cfg = AgentConfig(
        name=f"{p2}_p2",
        type=p2,
        depth=p2_depth,
        use_llm_prior=p2_llm_prior,
        provider=p2_provider or provider,
        model=p2_model or model,
        turn_timeout=turn_timeout,
        bank_timeout=bank_timeout,
    )

    server_mgr = ShowdownServerManager(app_cfg.server)
    runner = MatchRunner(telemetry_config=app_cfg.telemetry)

    async def _execute():
        async with server_mgr.ensure_running():
            player_1 = create_agent_instance(p1_cfg, app_cfg, team_str=t1)
            player_2 = create_agent_instance(p2_cfg, app_cfg, team_str=t2)

            console.rule(f"[bold cyan]1v1 Matchup: {player_1.agent_name} vs {player_2.agent_name}[/bold cyan]")
            series_res = await runner.run_series(player_1, player_2, n_games=games)

            console.print("\n[bold green]=== Series Finished ===[/bold green]")
            console.print(f"{player_1.agent_name} Wins: [bold cyan]{series_res.p1_wins}[/bold cyan] ({series_res.p1_win_rate}%)")
            console.print(f"{player_2.agent_name} Wins: [bold magenta]{series_res.p2_wins}[/bold magenta] ({series_res.p2_win_rate}%)")
            console.print(f"Draws: {series_res.draws}")
            if series_res.matches:
                latest = series_res.matches[-1]
                console.print(f"\nArtifacts saved in run folder:")
                if latest.replay_html_path:
                    console.print(f"  - Replay HTML: [cyan]{latest.replay_html_path}[/cyan]")
                if latest.breadcrumbs_json_path:
                    console.print(f"  - Telemetry: [cyan]{latest.breadcrumbs_json_path}[/cyan]")
                if latest.report_md_path:
                    console.print(f"  - Report: [cyan]{latest.report_md_path}[/cyan]")

    asyncio.run(_execute())


@app.command("tournament")
def run_tournament(
    config_file: str = typer.Option("config.yaml", "--config", "-c", help="Path to tournament config.yaml"),
):
    """Run an automated round-robin tournament bracket."""
    app_cfg = AppConfig.load_from_yaml(config_file)
    server_mgr = ShowdownServerManager(app_cfg.server)
    orchestrator = TournamentOrchestrator(app_cfg)

    async def _exec():
        async with server_mgr.ensure_running():
            await orchestrator.run_tournament()

    asyncio.run(_exec())


if __name__ == "__main__":
    app()
