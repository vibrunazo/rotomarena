"""The run monitor's buttons: start the round robin, stop it (with the Showdown server and the local model servers
it started), and stop the monitor itself. Everything starts without a console window."""

from __future__ import annotations

import datetime
import re
import subprocess
import sys
from typing import Optional

from rotomarena import local_servers
from rotomarena.config import AppConfig
from rotomarena.dashboard.driver import DRIVER_PID, ROOT, RUNS
from rotomarena.server.manager import ShowdownServerManager, _alive

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
NEW_GROUP = 0x00000200 if sys.platform == "win32" else 0


def driver_pid() -> Optional[int]:
    """The driver's PID while it runs."""
    try:
        pid = int(DRIVER_PID.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if _alive(pid) else None


def start_run() -> str:
    if driver_pid():
        return "A run is already going."
    subprocess.Popen([sys.executable, "-m", "rotomarena.dashboard.driver"], cwd=ROOT,
                     stdout=subprocess.DEVNULL, stderr=open(RUNS / "driver.err", "a", encoding="utf-8"),
                     creationflags=NO_WINDOW | NEW_GROUP, close_fds=True)
    return "Started the round robin. It resumes where it stopped: pairs already played are skipped."


def publish_now() -> str:
    """Exports the standings and pushes them to the site, in the background (the export takes a minute)."""
    subprocess.Popen([sys.executable, "-m", "rotomarena.dashboard.driver", "--publish"], cwd=ROOT,
                     stdout=subprocess.DEVNULL, stderr=open(RUNS / "driver.err", "a", encoding="utf-8"),
                     creationflags=NO_WINDOW | NEW_GROUP, close_fds=True)
    return "Publishing: the standings go to the site in a minute or two (see the publisher lines below)."


def stop_run(app_cfg: AppConfig) -> str:
    """Stops the driver and the round robin, then the servers they leave behind (a stopped process can't clean up).
    The games in progress are lost; the next start replays them."""
    pid = driver_pid()
    if pid:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
        DRIVER_PID.unlink(missing_ok=True)
    showdown = ShowdownServerManager(app_cfg.server)
    showdown.stop()
    showdown.run_file.unlink(missing_ok=True)
    for orphan in _listeners(app_cfg.server.port):  # a server whose parent died outside our PID file
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(orphan)], capture_output=True, creationflags=NO_WINDOW)
    for port in local_servers.running(app_cfg):
        local_servers.stop(app_cfg, port)
    with open(RUNS / "roundrobin-publisher.log", "a", encoding="utf-8") as log:
        log.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} stopped from the run monitor\n")
    return "Stopped the round robin, the Showdown server and the local model servers." if pid else \
        "No run was going; stopped any servers left behind."


def _listeners(port: int) -> list:
    """PIDs listening on this local port (netstat)."""
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    return sorted({int(m.group(1)) for m in re.finditer(rf"^\s*TCP\s+\S+:{port}\s+\S+\s+LISTENING\s+(\d+)", out, re.MULTILINE)})


RELAY_PID = RUNS / "relay" / "pid"


def relay_pid() -> Optional[int]:
    """The relay games' process while it runs."""
    try:
        pid = int(RELAY_PID.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if _alive(pid) else None


def start_relay(config_id: str, games: int) -> str:
    """Plays `games` games of `config_id` answered by hand (rotomarena ladder relay), beside any round robin."""
    if relay_pid():
        return "Relay games are already going."
    if not re.fullmatch(r"[a-z0-9_]+", config_id) or not 1 <= games <= 30:
        return "Pick a model and 1-30 games."
    RELAY_PID.parent.mkdir(parents=True, exist_ok=True)
    log = open(RUNS / "relay" / "relay.log", "a", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "rotomarena.cli", "ladder", "relay", config_id, "--games", str(games)],
                            cwd=ROOT, stdout=log, stderr=log, creationflags=NO_WINDOW | NEW_GROUP, close_fds=True)
    RELAY_PID.write_text(str(proc.pid))
    return f"Started {games} relay game(s) of {config_id}. Prompts appear in the Relay panel."


def stop_relay() -> str:
    """Stops the relay games; the one in progress is lost (it isn't saved)."""
    pid = relay_pid()
    if not pid:
        return "No relay games are going."
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
    RELAY_PID.unlink(missing_ok=True)
    for leftover in (RUNS / "relay").glob("*.json"):  # prompts nobody will answer now
        leftover.unlink(missing_ok=True)
    return "Stopped the relay games."
