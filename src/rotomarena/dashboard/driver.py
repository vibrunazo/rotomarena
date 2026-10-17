"""Runs the round robin and publishes the standings to the site (export, commit site/src/data, push) when it ends.
In between, the site is published only on request: the run monitor's Publish button, or `python -m
rotomarena.dashboard.driver --publish`. Every push is a site build, and builds are what the host's free tier counts
(17 Oct: a 45-minute timer had used 75% of Netlify's month by the 17th). Started by the run monitor's Start button
(or `python -m rotomarena.dashboard.driver`); stopped by its Stop button. Logs to runs/roundrobin*.log."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "runs"
DRIVER_PID = RUNS / "driver.pid"
ROUND_ROBIN_PID = RUNS / "roundrobin.pid"
GAMES_PER_PAIR = 3   # every pair plays three games (10 Oct: was 2; a 1-1 told nothing)
STALLED = 4          # the round robin's exit code when its games stopped making progress
MAX_RESTARTS = 10    # stalls in a row the driver restarts before giving up
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: children never open a console

env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
uv = shutil.which("uv") or "uv"


def say(msg: str) -> None:
    with open(RUNS / "roundrobin-publisher.log", "a", encoding="utf-8") as log:
        log.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} {msg}\n")


def run(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=NO_WINDOW)


def publish(final: bool) -> None:
    export = run(uv, "run", "rotomarena", "export-site", "--out", "site/src/data")
    say(f"export: {export.stdout.strip().splitlines()[0] if export.stdout.strip() else export.stderr[-300:]}")
    run("git", "add", "site/src/data")
    if run("git", "diff", "--cached", "--quiet").returncode == 0:
        say("nothing new to publish")
        return
    games = export.stdout.split("matches (")[1].split(" rated")[0] if "matches (" in export.stdout else "?"
    title = f"data: own-teams round robin, {games} rated games overall" + (" (run ended)" if final else "")
    commit = run("git", "commit", "-q", "-m", title)
    push = run("git", "push", "-q")
    say(f"published: {title} (commit {commit.returncode}, push {push.returncode} {push.stderr.strip()[:200]})")


def main() -> None:
    RUNS.mkdir(exist_ok=True)
    DRIVER_PID.write_text(str(os.getpid()))
    for attempt in range(MAX_RESTARTS + 1):
        say("starting round robin" if attempt == 0 else f"restarting the stalled round robin ({attempt}/{MAX_RESTARTS})")
        with open(RUNS / "roundrobin.log", "a", encoding="utf-8") as out, \
                open(RUNS / "roundrobin.err", "a", encoding="utf-8") as err:
            proc = subprocess.Popen([uv, "run", "rotomarena", "ladder", "round-robin", "--games-per-pair", str(GAMES_PER_PAIR)],
                                    cwd=ROOT, env=env, stdout=out, stderr=err, creationflags=NO_WINDOW)
            ROUND_ROBIN_PID.write_text(str(proc.pid))
            while proc.poll() is None:
                time.sleep(60)
        if proc.returncode != STALLED:
            break
        say("round robin stalled (no decision for ladder.stall_minutes); its stuck games will be replayed")
    say(f"round robin exited with {proc.returncode}")
    publish(final=True)
    say("done")
    DRIVER_PID.unlink(missing_ok=True)


if __name__ == "__main__":
    if "--publish" in sys.argv:
        publish(final=False)
    else:
        main()
