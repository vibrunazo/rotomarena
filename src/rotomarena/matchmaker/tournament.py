"""Round-Robin Tournament Bracket Orchestrator."""

from __future__ import annotations

import itertools
import re
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


def clean_llm_model_name(model_str: str) -> str:
    """Extracts a concise, distinct model name (max ~13 chars) capturing family, version, and variant."""
    if not model_str:
        return "Direct LLM"

    # Strip provider prefix (e.g., 'google/', 'meta-llama/', 'nvidia/') and tag suffixes (':free', ':beta')
    raw = model_str.split(":")[0].strip()
    if "/" in raw:
        raw = raw.split("/")[-1]

    # Convert dashed version numbers (e.g. claude-3-7 -> claude-3.7, llama-3-3 -> llama-3.3)
    s = re.sub(r"(\d+)-(\d+)", r"\1.\2", raw)
    # Replace underscores/hyphens with spaces
    s = re.sub(r"[-_]+", " ", s).strip()
    lower_s = s.lower()

    # 1. Gemini (e.g., gemini-3.8-flash, gemini-3.7-pro, gemini-2.5, gemini-1.5-flash)
    if "gemini" in lower_s:
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        var = ""
        if "pro" in lower_s:
            var = " Pro"
        elif "ultra" in lower_s:
            var = " Ultra"
        elif "flash" in lower_s:
            var = " Flash"
        elif "exp" in lower_s:
            var = " Exp"
        res = f"Gemini{ver}{var}".strip()
        if len(res) <= 18:
            return res
        return f"Gem{ver}{var}"[:18].strip()

    # 2. Claude (e.g., claude-3.7-sonnet, claude-3.5-haiku, claude-opus)
    if "claude" in lower_s:
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        var = ""
        for opt in ["sonnet", "haiku", "opus"]:
            if opt in lower_s:
                var = f" {opt.title()}"
                break
        res = f"Claude{ver}{var}".strip()
        if len(res) <= 18:
            return res
        return f"Claude{ver} {var[1]}"[:18].strip()

    # 3. GPT / OpenAI (e.g., gpt-4o, gpt-4o-mini, gpt-4.5, o1, o3-mini, gpt-5)
    if "gpt" in lower_s or re.search(r"\b(o1|o3|o4)\b", lower_s):
        if "4o mini" in lower_s or "4o-mini" in lower_s:
            return "GPT-4o Mini"
        if "4o" in lower_s:
            return "GPT-4o"
        if "4.5" in lower_s:
            return "GPT-4.5"
        if "o1 mini" in lower_s or "o1-mini" in lower_s:
            return "OpenAI o1-mini"
        if "o1" in lower_s:
            return "OpenAI o1"
        if "o3 mini" in lower_s or "o3-mini" in lower_s:
            return "OpenAI o3-mini"
        if "o3" in lower_s:
            return "OpenAI o3"
        if "o4" in lower_s:
            return "OpenAI o4"
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        return f"GPT{ver}"[:18].strip()

    # 4. DeepSeek (e.g., deepseek-r1, deepseek-v4, deepseek-v3, deepseek-chat)
    if "deepseek" in lower_s:
        if "r1" in lower_s:
            return "DeepSeek R1"
        if "v4" in lower_s:
            return "DeepSeek V4"
        if "v3" in lower_s or "chat" in lower_s:
            return "DeepSeek V3"
        v_match = re.search(r"(v\d+|r\d+)", lower_s)
        if v_match:
            return f"DeepSeek {v_match.group(1).upper()}"[:18]
        return "DeepSeek"

    # 5. Llama (e.g., llama-3.3-70b, llama-3.1-8b, llama-3.2-3b)
    if "llama" in lower_s:
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        s_match = re.search(r"(\d+b)", lower_s)
        size = f" {s_match.group(1).upper()}" if s_match else ""
        return f"Llama{ver}{size}"[:18].strip()

    # 6. Nemotron (e.g., nemotron-3-ultra-550b, nemotron-3.5-lightning, nemotron-70b)
    if "nemotron" in lower_s:
        v_match = re.search(r"nemotron\s*(\d+(?:\.\d+)?)", lower_s)
        if not v_match:
            v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        s_match = re.search(r"(\d+b)", lower_s)
        size = f" {s_match.group(1).upper()}" if s_match else ""
        return f"Nemotron{ver}{size}"[:18].strip()

    # 7. Qwen / QwQ (e.g., qwen-2.5-72b, qwq-32b)
    if "qwen" in lower_s or "qwq" in lower_s:
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        s_match = re.search(r"(\d+b)", lower_s)
        size = f" {s_match.group(1).upper()}" if s_match else ""
        prefix = "QwQ" if "qwq" in lower_s else "Qwen"
        return f"{prefix}{ver}{size}"[:18].strip()

    # 8. MiniMax (e.g., minimax-m3, minimax-01)
    if "minimax" in lower_s:
        m_match = re.search(r"(m\d+|01)", lower_s)
        tag = f" {m_match.group(1).upper()}" if m_match else " M3"
        return f"MiniMax{tag}"[:18].strip()

    # 9. Mistral / Mixtral
    if "mixtral" in lower_s:
        s_match = re.search(r"(\d+x\d+b)", lower_s)
        size = f" {s_match.group(1)}" if s_match else ""
        return f"Mixtral{size}"[:18].strip()
    if "mistral" in lower_s:
        var = "Large" if "large" in lower_s else ("Small" if "small" in lower_s else ("Nemo" if "nemo" in lower_s else ""))
        v_str = f" {var}" if var else ""
        return f"Mistral{v_str}"[:18].strip()

    # 10. Grok
    if "grok" in lower_s:
        v_match = re.search(r"(\d+)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        return f"Grok{ver}"[:18].strip()

    # Generic Fallback: Extract meaningful tokens
    tokens = s.split()
    words = [w.title() if not any(c.isdigit() for c in w) else w.upper() for w in tokens[:2]]
    cand = " ".join(words)
    return cand[:18].strip() or "Direct LLM"


def format_bot_display_name(
    agent_cfg: AgentConfig,
    resolved_model: Optional[str] = None,
    tag: Optional[str] = None,
) -> str:
    """Formats a clean, human-readable bot name (max 18 chars for Showdown)."""
    a_type = agent_cfg.type.lower()

    if a_type == "direct_llm":
        model = resolved_model or agent_cfg.model or ""
        if model:
            base = clean_llm_model_name(model)
        elif agent_cfg.provider:
            base = f"{agent_cfg.provider.title()}"
        else:
            base = "Direct LLM"
    elif a_type == "pokechamp":
        prior = "+L" if agent_cfg.use_llm_prior else ""
        base = f"PokeChamp D{agent_cfg.depth}{prior}"
    elif a_type == "max_damage":
        base = "MaxDamage AI"
    elif a_type == "heuristic":
        base = "Heuristic AI"
    elif a_type == "random":
        base = "Random AI"
    else:
        base = agent_cfg.name.title()

    # Sanitize base for Showdown (only alphanumeric, dot, hyphen, and space)
    base = re.sub(r"[^a-zA-Z0-9. -]", "", base).strip()

    if tag:
        max_base_len = 18 - 1 - len(str(tag))
        return f"{base[:max_base_len].strip()} {tag}"

    return base[:18].strip()


def create_agent_instance(
    agent_cfg: AgentConfig,
    app_config: AppConfig,
    team_str: Optional[str] = None,
    player_tag: Optional[str] = None,
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

    resolved_model = agent_cfg.model
    if not resolved_model and llm_client and getattr(llm_client, "default_model", None):
        resolved_model = llm_client.default_model

    unique_player_name = format_bot_display_name(
        agent_cfg, resolved_model=resolved_model, tag=player_tag
    )

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
            turn_timeout=agent_cfg.turn_timeout,
            bank_timeout=agent_cfg.bank_timeout,
            server_configuration=server_conf,
        )
    elif a_type == "direct_llm":
        return DirectLLMPlayer(
            player_name=unique_player_name,
            llm_client=llm_client,
            model=agent_cfg.model,
            temperature=agent_cfg.temperature,
            team=team_str,
            turn_timeout=agent_cfg.turn_timeout,
            bank_timeout=agent_cfg.bank_timeout,
            server_configuration=server_conf,
        )
    elif a_type == "max_damage":
        return MaxDamagePlayer(
            player_name=unique_player_name,
            team=team_str,
            turn_timeout=agent_cfg.turn_timeout,
            bank_timeout=agent_cfg.bank_timeout,
            server_configuration=server_conf,
        )
    elif a_type == "heuristic":
        return HeuristicPlayer(
            player_name=unique_player_name,
            evaluation_weights=agent_cfg.evaluation_weights,
            team=team_str,
            turn_timeout=agent_cfg.turn_timeout,
            bank_timeout=agent_cfg.bank_timeout,
            server_configuration=server_conf,
        )
    else:
        return RandomBenchmarkPlayer(
            player_name=unique_player_name,
            team=team_str,
            turn_timeout=agent_cfg.turn_timeout,
            bank_timeout=agent_cfg.bank_timeout,
            server_configuration=server_conf,
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
            p1_preview = format_bot_display_name(p1_cfg)
            p2_preview = format_bot_display_name(p2_cfg)
            is_mirror = (p1_preview.lower() == p2_preview.lower())

            for round_idx in range(1, self.tournament_config.rounds_per_pair + 1):
                # Pick teams for round
                t1 = loaded_teams[(round_idx - 1) % len(loaded_teams)]
                t2 = loaded_teams[round_idx % len(loaded_teams)]

                tag_1 = "1" if is_mirror else None
                tag_2 = "2" if is_mirror else None

                # Alternate side assignments
                if round_idx % 2 == 1:
                    player_a = create_agent_instance(p1_cfg, self.config, team_str=t1, player_tag=tag_1)
                    player_b = create_agent_instance(p2_cfg, self.config, team_str=t2, player_tag=tag_2)
                else:
                    player_a = create_agent_instance(p2_cfg, self.config, team_str=t2, player_tag=tag_2)
                    player_b = create_agent_instance(p1_cfg, self.config, team_str=t1, player_tag=tag_1)

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
