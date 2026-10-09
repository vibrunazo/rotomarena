"""What the run monitor shows: the round robin's plan and progress (recomputed from the same schedule the run
follows), the games being played right now (asked of the Showdown server as a spectator), the local model servers,
recent games, spending and a rough finish time. Read-only: nothing here changes a run."""

from __future__ import annotations

import asyncio
import datetime
import json
import math
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from rotomarena.config import AppConfig
from rotomarena.ladder import games_left, quick_pairs_first, round_robin_ids, round_robin_pairs, version_state
from rotomarena.local_servers import running as running_servers
from rotomarena.results import load_matches, void_reason
from rotomarena.teams.draft import draft_cost, load_drafts, playable_team

RUNS = Path("runs")
LLAMA_LOGS = Path(r"D:\docs\assets\generator\tools\llm\llamacpp\logs")
GAMES_PER_PAIR = 2  # what the round-robin driver asks for
DEFAULT_TURN_SECONDS = {"local": 25.0, "api": 8.0, "decision": 1.0, "bot": 0.1}
DEFAULT_TURNS = 25


def _alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        import os
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_int(path: Path) -> Optional[int]:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _kind(app_cfg: AppConfig, cid: str) -> str:
    a = app_cfg.agents[cid]
    if not a.is_model:
        return "bot"
    return "decision" if a.type == "decision" else "local" if a.provider == "local" else "api"


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


async def live_battles(app_cfg: AppConfig, timeout: float = 3.0) -> List[Dict[str, Any]]:
    """The battles open on the Showdown server, each with its players and current turn (joined as a spectator)."""
    import websockets

    out = []
    try:
        async with websockets.connect(app_cfg.server.websocket_url, open_timeout=timeout) as ws:
            await ws.send("|/cmd roomlist")
            rooms: Dict[str, Any] = {}
            for _ in range(20):
                msg = await asyncio.wait_for(ws.recv(), timeout)
                if "|queryresponse|roomlist|" in msg:
                    rooms = json.loads(msg.split("|queryresponse|roomlist|", 1)[1]).get("rooms") or {}
                    break
            for rid, room in rooms.items():
                await ws.send(f"|/join {rid}")
                turn = 0
                for _ in range(30):
                    msg = await asyncio.wait_for(ws.recv(), timeout)
                    if msg.startswith(f">{rid}"):
                        turns = re.findall(r"^\|turn\|(\d+)$", msg, re.MULTILINE)
                        turn = int(turns[-1]) if turns else turn
                        if "|init|battle" in msg:
                            break
                await ws.send(f"{rid}|/leave")
                out.append({"room": rid, "p1": room.get("p1"), "p2": room.get("p2"), "turn": turn})
    except (OSError, asyncio.TimeoutError, Exception):  # no server, or it refused: nothing live
        return out
    return out


def _llama_speed(port: int) -> Optional[Dict[str, Any]]:
    """The last generation speed a local server logged."""
    log = LLAMA_LOGS / f"server_{port}.log"
    try:
        with open(log, "rb") as f:
            f.seek(max(0, log.stat().st_size - 60_000))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    speeds = re.findall(r"eval time = .*?([\d.]+) tokens per second", tail)
    return {"tok_s": float(speeds[-1]) if speeds else None, "last_write": _iso(log.stat().st_mtime)}


def _turn_seconds(matches) -> Dict[str, float]:
    """Median seconds per decision for each model, from this version's games."""
    per: Dict[str, List[float]] = {}
    for m in matches:
        names = {p.username: p.config_id for p in m.players}
        for c in m.breadcrumbs:
            lat = (c.llm_metrics or {}).get("latency_ms")
            cid = names.get(c.agent_name)
            if lat and cid:
                per.setdefault(cid, []).append(lat / 1000)
    return {k: statistics.median(v) for k, v in per.items() if v}


