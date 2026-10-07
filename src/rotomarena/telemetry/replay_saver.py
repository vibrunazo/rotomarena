"""Pokémon Showdown battle replay HTML and JSON exporter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from jinja2 import Environment
from markupsafe import Markup


REPLAY_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RotomArena Replay: {{ player_1 }} vs {{ player_2 }}</title>
    <script>
        // Guarantee Showdown Config & Dex routes are defined before any scripts load
        window.Config = window.Config || {};
        window.Config.routes = {
            root: 'pokemonshowdown.com',
            client: 'play.pokemonshowdown.com',
            dex: 'dex.pokemonshowdown.com',
            replays: 'replay.pokemonshowdown.com'
        };

        // Intercept any broken effect images (stealth rock, spikes, webs) and redirect them to official Showdown fx CDN
        document.addEventListener('error', function(e) {
            var target = e.target;
            if (target && target.tagName === 'IMG') {
                var src = target.getAttribute('src') || '';
                if (!target.dataset.retried) {
                    target.dataset.retried = 'true';
                    var filename = src.split('/').pop().split('?')[0];
                    if (filename && filename.endsWith('.png')) {
                        target.src = 'https://play.pokemonshowdown.com/fx/' + filename;
                    }
                }
            }
        }, true);

        // Continuously ensure BattleEffects and Dex prefixes are properly set
        function fixBattleEffects() {
            var fxBase = 'https://play.pokemonshowdown.com/fx/';
            if (window.Dex) {
                if (!window.Dex.fxPrefix || !window.Dex.fxPrefix.startsWith('http')) {
                    window.Dex.fxPrefix = fxBase;
                }
                if (!window.Dex.resourcePrefix || !window.Dex.resourcePrefix.startsWith('http')) {
                    window.Dex.resourcePrefix = 'https://play.pokemonshowdown.com/';
                }
            }
            if (window.BattleEffects) {
                for (var id in window.BattleEffects) {
                    var fx = window.BattleEffects[id];
                    if (fx && fx.url && !fx.url.startsWith('http') && !fx.url.startsWith('//')) {
                        fx.url = fxBase + fx.url.replace(/^\\/?(fx\\/)?/, '');
                    }
                }
            }
        }
        var fixTimer = setInterval(fixBattleEffects, 50);
        window.addEventListener('load', function() {
            fixBattleEffects();
            setTimeout(function() { clearInterval(fixTimer); }, 10000);
        });
    </script>
    <style>
        :root {
            --bg-color: #0b1120;
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
            max-width: 1180px;
            margin: 0 auto;
        }
        .header {
            background-color: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
        }
        .match-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 14px;
            margin-bottom: 14px;
        }
        .badge {
            display: inline-block;
            padding: 6px 16px;
            border-radius: 9999px;
            font-size: 14px;
            font-weight: 600;
        }
        .badge-winner {
            background-color: rgba(74, 222, 128, 0.2);
            color: var(--accent-green);
            border: 1px solid var(--accent-green);
        }
        .replay-container {
            margin-bottom: 20px;
            border-radius: 12px;
            overflow: hidden;
            background: #111827;
            border: 1px solid var(--border);
            padding: 12px 0;
        }
        
        details.log-section {
            background-color: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px 24px;
            margin-top: 20px;
        }
        summary {
            font-weight: 600;
            font-size: 16px;
            cursor: pointer;
            color: var(--accent);
            outline: none;
        }
        .log-container {
            margin-top: 14px;
            max-height: 400px;
            overflow-y: auto;
            background: #0f172a;
            border-radius: 8px;
            padding: 12px;
            border: 1px solid var(--border);
        }
        .log-line {
            font-family: "Cascadia Code", "Fira Code", monospace;
            font-size: 12px;
            line-height: 1.5;
            padding: 3px 6px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        }
        .log-turn {
            background-color: #0369a1;
            color: #ffffff;
            font-weight: bold;
            margin-top: 8px;
            margin-bottom: 4px;
            padding: 4px 8px;
            border-radius: 4px;
        }
        .log-switch { color: #a78bfa; }
        .log-move { color: #38bdf8; }
        .log-damage { color: #f87171; }
        .log-faint { color: #ef4444; font-weight: bold; }
        .log-win { color: #4ade80; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="match-title">
                <div>
                    <h1 style="margin:0 0 6px 0; font-size: 22px;">⚡ RotomArena Battle Replay</h1>
                    <div style="color: var(--text-muted); font-size: 13px;">Match ID: <code>{{ match_id }}</code> | Format: <code>{{ format }}</code></div>
                </div>
                <div>
                    {% if winner %}
                    <span class="badge badge-winner">🏆 Winner: {{ winner }}</span>
                    {% else %}
                    <span class="badge">Result: Draw</span>
                    {% endif %}
                </div>
            </div>
            <div style="display: flex; gap: 24px; color: var(--text-muted); font-size: 14px; flex-wrap: wrap;">
                <div><strong>Player 1:</strong> {{ player_1 }}</div>
                <div><strong>Player 2:</strong> {{ player_2 }}</div>
                <div><strong>Total Turns:</strong> {{ total_turns }}</div>
                <div><strong>Duration:</strong> {{ duration_seconds }}s</div>
            </div>
        </div>

        <div class="replay-container">
            <div class="wrapper replay-wrapper" style="max-width:1180px;margin:0 auto">
                <div class="battle"></div>
                <div class="clippy"></div>
                <div class="battle-log"></div>
                <div class="replay-controls"></div>
                <div class="replay-controls-2"></div>
            </div>
        </div>

        <details class="log-section">
            <summary>📜 View Raw Protocol Log ({{ raw_log_lines|length }} lines)</summary>
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
        </details>
    </div>

    <script type="text/plain" class="battle-log-data">
{{ raw_log_text }}
    </script>
    <script src="https://play.pokemonshowdown.com/js/replay-embed.js"></script>
</body>
</html>
"""


def flatten_logs(logs: Any) -> List[str]:
    """Recursively flatten raw log items into a list of strings."""
    lines = []
    if isinstance(logs, str):
        for line in logs.split("\n"):
            l_str = line.strip()
            if l_str:
                lines.append(l_str)
    elif isinstance(logs, (list, tuple)):
        for item in logs:
            if isinstance(item, (list, tuple)):
                joined = "|".join(str(sub) for sub in item if sub is not None)
                if joined.strip():
                    lines.append(joined.strip())
            elif isinstance(item, str):
                for l in item.split("\n"):
                    if l.strip():
                        lines.append(l.strip())
            else:
                lines.append(str(item).strip())
    return lines


def save_battle_replay_html(
    match_id: str,
    player_1: str,
    player_2: str,
    winner: Optional[str],
    total_turns: int,
    duration_seconds: float,
    raw_logs: Any,
    output_path: str | Path,
    format_str: str = "gen9ou",
) -> Path:
    """Renders and saves a standalone animated HTML replay viewer."""
    lines = flatten_logs(raw_logs)
    # Showdown's convention for a log inlined in <script>: every "/" becomes "\/", so the log can never
    # contain "</script>"; replay-embed.js turns them back.
    raw_log_text = Markup("\n".join(lines).replace("/", "\\/"))

    template = Environment(autoescape=True).from_string(REPLAY_HTML_TEMPLATE)
    html_content = template.render(
        match_id=match_id,
        player_1=player_1,
        player_2=player_2,
        winner=winner,
        total_turns=total_turns,
        duration_seconds=round(duration_seconds, 2),
        raw_log_lines=lines,
        raw_log_text=raw_log_text,
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
