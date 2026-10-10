"""RotomArena CLI Application."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import List, Optional
import typer
from pydantic import ValidationError
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

from rotomarena.agents.factory import create_players, resolved_model
from rotomarena import local_servers
from rotomarena.config import AgentConfig, AppConfig
from rotomarena.matchmaker.runner import MatchRunner
from rotomarena.server.manager import ShowdownServerManager
from rotomarena.teams.loader import load_team_file
from rotomarena.rulesets import RulesChanged, current_rules, register
from rotomarena.teams.presets import list_available_teams, load_preset_team

app = typer.Typer(
    name="rotomarena",
    help="RotomArena: Local Pokemon AI Battle Benchmarking Testbed for Gen 9 OU",
    add_completion=False,
)
server_app = typer.Typer(help="Manage local Pokemon Showdown server")
teams_app = typer.Typer(help="Inspect and manage Gen 9 OU teams")
replay_app = typer.Typer(help="Inspect and view battle replays and telemetry")
ladder_app = typer.Typer(help="Season ratings, placement and top-up games")

app.add_typer(server_app, name="server")
app.add_typer(teams_app, name="teams")
app.add_typer(replay_app, name="replay")
app.add_typer(ladder_app, name="ladder")

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


@teams_app.command("draft")
def teams_draft(
    config_ids: List[str] = typer.Argument(..., help="Registry entries that build their own team"),
    attempts: int = typer.Option(5, "--attempts", "-a", help="Tries, with Showdown's validator messages fed back; "
                                 "after the last, the team is repaired with middling replacements"),
    config_file: str = typer.Option("config.yaml", "--config", "-c", help="Config file"),
    version: Optional[str] = typer.Option(None, "--version", help="Ruleset version to play (default: play in the config)"),
    keep_picks: bool = typer.Option(False, "--keep-picks", help="Keep each model's six picks from its current draft "
                                    "and redo only the sets (when the harness, not the model, spoiled them)"),
):
    """Each model builds its own Gen 9 OU team from the format's rules; Showdown's validator referees.
    Saves every attempt to data/drafts/<format>/<config id>.json."""
    from rotomarena.teams.draft import DraftUnavailable, draft_team, load_drafts, save_draft
    from rotomarena.teams.draft_decisions import draft_team_by_decisions

    app_cfg = AppConfig.load(config_file).playing(version)
    agents = [app_cfg.agents[c] for c in config_ids if c in app_cfg.agents]
    unknown = [c for c in config_ids if c not in app_cfg.agents]
    if unknown:
        console.print(f"[bold red]Not in the registry: {', '.join(unknown)}[/bold red]")
        raise typer.Exit(1)
    local = local_servers.local_agents(agents)
    if local and app_cfg.local_llm.manage:
        # Local servers are shared with ladder runs: starting ours would stop theirs mid-game.
        others = {port: m for port, m in local_servers.running(app_cfg).items() if port not in {a.port for a in local}}
        if others:
            console.print(f"[bold red]Other local servers are running ({', '.join(others.values())}); a ladder run may be "
                          "using them. Draft local models when it is idle.[/bold red]")
            raise typer.Exit(1)

    async def _run():
        for agent in agents:
            console.print(f"[bold cyan]{agent.name}[/bold cyan] drafting")
            if agent in local:
                local_servers.prepare([agent], app_cfg, log=console.print)
            try:
                if agent.type == "decision":
                    record = await draft_team_by_decisions(agent, app_cfg, attempts=attempts, log=console.print)
                else:
                    earlier = load_drafts(version=app_cfg.ruleset.version, fmt=app_cfg.ruleset.format).get(agent.name) if keep_picks else None
                    record = await draft_team(agent, app_cfg, attempts=attempts, log=console.print,
                                              keep_picks=earlier["picks"] if earlier else None)
            except DraftUnavailable as e:
                console.print(f"  [red]no draft kept[/red] ({e}); run it again when the provider is back")
                continue
            path = save_draft(record)
            verdict = "[green]legal[/green]" if record["legal"] else f"[yellow]repaired ({len(record['repairs'])} changes)[/yellow]"
            console.print(f"  {verdict} after {len(record['attempts'])} attempt(s) -> {path}")

    asyncio.run(_run())
    if local and app_cfg.local_llm.manage:
        for agent in local:
            local_servers.stop(app_cfg, agent.port)


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
    match: Optional[List[str]] = typer.Argument(None, help="Match folder name or partial match ID (defaults to latest match)"),
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
        match_str = " ".join(match).lower()
        for m in matches:
            if match_str in m.name.lower() or all(token.lower() in m.name.lower() for token in match):
                target_match = m
                break

    if not target_match:
        console.print(f"[red]Could not find match matching: {' '.join(match or [])}[/red]")
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
# Battle Commands
# ---------------------------------------------------------------------


def _agent_config(app_cfg: AppConfig, choice: str, provider: str, model: Optional[str]) -> AgentConfig:
    """`choice` is a config id from the agents registry or a bare agent type. A bare type reuses the
    registry entry for the same bot or the same provider and model, so its games count toward that rating."""
    if choice in app_cfg.agents:
        return app_cfg.agents[choice]
    try:
        cfg = AgentConfig(name=choice, type=choice, provider=provider, model=model)
    except ValidationError:
        known = ", ".join(sorted(app_cfg.agents)) or "none"
        console.print(
            f"[bold red]Unknown player '{choice}'.[/bold red] Use an agent type "
            f"(pokechamp, direct_llm, heuristic, max_damage, random) or a config id ({known})."
        )
        raise typer.Exit(1)
    target_model = resolved_model(cfg, app_cfg)
    for entry in app_cfg.agents.values():
        if entry.type == cfg.type and (
            cfg.type != "direct_llm"
            or (entry.provider == cfg.provider and resolved_model(entry, app_cfg) == target_model)
        ):
            return entry
    if cfg.type == "direct_llm":
        cfg.name = re.sub(r"[^a-z0-9]+", "_", f"{cfg.provider}_{target_model}".lower()).strip("_")
    return cfg


@app.command("battle")
def run_battle(
    p1: str = typer.Option("pokechamp", "--p1", help="Player 1: agent type (pokechamp, direct_llm, heuristic, max_damage, random) or config id"),
    p2: str = typer.Option("heuristic", "--p2", help="Player 2: agent type or config id"),
    p1_provider: Optional[str] = typer.Option(None, "--p1-provider", help="LLM provider for player 1 (openrouter, local, gemini, ollama, vllm)"),
    p1_model: Optional[str] = typer.Option(None, "--p1-model", help="LLM model for player 1"),
    p2_provider: Optional[str] = typer.Option(None, "--p2-provider", help="LLM provider for player 2"),
    p2_model: Optional[str] = typer.Option(None, "--p2-model", help="LLM model for player 2"),
    team1: str = typer.Option("balance", "--team1", help="First team of the series"),
    team2: str = typer.Option("hyper_offense", "--team2", help="Second team of the series"),
    games: int = typer.Option(1, "--games", "-n", help="Games in the series; sides alternate every game, teams every two"),
    provider: str = typer.Option("openrouter", "--provider", help="LLM provider when not set per player"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM model when not set per player (default: the provider's)"),
    config_file: str = typer.Option("config.yaml", "--config", "-c", help="Config file with the agents registry"),
):
    """Run a 1v1 battle series between two agents."""
    app_cfg = AppConfig.load(config_file)

    random_teams = app_cfg.ruleset.team_mode == "random"  # the format deals the teams
    first_team = None if random_teams else load_preset_team(team1)
    second_team = None if random_teams else load_preset_team(team2)
    p1_cfg = _agent_config(app_cfg, p1, p1_provider or provider, p1_model or model)
    p2_cfg = _agent_config(app_cfg, p2, p2_provider or provider, p2_model or model)

    server_mgr = ShowdownServerManager(app_cfg.server)
    runner = MatchRunner(telemetry_config=app_cfg.telemetry, rules=current_rules(app_cfg))

    async def _execute():
        async with server_mgr.ensure_running():
            player_1, player_2 = create_players(p1_cfg, p2_cfg, app_cfg)
            console.rule(f"[bold cyan]1v1 Matchup: {player_1.agent_name} vs {player_2.agent_name}[/bold cyan]")
            series_res = await runner.run_series(
                player_1, player_2, first_team, second_team, n_games=games,
                before_game=lambda: local_servers.prepare([p1_cfg, p2_cfg], app_cfg, log=console.print),
            )

            console.print("\n[bold green]=== Series Finished ===[/bold green]")
            console.print(f"{player_1.agent_name} Wins: [bold cyan]{series_res.a_wins}[/bold cyan] ({series_res.a_win_rate}%)")
            console.print(f"{player_2.agent_name} Wins: [bold magenta]{series_res.b_wins}[/bold magenta] ({series_res.b_win_rate}%)")
            console.print(f"Draws: {series_res.draws}")
            if series_res.matches:
                latest = series_res.matches[-1]
                console.print("\nArtifacts saved in run folder:")
                if latest.replay_html_path:
                    console.print(f"  - Replay HTML: [cyan]{latest.replay_html_path}[/cyan]")
                if latest.breadcrumbs_json_path:
                    console.print(f"  - Telemetry: [cyan]{latest.breadcrumbs_json_path}[/cyan]")
                if latest.report_md_path:
                    console.print(f"  - Report: [cyan]{latest.report_md_path}[/cyan]")

    with local_servers.session(app_cfg):
        asyncio.run(_execute())


# ---------------------------------------------------------------------
# Ladder & Site Export
# ---------------------------------------------------------------------


def _print_ratings(app_cfg: AppConfig) -> None:
    from rotomarena.ladder import describe_void_matches, version_state

    state = version_state(app_cfg)
    table = Table(title=f"RotomArena ladder, version {app_cfg.ruleset.version}", show_header=True)
    for col, justify in (("Rank", "right"), ("Config id", "left"), ("Rating", "right"), ("95% CI", "right"),
                         ("Games", "right"), ("W-L-D", "center"), ("", "left")):
        table.add_column(col, justify=justify)
    ordered = sorted(state.ratings.values(), key=lambda r: (r.rating is None, -(r.rating or 0)))
    rank = 0
    for r in ordered:
        role = app_cfg.agents[r.config_id].role if r.config_id in app_cfg.agents else "not in registry"
        notes = [role] if role != "contestant" else []
        if r.games < app_cfg.ladder.provisional_games:
            notes.append("provisional")
        if r.ranked:
            rank += 1
        table.add_row(
            str(rank) if r.ranked else "-",
            r.config_id,
            f"{r.rating:.0f}" if r.ranked else "unranked",
            "fixed" if r.config_id == app_cfg.ladder.anchor else (f"{r.ci_low:.0f} to {r.ci_high:.0f}" if r.ranked else ""),
            str(r.games),
            f"{r.wins}-{r.losses}-{r.draws}",
            ", ".join(notes),
        )
    console.print(table)
    console.print(f"{len(state.outcomes)} rated matches, {state.void_count} void.")
    for match_id, reason in describe_void_matches(state, app_cfg.ladder.max_autopilot):
        console.print(f"  [dim]void: {match_id} ({reason})[/dim]")


@ladder_app.command("status")
def ladder_status(config_file: str = typer.Option("config.yaml", "--config", "-c", help="Config file")):
    """Show the ratings of the ruleset version being played."""
    _print_ratings(AppConfig.load(config_file))


@ladder_app.command("place")
def ladder_place(
    config_id: str = typer.Argument(..., help="Registry entry to place (from the agents block)"),
    with_control: bool = typer.Option(False, "--with-control", help="Play the control games even for an expensive model"),
    config_file: str = typer.Option("config.yaml", "--config", "-c", help="Config file"),
):
    """Play a model's placement games: a set against each anchor, a sparring partner and the closest-rated LLM.
    Resumes where an interrupted placement stopped."""
    from rotomarena.ladder import RunHalted, place

    app_cfg = AppConfig.load(config_file)
    _register_rules(app_cfg)
    server_mgr = ShowdownServerManager(app_cfg.server)

    async def _run():
        async with server_mgr.ensure_running():
            await place(config_id, app_cfg, log=console.print, with_control=with_control)

    try:
        with local_servers.session(app_cfg):
            asyncio.run(_run())
    except RunHalted as e:
        _report_halt(e, app_cfg)
    except ValueError as e:
        console.print(f"[bold red]{e}[/bold red]")
        raise typer.Exit(1)
    _print_ratings(app_cfg)


def _register_rules(app_cfg: AppConfig) -> None:
    """Stores this version's rules on its first run; refuses to play under changed rules (see rulesets.py)."""
    try:
        register(app_cfg)
    except RulesChanged as e:
        console.print(f"[bold red]{e}[/bold red]")
        raise typer.Exit(1)


