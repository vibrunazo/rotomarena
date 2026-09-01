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
commentary_app = typer.Typer(help="Generate and inspect play-by-play battle commentary")

app.add_typer(server_app, name="server")
app.add_typer(teams_app, name="teams")
app.add_typer(replay_app, name="replay")
app.add_typer(commentary_app, name="commentary")

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
def replay_list(
    limit: int = typer.Option(15, "--limit", "-n", help="Number of recent matches to show"),
    output_dir: str = typer.Option("./runs", "--dir", "-d", help="Directory containing match runs"),
):
    """List recent match runs and replays."""
    p = Path(output_dir)
    if not p.exists():
        console.print("[yellow]No runs directory found.[/yellow]")
        return

    matches = sorted([d for d in p.iterdir() if d.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
    if not matches:
        console.print("[yellow]No recorded matches found.[/yellow]")
        return

    table = Table(title="Recent RotomArena Match Runs", show_header=True)
    table.add_column("Match ID", style="bold cyan")
    table.add_column("Replay HTML", style="green")
    table.add_column("Breadcrumbs JSON", style="yellow")
    table.add_column("Report MD", style="magenta")

    for m in matches[:limit]:
        has_html = "[green]Yes[/green]" if (m / "replay.html").exists() else "[dim]-[/dim]"
        has_json = "[green]Yes[/green]" if (m / "breadcrumbs.json").exists() else "[dim]-[/dim]"
        has_md = "[green]Yes[/green]" if (m / "report.md").exists() else "[dim]-[/dim]"
        table.add_row(m.name, has_html, has_json, has_md)

    console.print(table)


@replay_app.command("open")
def replay_open(
    match: Optional[str] = typer.Argument(None, help="Match folder name or partial match ID (defaults to latest match)"),
    output_dir: str = typer.Option("./runs", "--dir", "-d", help="Directory containing match runs"),
):
    """Open an animated battle replay HTML in your default browser."""
    import webbrowser
    p = Path(output_dir)
    if not p.exists():
        console.print("[red]No runs directory found.[/red]")
        return

    matches = sorted([d for d in p.iterdir() if d.is_dir() and (d / "replay.html").exists()], key=lambda x: x.stat().st_mtime, reverse=True)
    if not matches:
        console.print("[yellow]No match replays with replay.html found in runs/.[/yellow]")
        return

    target_match = None
    if not match:
        target_match = matches[0]
    else:
        for m in matches:
            if match.lower() in m.name.lower():
                target_match = m
                break

    if not target_match:
        console.print(f"[red]Could not find match matching: {match}[/red]")
        return

    replay_file = target_match / "replay.html"
    console.print(f"[bold green]Opening animated replay:[/bold green] [cyan]{replay_file}[/cyan]")
    webbrowser.open(replay_file.resolve().as_uri())


@replay_app.command("refresh")
def replay_refresh(output_dir: str = typer.Option("./runs", "--dir", "-d", help="Directory containing match runs")):
    """Re-render all replay.html files across the runs/ folder with the embedded animated player."""
    from rotomarena.telemetry.replay_saver import save_battle_replay_html
    import json

    p = Path(output_dir)
    if not p.exists():
        console.print("[yellow]No runs directory found.[/yellow]")
        return

    matches = [d for d in p.iterdir() if d.is_dir()]
    updated = 0
    for match_dir in matches:
        log_file = match_dir / "battle_log.json"
        if not log_file.exists():
            continue
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
            raw_logs = data.get("raw_logs", [])
            meta = data.get("metadata", {})
            match_id = data.get("match_id", match_dir.name)
            p1 = "Player 1"
            p2 = "Player 2"
            for line in raw_logs:
                if isinstance(line, (list, tuple)) and len(line) >= 4 and line[1] == "player":
                    if line[2] == "p1": p1 = line[3]
                    elif line[2] == "p2": p2 = line[3]
                elif isinstance(line, str) and line.startswith("|player|"):
                    parts = line.split("|")
                    if len(parts) >= 4:
                        if parts[2] == "p1": p1 = parts[3]
                        elif parts[2] == "p2": p2 = parts[3]

            save_battle_replay_html(
                match_id=match_id,
                player_1=p1,
                player_2=p2,
                winner=meta.get("winner"),
                total_turns=meta.get("turns", 0),
                duration_seconds=meta.get("duration_seconds", 0.0),
                raw_logs=raw_logs,
                output_path=match_dir / "replay.html",
            )
            updated += 1
        except Exception as e:
            console.print(f"[red]Error updating {match_dir.name}: {e}[/red]")

    console.print(f"[bold green]Successfully refreshed {updated} replay.html files with the embedded animated player![/bold green]")


# ---------------------------------------------------------------------
# Commentary Commands
# ---------------------------------------------------------------------


@commentary_app.command("generate")
def commentary_generate(
    match: Optional[str] = typer.Argument(None, help="Match folder name or partial match ID (defaults to latest match)"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM Provider (gemini, openrouter, ollama)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM Model"),
    output_dir: str = typer.Option("./runs", "--dir", "-d", help="Directory containing match runs"),
):
    """Generate or re-generate play-by-play LLM commentary for a battle."""
    import json
    from rotomarena.commentary.generator import CommentaryGenerator
    from rotomarena.llm.client import LLMClient
    from rotomarena.telemetry.replay_saver import save_battle_replay_html

    p = Path(output_dir)
    if not p.exists():
        console.print("[red]No runs directory found.[/red]")
        return

    matches = sorted([d for d in p.iterdir() if d.is_dir() and (d / "battle_log.json").exists()], key=lambda x: x.stat().st_mtime, reverse=True)
    if not matches:
        console.print("[yellow]No match directories with battle_log.json found in runs/.[/yellow]")
        return

    target_match = None
    if not match:
        target_match = matches[0]
    else:
        for m in matches:
            if match.lower() in m.name.lower():
                target_match = m
                break

    if not target_match:
        console.print(f"[red]Could not find match matching: {match}[/red]")
        return

    console.print(f"[cyan]Generating play-by-play commentary for [bold]{target_match.name}[/bold]...[/cyan]")

    log_data = json.loads((target_match / "battle_log.json").read_text(encoding="utf-8"))
    raw_logs = log_data.get("raw_logs", [])
    meta = log_data.get("metadata", {})
    match_id = log_data.get("match_id", target_match.name)

    p1 = "Player 1"
    p2 = "Player 2"
    for line in raw_logs:
        if isinstance(line, (list, tuple)) and len(line) >= 4 and line[1] == "player":
            if line[2] == "p1": p1 = line[3]
            elif line[2] == "p2": p2 = line[3]
        elif isinstance(line, str) and line.startswith("|player|"):
            parts = line.split("|")
            if len(parts) >= 4:
                if parts[2] == "p1": p1 = parts[3]
                elif parts[2] == "p2": p2 = parts[3]

    breadcrumbs = None
    b_file = target_match / "breadcrumbs.json"
    if b_file.exists():
        try:
            b_data = json.loads(b_file.read_text(encoding="utf-8"))
            breadcrumbs = b_data.get("breadcrumbs", [])
        except Exception:
            pass

    client = None
    if provider or model:
        client = LLMClient(
            base_url="https://openrouter.ai/api/v1" if provider == "openrouter" else None,
            default_model=model,
            provider_name=provider,
        )

    generator = CommentaryGenerator(llm_client=client)

    async def _run():
        commentary = await generator.generate_commentary(
            raw_logs=raw_logs,
            p1_name=p1,
            p2_name=p2,
            match_id=match_id,
            winner=meta.get("winner"),
            total_turns=meta.get("turns", 0),
            breadcrumbs=breadcrumbs,
        )

        comm_file = target_match / "commentary.json"
        comm_file.write_text(commentary.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[bold green]Saved commentary JSON:[/bold green] [cyan]{comm_file}[/cyan]")

        # Refresh replay.html with embedded commentary
        save_battle_replay_html(
            match_id=match_id,
            player_1=p1,
            player_2=p2,
            winner=meta.get("winner"),
            total_turns=meta.get("turns", 0),
            duration_seconds=meta.get("duration_seconds", 0.0),
            raw_logs=raw_logs,
            output_path=target_match / "replay.html",
            commentary=commentary,
        )
        console.print(f"[bold green]Updated animated replay with TTS:[/bold green] [cyan]{target_match / 'replay.html'}[/cyan]")

    asyncio.run(_run())


@commentary_app.command("view")
def commentary_view(
    match: Optional[str] = typer.Argument(None, help="Match folder name (defaults to latest)"),
    output_dir: str = typer.Option("./runs", "--dir", "-d", help="Directory containing match runs"),
):
    """View play-by-play commentary for a match in terminal."""
    import json
    p = Path(output_dir)
    matches = sorted([d for d in p.iterdir() if d.is_dir() and (d / "commentary.json").exists()], key=lambda x: x.stat().st_mtime, reverse=True)
    if not matches:
        console.print("[yellow]No commentary.json found in runs/. Run 'rotomarena commentary generate' first.[/yellow]")
        return

    target_match = None
    if not match:
        target_match = matches[0]
    else:
        for m in matches:
            if match.lower() in m.name.lower():
                target_match = m
                break

    if not target_match:
        console.print(f"[red]Could not find match with commentary matching: {match}[/red]")
        return

    data = json.loads((target_match / "commentary.json").read_text(encoding="utf-8"))
    console.rule(f"[bold cyan]🎙️ Commentary: {data.get('match_id')}[/bold cyan]")
    for turn in data.get("turns", []):
        t_num = turn.get("turn", 0)
        title = turn.get("title", f"Turn {t_num}")
        text = turn.get("commentary", "")
        console.print(f"\n[bold yellow]{title}[/bold yellow]")
        console.print(f"[white]{text}[/white]")


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
    commentary: bool = typer.Option(False, "--commentary", help="Auto-generate play-by-play LLM commentary after match"),
    provider: str = typer.Option("gemini", "--provider", help="Default LLM Provider if not specified per player"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Default LLM Model override if not specified per player"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
):
    """Run a 1v1 battle series between two configured AI agents."""
    app_cfg = AppConfig.load_from_yaml(config_file) if config_file else AppConfig.default_config()
    if commentary:
        app_cfg.telemetry.generate_commentary = True

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
                if latest.commentary_json_path:
                    console.print(f"  - Commentary: [cyan]{latest.commentary_json_path}[/cyan]")

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