def status(app_cfg: AppConfig) -> Dict[str, Any]:
    now = datetime.datetime.now()
    version = app_cfg.ruleset.version
    state = version_state(app_cfg)
    matches = state.matches
    max_autopilot = app_cfg.ladder.max_autopilot

    # The schedule, exactly as round_robin builds it
    drafts = load_drafts(version=version)
    ids = round_robin_ids(app_cfg)
    sitting_out = [k for k, a in app_cfg.agents.items() if a.is_model and a.active and k not in ids]
    pairs = quick_pairs_first(round_robin_pairs(ids), app_cfg)
    left = {k: games_left(app_cfg, app_cfg.agents[k]) for k in ids}
    plan = []
    for i, (a, b) in enumerate(pairs, 1):
        done = state.games(a, b)
        need = max(GAMES_PER_PAIR - done, 0)
        more = min(need, left[a], left[b])
        left[a] -= more
        left[b] -= more
        planned = done + more
        plan.append({"index": i, "a": a, "b": b, "done": done, "planned": planned,
                     "skipped": planned < GAMES_PER_PAIR and more < need})
    current = next((p for p in plan if p["done"] < p["planned"]), None)

    # Time left, as a range: each remaining pair's games at its models' measured seconds per turn, for a short,
    # typical and long game (the 25th, 50th and 75th percentile of game lengths so far)
    secs = _turn_seconds(matches)
    lengths = sorted(m.total_turns for m in matches)
    if len(lengths) >= 4:
        spread = {k: lengths[round(q * (len(lengths) - 1))] for k, q in (("low", 0.25), ("mid", 0.5), ("high", 0.75))}
    else:
        spread = {"low": DEFAULT_TURNS * 0.7, "mid": DEFAULT_TURNS, "high": DEFAULT_TURNS * 1.4}

    def turn_time(cid: str) -> float:
        return secs.get(cid) or DEFAULT_TURN_SECONDS[_kind(app_cfg, cid)]

    def pair_seconds(p: Dict[str, Any], turns: float) -> float:
        games = p["planned"] - p["done"]
        if games <= 0:
            return 0.0
        a, b = app_cfg.agents[p["a"]], app_cfg.agents[p["b"]]
        both_local = _kind(app_cfg, p["a"]) == _kind(app_cfg, p["b"]) == "local"
        per_turn = turn_time(p["a"]) + turn_time(p["b"]) if both_local else max(turn_time(p["a"]), turn_time(p["b"]))
        lanes = min(x for x in (app_cfg.ladder.parallel_games, games, a.max_parallel_games, b.max_parallel_games) if x)
        return turns * per_turn * math.ceil(games / lanes)

    remaining = {k: sum(pair_seconds(p, t) for p in plan) for k, t in spread.items()}
    # a bot decides instantly, so only models can have a pace still to guess
    unmeasured = sorted({x for p in plan if p["done"] < p["planned"] for x in (p["a"], p["b"])
                         if x not in secs and _kind(app_cfg, x) != "bot"})
    stamps = [datetime.datetime.strptime(m.match_id[6:21], "%Y%m%d_%H%M%S") for m in matches
              if re.match(r"match_\d{8}_\d{6}", m.match_id)]
    first_game = min(stamps) if stamps else None

    # Processes and servers
    driver_pid = _read_int(RUNS / "driver.pid")
    showdown_run = _read_int(Path(app_cfg.server.server_dir).resolve().parent / "showdown.run")
    try:
        servers = running_servers(app_cfg)
    except Exception:
        servers = {}
    local_servers = [{"port": port, "model": model, **(_llama_speed(port) or {})} for port, model in sorted(servers.items())]

    # In-progress game folders (created at a game's start; the record is written at its end)
    run_started = (RUNS / "roundrobin.pid").stat().st_mtime if (RUNS / "roundrobin.pid").exists() else 0
    in_progress = []
    for d in RUNS.glob("match_*"):
        if d.is_dir() and not (d / "breadcrumbs.json").exists() and d.stat().st_mtime >= run_started:
            in_progress.append({"folder": d.name, "started": _iso(d.stat().st_mtime),
                                "minutes": round((now.timestamp() - d.stat().st_mtime) / 60)})
    in_progress.sort(key=lambda g: g["started"])

    # Models: games done and planned, results, spending
    models = []
    for k in ids:
        a = app_cfg.agents[k]
        mine = [m for m in matches if any(p.config_id == k for p in m.players)]
        valid = [m for m in mine if not void_reason(m, max_autopilot)]
        wins = sum(1 for m in valid if any(p.config_id == k and p.username == m.winner for p in m.players))
        # Every game it finished in this version, voided ones too (they were paid for), plus all its drafting
        games_cost = sum((c.llm_metrics or {}).get("cost_usd") or 0 for m in mine for c in m.breadcrumbs
                         if any(p.config_id == k and p.username == c.agent_name for p in m.players))
        drafting = draft_cost(drafts.get(k) or {})
        models.append({
            "id": k, "name": a.display_name or k, "kind": _kind(app_cfg, k),
            "done": sum(p["done"] for p in plan if k in (p["a"], p["b"])),
            "planned": sum(p["planned"] for p in plan if k in (p["a"], p["b"])),
            "wins": wins, "losses": len(valid) - wins, "void": len(mine) - len(valid),
            "games_cost_usd": round(games_cost, 4), "draft_cost_usd": round(drafting, 4),
            "cost_usd": round(games_cost + drafting, 4), "cap": a.max_games, "sec_per_turn": round(secs[k], 1) if k in secs else None,
        })
    models.sort(key=lambda m: (-(m["done"] / m["planned"]) if m["planned"] else 0, m["name"]))

    recent = sorted(matches, key=lambda m: m.match_id, reverse=True)[:8]
    names = {k: (app_cfg.agents[k].display_name or k) for k in app_cfg.agents}
    recent_rows = [{
        "match_id": m.match_id,
        "players": [names.get(p.config_id, p.config_id) for p in m.players],
        "winner": next((names.get(p.config_id, p.config_id) for p in m.players if p.username == m.winner), None),
        "turns": m.total_turns, "minutes": round((m.duration_seconds or 0) / 60, 1),
        "void": void_reason(m, max_autopilot),
    } for m in recent]

    try:
        log_tail = (RUNS / "roundrobin-publisher.log").read_text(encoding="utf-8").splitlines()[-3:]
    except OSError:
        log_tail = []
    errors = []
    err = RUNS / "roundrobin.err"
    if err.exists() and err.stat().st_mtime >= run_started and err.stat().st_size:
        errors = err.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:]

    activity = max([run_started] + [(LLAMA_LOGS / f"server_{s['port']}.log").stat().st_mtime for s in local_servers
                                    if (LLAMA_LOGS / f"server_{s['port']}.log").exists()]
                   + [d.stat().st_mtime for d in RUNS.glob("match_*")])
    return {
        "now": now.isoformat(timespec="seconds"),
        "version": version,
        "run": {"driver_pid": driver_pid, "running": _alive(driver_pid), "started": _iso(run_started) if run_started else None,
                "showdown_pid": showdown_run, "showdown_running": _alive(showdown_run),
                "last_activity": _iso(activity), "idle_minutes": round((now.timestamp() - activity) / 60)},
        "totals": {"games_done": sum(p["done"] for p in plan), "games_planned": sum(p["planned"] for p in plan),
                   "pairs_done": sum(1 for p in plan if p["planned"] and p["done"] >= p["planned"]),
                   "pairs_planned": sum(1 for p in plan if p["planned"]), "pairs_skipped": sum(1 for p in plan if not p["planned"]),
                   "pairs_total": len(plan), "void_games": state.void_count},
        "eta": {**{f"{k}_hours": round(v / 3600, 1) for k, v in remaining.items()},
                **{f"finish_{k}": (now + datetime.timedelta(seconds=v)).isoformat(timespec="minutes") for k, v in remaining.items()},
                "turns": spread, "games_measured": len(lengths), "unmeasured": unmeasured,
                "first_game": first_game.isoformat(timespec="minutes") if first_game else None,
                "elapsed_hours": round((now - first_game).total_seconds() / 3600, 1) if first_game else 0},
        "current": current,
        "next": [p for p in plan if p["done"] < p["planned"]][1:6],
        "plan": plan,
        "in_progress": in_progress,
        "sitting_out": sitting_out,
        "models": models,
        "names": names,
        "local_servers": local_servers,
        "recent": recent_rows,
        "publisher": log_tail,
        "errors": errors,
        "spend_usd": round(sum(m["cost_usd"] for m in models), 4),
    }