def _report_halt(e: Exception, app_cfg: AppConfig) -> None:
    """Prints why a ladder run stopped, then the ratings, and exits with status 3, or 4 for a stall (which the run
    monitor's driver restarts by itself)."""
    import datetime

    from rotomarena.ladder import RunStalled

    stalled = isinstance(e, RunStalled)
    console.print(f"[bold red]{datetime.datetime.now():%Y-%m-%d %H:%M} RUN {'STALLED' if stalled else 'HALTED'}: {e}[/bold red]")
    if stalled:
        console.print("Run the same command again: it resumes, replaying the stuck games (the run monitor does this itself).")
        raise typer.Exit(4)
    console.print("Fix the cause (credits, quota, a broken model), then run the same command again: it resumes.")
    _print_ratings(app_cfg)
    raise typer.Exit(3)


def _wait_for_idle_cpu(threshold: int = 25, quiet_minutes: int = 5) -> None:
    """Blocks until the CPU load has stayed under `threshold`% for `quiet_minutes` checks a minute apart."""
    import time

    quiet = 0
    while quiet < quiet_minutes:
        load = local_servers.cpu_load()
        quiet = quiet + 1 if load is not None and load < threshold else 0
        console.print(f"[dim]{time.strftime('%H:%M')} CPU {load}% (quiet {quiet}/{quiet_minutes} min)[/dim]")
        if quiet < quiet_minutes:
            time.sleep(60)


