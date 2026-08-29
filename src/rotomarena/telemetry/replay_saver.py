"""Pokémon Showdown battle replay HTML and JSON exporter."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from jinja2 import Template


REPLAY_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RotomArena Replay: {{ player_1 }} vs {{ player_2 }}</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #38bdf8;
            --accent-green: #4ade80;
            --accent-red: #f87171;
            --border: #334155;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 24px;
        }
        .container {
            max-width: 1000px;
            margin: 0 auto;
        }
        .header {
            background-color: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }
        .match-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            margin-bottom: 16px;
        }
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 14px;
            font-weight: 600;
        }
        .badge-winner {
            background-color: rgba(74, 222, 128, 0.2);
            color: var(--accent-green);
            border: 1px solid var(--accent-green);
        }
        .log-section {
            background-color: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
        }
        .log-line {
            font-family: "Cascadia Code", "Fira Code", monospace;
            font-size: 13px;
            line-height: 1.6;
            padding: 4px 8px;
            border-radius: 4px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }
        .log-turn {
            background-color: #0369a1;
            color: #ffffff;
            font-weight: bold;
            margin-top: 12px;
            margin-bottom: 6px;
            padding: 6px 12px;
            border-radius: 6px;
        }
        .log-switch { color: #a78bfa; }
        .log-move { color: #38bdf8; }
        .log-damage { color: #f87171; }
        .log-faint { color: #ef4444; font-weight: bold; }
        .log-win { color: #4ade80; font-weight: bold; font-size: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="match-title">
                <div>
                    <h1 style="margin:0 0 8px 0; font-size: 24px;">⚡ RotomArena Battle Replay</h1>
                    <div style="color: var(--text-muted);">Match ID: <code>{{ match_id }}</code> | Format: <code>{{ format }}</code></div>
                </div>
                <div>
                    {% if winner %}
                    <span class="badge badge-winner">Winner: {{ winner }}</span>
                    {% else %}
                    <span class="badge">Result: Draw</span>
                    {% endif %}
                </div>
            </div>
            <div style="display: flex; gap: 24px; color: var(--text-muted); font-size: 14px;">
                <div><strong>Player 1:</strong> {{ player_1 }}</div>
                <div><strong>Player 2:</strong> {{ player_2 }}</div>
                <div><strong>Total Turns:</strong> {{ total_turns }}</div>
                <div><strong>Duration:</strong> {{ duration_seconds }}s</div>
            </div>
        </div>

        <div class="log-section">
            <h2 style="margin-top:0; font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 8px;">Showdown Protocol Stream</h2>
            <div class="log-container">
                {% for line in raw_log_lines %}
                    {% if line.startswith('|turn|') %}
                        <div class="log-turn">Turn {{ line.split('|')[2] }}</div>
                    {% elif '|switch|' in line or '|drag|' in line %}
                        <div class="log-line log-switch">{{ line }}</div>
                    {% elif '|move|' in line %}
                        <div class="log-line log-move">{{ line }}</div>
                    {% elif '|-damage|' in line or '|-heal|' in line %}
                        <div class="log-line log-damage">{{ line }}</div>
                    {% elif '|faint|' in line %}
                        <div class="log-line log-faint">💀 {{ line }}</div>
                    {% elif '|win|' in line %}
                        <div class="log-line log-win">🏆 {{ line }}</div>
                    {% else %}
                        <div class="log-line">{{ line }}</div>
                    {% endif %}
                {% endfor %}
            </div>
        </div>
    </div>
</body>
</html>
"""


def save_battle_replay_html(
    match_id: str,
    player_1: str,
    player_2: str,
    winner: Optional[str],
    total_turns: int,
    duration_seconds: float,
    raw_logs: List[str] | str,
    output_path: str | Path,
    format_str: str = "gen9ou",
) -> Path:
    """Renders and saves a standalone HTML replay viewer."""
    if isinstance(raw_logs, str):
        lines = [line.strip() for line in raw_logs.split("\n") if line.strip()]
    else:
        lines = raw_logs

    template = Template(REPLAY_HTML_TEMPLATE)
    html_content = template.render(
        match_id=match_id,
        player_1=player_1,
        player_2=player_2,
        winner=winner,
        total_turns=total_turns,
        duration_seconds=round(duration_seconds, 2),
        raw_log_lines=lines,
        format=format_str,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_content, encoding="utf-8")
    return out


def save_battle_raw_json(
    match_id: str,
    metadata: Dict[str, Any],
    raw_logs: List[str] | str,
    output_path: str | Path,
) -> Path:
    """Saves raw battle protocol logs and metadata as JSON."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    
    if isinstance(raw_logs, str):
        log_lines = raw_logs.split("\n")
    else:
        log_lines = raw_logs

    data = {
        "match_id": match_id,
        "metadata": metadata,
        "raw_logs": log_lines,
    }
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out
