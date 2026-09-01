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
            --bg-color: #0b1120;
            --card-bg: #1e293b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #38bdf8;
            --accent-green: #4ade80;
            --accent-red: #f87171;
            --border: #334155;
            --caster-bg: #182234;
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
        
        /* 🎙️ Commentary & TTS Caster Panel */
        .commentary-panel {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid #38bdf8;
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 20px;
            box-shadow: 0 0 15px rgba(56, 189, 248, 0.15);
        }
        .commentary-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 14px;
            margin-bottom: 14px;
        }
        .commentary-title {
            font-size: 17px;
            font-weight: 700;
            color: #38bdf8;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .pulse-icon {
            display: inline-block;
            transition: transform 0.2s;
        }
        .pulse-icon.speaking {
            animation: pulse-glow 1s infinite alternate;
        }
        @keyframes pulse-glow {
            from { transform: scale(1.0); filter: drop-shadow(0 0 2px #38bdf8); }
            to { transform: scale(1.3); filter: drop-shadow(0 0 8px #38bdf8); }
        }
        .commentary-controls {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }
        .btn {
            cursor: pointer;
            font-weight: 600;
            padding: 8px 16px;
            border-radius: 8px;
            border: none;
            font-size: 14px;
            transition: all 0.2s ease;
        }
        .btn-primary {
            background: #0284c7;
            color: #ffffff;
        }
        .btn-primary:hover {
            background: #0369a1;
        }
        .btn-warning {
            background: #f59e0b;
            color: #ffffff;
        }
        .btn-warning:hover {
            background: #d97706;
        }
        .btn-secondary {
            background: #334155;
            color: #f8fafc;
        }
        .btn-secondary:hover {
            background: #475569;
        }
        .control-group {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            color: var(--text-muted);
        }
        .select-input {
            background: #0f172a;
            color: #f8fafc;
            border: 1px solid var(--border);
            padding: 6px 10px;
            border-radius: 6px;
            font-size: 13px;
            max-width: 200px;
        }
        .teleprompter-box {
            background: #0a0f1d;
            border: 1px solid #1e293b;
            border-left: 4px solid #38bdf8;
            border-radius: 8px;
            padding: 16px 20px;
            min-height: 54px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .teleprompter-turn-badge {
            font-size: 12px;
            font-weight: bold;
            color: #38bdf8;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .teleprompter-text {
            font-size: 15px;
            line-height: 1.6;
            color: #f1f5f9;
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

        <!-- 🎙️ Commentary & TTS Caster Panel -->
        <div class="commentary-panel" id="commentary-section" style="{% if not commentary_json %}display:none;{% endif %}">
            <div class="commentary-header">
                <div class="commentary-title">
                    <span class="pulse-icon" id="tts-pulse">🎙️</span>
                    <span>Play-by-Play Esports Commentary & TTS Caster</span>
                </div>
                <div class="commentary-controls">
                    <button id="tts-toggle-btn" class="btn btn-primary" onclick="toggleCommentaryPlay()">▶ Start Commentary</button>
                    <button id="tts-stop-btn" class="btn btn-secondary" onclick="stopCommentary()">⏹ Reset</button>
                    <div class="control-group">
                        <label for="tts-voice-select">Voice:</label>
                        <select id="tts-voice-select" class="select-input"></select>
                    </div>
                    <div class="control-group">
                        <label for="tts-rate-input">Speed: <span id="tts-rate-val">1.1x</span></label>
                        <input type="range" id="tts-rate-input" min="0.8" max="1.6" step="0.1" value="1.1" oninput="updateTtsRate(this.value)">
                    </div>
                </div>
            </div>

            <div class="teleprompter-box">
                <div class="teleprompter-turn-badge" id="teleprompter-turn-badge">Opening Matchup</div>
                <div class="teleprompter-text" id="teleprompter-text">Press "Start Commentary" to begin live turn-by-turn voice narration...</div>
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
    {% if commentary_json %}
    <script type="application/json" id="rotomarena-commentary-data">
{{ commentary_json }}
    </script>
    {% endif %}
    <script src="https://play.pokemonshowdown.com/js/replay-embed.js"></script>

    <script>
    (function() {
        let commentaryData = null;
        try {
            const raw = document.getElementById('rotomarena-commentary-data');
            if (raw && raw.textContent.trim()) {
                commentaryData = JSON.parse(raw.textContent.trim());
            }
        } catch (e) {
            console.error("Failed to parse commentary data:", e);
        }

        if (!commentaryData || !commentaryData.turns || !commentaryData.turns.length) {
            return;
        }

        const section = document.getElementById('commentary-section');
        if (section) section.style.display = 'block';

        let isPlaying = false;
        let currentTurn = 0;
        let voices = [];
        let speechRate = 1.1;

        const toggleBtn = document.getElementById('tts-toggle-btn');
        const voiceSelect = document.getElementById('tts-voice-select');
        const turnBadge = document.getElementById('teleprompter-turn-badge');
        const teleText = document.getElementById('teleprompter-text');
        const pulseIcon = document.getElementById('tts-pulse');

        function loadVoices() {
            if (!('speechSynthesis' in window)) return;
            voices = window.speechSynthesis.getVoices();
            if (!voiceSelect) return;
            voiceSelect.innerHTML = '';
            
            const sorted = [...voices].sort((a, b) => {
                const aEn = a.lang.startsWith('en') ? 0 : 1;
                const bEn = b.lang.startsWith('en') ? 0 : 1;
                return aEn - bEn;
            });

            sorted.forEach((v, idx) => {
                const opt = document.createElement('option');
                opt.value = v.name;
                opt.textContent = `${v.name} (${v.lang})`;
                if (v.default || (v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Online') || v.name.includes('Google') || idx === 0))) {
                    opt.selected = true;
                }
                voiceSelect.appendChild(opt);
            });
        }

        if ('speechSynthesis' in window) {
            window.speechSynthesis.onvoiceschanged = loadVoices;
            loadVoices();
        }

        function getTurnCommentary(t) {
            const match = commentaryData.turns.find(x => x.turn === t);
            return match || null;
        }

        function updateUI(t, text, isSpeaking) {
            if (turnBadge) {
                const turnObj = getTurnCommentary(t);
                turnBadge.textContent = turnObj && turnObj.title ? turnObj.title : (t === 0 ? "Opening Leads" : `Turn ${t}`);
            }
            if (teleText) teleText.textContent = text || "Battle in progress...";
            if (pulseIcon) {
                if (isSpeaking) {
                    pulseIcon.classList.add('speaking');
                } else {
                    pulseIcon.classList.remove('speaking');
                }
            }
        }

        function speakTurn(turnNum) {
            if (!isPlaying) return;
            const turnObj = getTurnCommentary(turnNum);
            if (!turnObj) {
                if (turnNum < commentaryData.total_turns) {
                    advanceToTurn(turnNum + 1);
                } else {
                    stop();
                }
                return;
            }

            updateUI(turnNum, turnObj.commentary, true);

            if (!('speechSynthesis' in window)) {
                setTimeout(() => {
                    if (isPlaying) advanceToTurn(turnNum + 1);
                }, 3000);
                return;
            }

            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(turnObj.commentary);
            utterance.rate = speechRate;
            
            const selName = voiceSelect ? voiceSelect.value : '';
            const chosenVoice = voices.find(v => v.name === selName);
            if (chosenVoice) utterance.voice = chosenVoice;

            utterance.onend = () => {
                updateUI(turnNum, turnObj.commentary, false);
                if (!isPlaying) return;
                
                setTimeout(() => {
                    if (!isPlaying) return;
                    if (turnNum < commentaryData.total_turns) {
                        advanceToTurn(turnNum + 1);
                    } else {
                        stop();
                    }
                }, 400);
            };

            utterance.onerror = (e) => {
                console.warn("TTS error:", e);
                updateUI(turnNum, turnObj.commentary, false);
                if (isPlaying && turnNum < commentaryData.total_turns) {
                    setTimeout(() => advanceToTurn(turnNum + 1), 1000);
                }
            };

            window.speechSynthesis.speak(utterance);
        }

        function advanceToTurn(nextTurn) {
            currentTurn = nextTurn;
            if (window.Replays && window.Replays.battle) {
                try {
                    if (typeof window.Replays.battle.seekTurn === 'function') {
                        window.Replays.battle.seekTurn(nextTurn);
                    } else if (typeof window.Replays.battle.stepTurn === 'function') {
                        window.Replays.battle.stepTurn();
                    }
                } catch (err) {
                    console.warn("Replay step error:", err);
                }
            }
            speakTurn(nextTurn);
        }

        function start() {
            isPlaying = true;
            if (toggleBtn) {
                toggleBtn.textContent = '⏸ Pause Commentary';
                toggleBtn.classList.remove('btn-primary');
                toggleBtn.classList.add('btn-warning');
            }
            if (window.Replays && window.Replays.battle && typeof window.Replays.battle.turn === 'number') {
                currentTurn = window.Replays.battle.turn;
            }
            speakTurn(currentTurn);
        }

        function pause() {
            isPlaying = false;
            if ('speechSynthesis' in window) window.speechSynthesis.cancel();
            if (toggleBtn) {
                toggleBtn.textContent = '▶ Resume Commentary';
                toggleBtn.classList.remove('btn-warning');
                toggleBtn.classList.add('btn-primary');
            }
            updateUI(currentTurn, getTurnCommentary(currentTurn)?.commentary, false);
        }

        function stop() {
            isPlaying = false;
            if ('speechSynthesis' in window) window.speechSynthesis.cancel();
            if (toggleBtn) {
                toggleBtn.textContent = '▶ Start Commentary';
                toggleBtn.classList.remove('btn-warning');
                toggleBtn.classList.add('btn-primary');
            }
            currentTurn = 0;
            updateUI(0, getTurnCommentary(0)?.commentary || "Ready to start commentary.", false);
        }

        window.toggleCommentaryPlay = function() {
            if (isPlaying) {
                pause();
            } else {
                start();
            }
        };

        window.stopCommentary = function() {
            stop();
            if (window.Replays && window.Replays.battle && typeof window.Replays.battle.seekTurn === 'function') {
                window.Replays.battle.seekTurn(0);
            }
        };

        window.updateTtsRate = function(val) {
            speechRate = parseFloat(val);
            const label = document.getElementById('tts-rate-val');
            if (label) label.textContent = `${speechRate.toFixed(1)}x`;
        };

        const intro = getTurnCommentary(0);
        if (intro) {
            updateUI(0, intro.commentary, false);
        }
    })();
    </script>
</body>
</html>
"""


def _flatten_logs(logs: Any) -> List[str]:
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
    commentary: Optional[Any] = None,
) -> Path:
    """Renders and saves a standalone animated HTML replay viewer with TTS commentary."""
    lines = _flatten_logs(raw_logs)
    raw_log_text = "\n".join(lines)

    commentary_json = None
    if commentary is not None:
        if hasattr(commentary, "model_dump_json"):
            commentary_json = commentary.model_dump_json(indent=2)
        elif hasattr(commentary, "json"):
            commentary_json = commentary.json()
        elif isinstance(commentary, dict):
            commentary_json = json.dumps(commentary, indent=2)
        elif isinstance(commentary, str):
            commentary_json = commentary

    template = Template(REPLAY_HTML_TEMPLATE)
    html_content = template.render(
        match_id=match_id,
        player_1=player_1,
        player_2=player_2,
        winner=winner,
        total_turns=total_turns,
        duration_seconds=round(duration_seconds, 2),
        raw_log_lines=lines,
        raw_log_text=raw_log_text,
        commentary_json=commentary_json,
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