@ladder_app.command("place-all")
def ladder_place_all(
    config_ids: List[str] = typer.Argument(..., help="Registry entries to place, in this order"),
    wait_idle: bool = typer.Option(False, "--wait-idle", help="Start only after the CPU has been under 25% for 5 minutes"),
    config_file: str = typer.Option("config.yaml", "--config", "-c", help="Config file"),
):
    """Place several models one after another (an unattended run). Each placement resumes where it stopped.
    A broken model is logged and skipped so the rest still run; a provider limit or repeated void games stop
    the whole run."""
    import datetime
    from rotomarena.ladder import RunHalted, place

    app_cfg = AppConfig.load(config_file)
    _register_rules(app_cfg)
    unknown = [c for c in config_ids if c not in app_cfg.agents]
    if unknown:
        console.print(f"[bold red]Not in the registry: {', '.join(unknown)}[/bold red]")
        raise typer.Exit(1)
    if wait_idle:
        _wait_for_idle_cpu()
    for config_id in config_ids:
        console.rule(f"[bold cyan]{datetime.datetime.now():%Y-%m-%d %H:%M} placing {config_id}[/bold cyan]")
        server_mgr = ShowdownServerManager(app_cfg.server)

        async def _run():
            async with server_mgr.ensure_running():
                await place(config_id, app_cfg, log=console.print)

        try:
            with local_servers.session(app_cfg):
                asyncio.run(_run())
        except RunHalted as e:
            _report_halt(e, app_cfg)
        except Exception as e:  # keep going: one broken model shouldn't stop a weekend run
            console.print(f"[bold red]Placement of {config_id} failed: {e}[/bold red]")
    console.rule(f"[bold green]{datetime.datetime.now():%Y-%m-%d %H:%M} all placements done[/bold green]")
    _print_ratings(app_cfg)


