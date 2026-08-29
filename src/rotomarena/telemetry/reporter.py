"""Markdown Match Summary and Benchmark Report Generator."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from rotomarena.telemetry.breadcrumbs import MatchTelemetry, TurnBreadcrumb


def generate_match_markdown_report(telemetry: MatchTelemetry, output_path: str | Path) -> Path:
    """Generates a structured Markdown match summary report."""
    lines: List[str] = [
        f"# ⚡ RotomArena Match Report: `{telemetry.match_id}`",
        "",
        "## 📊 Match Overview",
        "",
        f"- **Format**: `{telemetry.format}`",
        f"- **Player 1**: `{telemetry.player_1}`",
        f"- **Player 2**: `{telemetry.player_2}`",
        f"- **Winner**: **`{telemetry.winner or 'Draw'}`**",
        f"- **Total Turns**: {telemetry.total_turns}",
        f"- **Match Duration**: {telemetry.duration_seconds}s",
        "",
    ]

    # Aggregate telemetry statistics
    p1_turns = [b for b in telemetry.breadcrumbs if b.agent_name == telemetry.player_1]
    p2_turns = [b for b in telemetry.breadcrumbs if b.agent_name == telemetry.player_2]

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
        return total_tokens, avg_latency, avg_nodes

    p1_tokens, p1_lat, p1_nodes = compute_agent_metrics(p1_turns)
    p2_tokens, p2_lat, p2_nodes = compute_agent_metrics(p2_turns)

    lines.extend([
        "## 🤖 Agent Performance & Resource Consumption",
        "",
        "| Metric | Player 1 (`" + telemetry.player_1 + "`) | Player 2 (`" + telemetry.player_2 + "`) |",
        "|---|---|---|",
        f"| **Turns Played** | {len(p1_turns)} | {len(p2_turns)} |",
        f"| **Total LLM Tokens** | {p1_tokens:,} | {p2_tokens:,} |",
        f"| **Avg Decision Latency** | {p1_lat} ms | {p2_lat} ms |",
        f"| **Avg Search Tree Nodes** | {p1_nodes} | {p2_nodes} |",
        "",
        "## 🔍 Turn-by-Turn Decision Breadcrumbs",
        "",
    ])

    for b in telemetry.breadcrumbs:
        lines.append(f"### Turn {b.turn} - `{b.agent_name}` ({b.agent_type})")
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
