"""Markdown Match Summary and Benchmark Report Generator."""

from __future__ import annotations

from pathlib import Path
from typing import List
from rotomarena.telemetry.breadcrumbs import MatchTelemetry, TurnBreadcrumb


def generate_match_markdown_report(telemetry: MatchTelemetry, output_path: str | Path) -> Path:
    """Generates a structured Markdown match summary report."""
    p1 = telemetry.player("p1")
    p2 = telemetry.player("p2")
    p1_name = p1.display_name if p1 else "p1"
    p2_name = p2.display_name if p2 else "p2"

    def describe(player) -> str:
        if not player:
            return "unknown"
        model = f", `{player.model}`" if player.model else ""
        quant = f" ({player.quantization})" if player.quantization else ""
        return f"`{player.display_name}` [{player.config_id}{model}{quant}], team {player.team}"

    lines: List[str] = [
        f"# ⚡ RotomArena Match Report: `{telemetry.match_id}`",
        "",
        "## 📊 Match Overview",
        "",
        f"- **Format**: `{telemetry.format}` (ruleset `{telemetry.ruleset.get('version', '?')}`)",
        f"- **Player 1**: {describe(p1)}",
        f"- **Player 2**: {describe(p2)}",
        f"- **Winner**: **`{telemetry.winner or 'Draw'}`**",
        f"- **Total Turns**: {telemetry.total_turns}",
        f"- **Match Duration**: {telemetry.duration_seconds}s",
        "",
    ]

    # Aggregate telemetry statistics
    p1_turns = [b for b in telemetry.breadcrumbs if b.agent_name == p1_name]
    p2_turns = [b for b in telemetry.breadcrumbs if b.agent_name == p2_name]

    def compute_agent_metrics(crumbs: List[TurnBreadcrumb]):
        total_tokens = 0
        total_latency = 0.0
        searches_run = 0
        total_nodes = 0
        for c in crumbs:
            if c.llm_metrics:
                total_tokens += c.llm_metrics.get("total_tokens", 0)
                total_latency += c.llm_metrics.get("latency_ms", 0.0)
            if c.search_telemetry:
                searches_run += 1
                total_nodes += c.search_telemetry.get("nodes_evaluated", 0)
        
        avg_latency = round(total_latency / max(1, len(crumbs)), 1)
        avg_nodes = round(total_nodes / max(1, searches_run), 1) if searches_run else 0
        autopilot = sum(1 for c in crumbs if c.decision_source not in ("model", "forced"))
        return total_tokens, avg_latency, avg_nodes, autopilot

    p1_tokens, p1_lat, p1_nodes, p1_auto = compute_agent_metrics(p1_turns)
    p2_tokens, p2_lat, p2_nodes, p2_auto = compute_agent_metrics(p2_turns)

    lines.extend([
        "## 🤖 Agent Performance & Resource Consumption",
        "",
        f"| Metric | Player 1 (`{p1_name}`) | Player 2 (`{p2_name}`) |",
        "|---|---|---|",
        f"| **Turns Played** | {len(p1_turns)} | {len(p2_turns)} |",
        f"| **Autopilot Turns** (fallback picked the move) | {p1_auto} | {p2_auto} |",
        f"| **Total LLM Tokens** | {p1_tokens:,} | {p2_tokens:,} |",
        f"| **Avg Decision Latency** | {p1_lat} ms | {p2_lat} ms |",
        f"| **Avg Search Tree Nodes** | {p1_nodes} | {p2_nodes} |",
        "",
        "## 🔍 Turn-by-Turn Decision Breadcrumbs",
        "",
    ])

    for b in telemetry.breadcrumbs:
        source = "" if b.decision_source == "model" else f" — AUTOPILOT ({b.decision_source})"
        lines.append(f"### Turn {b.turn} - `{b.agent_name}` ({b.agent_type}){source}")
        lines.append(f"- **Active Matchup**: `{b.active_pokemon}` ({b.active_hp_pct}% HP) vs `{b.opponent_active}` ({b.opponent_hp_pct}% HP)")
        lines.append(f"- **Chosen Action**: **`{b.chosen_action}`**")
        
        if b.reasoning:
            clean_reasoning = b.reasoning.replace("\n", "\n  > ")
            lines.append(f"- **Reasoning / CoT**:\n  > {clean_reasoning}")

        if b.search_telemetry and "candidate_scores" in b.search_telemetry:
            scores_str = ", ".join([f"`{k}`: {v}" for k, v in b.search_telemetry["candidate_scores"].items()])
            lines.append(f"- **Search Tree Evaluations**: {scores_str}")

        if b.llm_metrics:
            lines.append(
                f"- **LLM Metrics**: {b.llm_metrics.get('total_tokens', 0)} tokens, "
                f"{round(b.llm_metrics.get('latency_ms', 0.0), 1)} ms ({b.llm_metrics.get('model', '')})"
            )

        lines.append("")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