@ladder_app.command("round-robin")
def ladder_round_robin(
    games_per_pair: int = typer.Option(3, "--games-per-pair", "-g", help="Games each pair plays, sides alternating"),
    config_file: str = typer.Option("config.yaml", "--config", "-c", help="Config file"),
    version: Optional[str] = typer.Option(None, "--version", help="Ruleset version to play (default: play in the config)"),
):
    """Every language model plays every other one, pair by pair in balanced rounds (a pair's games run at once),
    so a run stopped early still covers every model evenly. Resumes where it stopped."""
    from rotomarena.ladder import RunHalted, round_robin, watchdog

    app_cfg = AppConfig.load(config_file).playing(version)
    _register_rules(app_cfg)
    watchdog(app_cfg, app_cfg.ladder.stall_minutes + 10)  # the backstop when the event loop itself hangs
    server_mgr = ShowdownServerManager(app_cfg.server)

    async def _run():
        async with server_mgr.ensure_running():
            await round_robin(app_cfg, games_per_pair, log=console.print)

    try:
        with local_servers.session(app_cfg):
            asyncio.run(_run())
    except RunHalted as e:
        _report_halt(e, app_cfg)
    _print_ratings(app_cfg)


@ladder_app.command("fill")
def ladder_fill(
    budget: int = typer.Option(8, "--budget", "-b", help="Maximum games to play"),
    include_paid: bool = typer.Option(False, "--include-paid", help="Also schedule paid API models"),
    config_file: str = typer.Option("config.yaml", "--config", "-c", help="Config file"),
):
    """Play extra games between neighbouring models whose ratings still overlap."""
    from rotomarena.ladder import RunHalted, fill

    app_cfg = AppConfig.load(config_file)
    _register_rules(app_cfg)
    server_mgr = ShowdownServerManager(app_cfg.server)

    async def _run():
        async with server_mgr.ensure_running():
            await fill(app_cfg, budget, free_only=not include_paid, log=console.print)

    try:
        with local_servers.session(app_cfg):
            asyncio.run(_run())
    except RunHalted as e:
        _report_halt(e, app_cfg)
    _print_ratings(app_cfg)


@app.command("dashboard")
def dashboard(
    host: str = typer.Option("0.0.0.0", "--host", help="Address to listen on (0.0.0.0: every device on the LAN)"),
    port: int = typer.Option(8765, "--port", "-p", help="Port to listen on"),
    config_file: str = typer.Option("config.yaml", "--config", "-c", help="Config file"),
):
    """A read-only web page with the round robin's progress, the games being played, finish time and spending."""
    from rotomarena.dashboard.server import serve

    console.print(f"[cyan]Run monitor on http://{host}:{port}/ (Ctrl+C stops it)[/cyan]")
    serve(config_file, host, port)


@app.command("export-site")
def export_site_command(
    out: str = typer.Option("site/src/data", "--out", "-o", help="Output directory for the site's JSON"),
    config_file: str = typer.Option("config.yaml", "--config", "-c", help="Config file"),
):
    """Export every benchmark's games and ratings, and the retracted v0 archive, as JSON for the website."""
    from rotomarena.export.site import export_site

    counts = export_site(AppConfig.load(config_file), out)
    console.print(
        f"[bold green]Exported[/bold green] {counts['models']} models, {counts['matches']} matches "
        f"({counts['rated']} rated, {counts['void']} void) and {counts['retracted']} retracted matches to [cyan]{out}[/cyan]"
    )


if __name__ == "__main__":
    app()
