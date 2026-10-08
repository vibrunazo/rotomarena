"""The run monitor's web server: the page, /api/status (cached for a few seconds, since every page on the LAN
polls it), and live battles: /watch/<room> plays a battle in Showdown's player and /api/battle/<room> hands it the
new log lines. Read-only."""

from __future__ import annotations

import asyncio
import html
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple

from rotomarena.config import AppConfig
from rotomarena.dashboard.relay import relay
from rotomarena.dashboard.status import live_battles, status

PAGE = Path(__file__).with_name("page.html")
WATCH = Path(__file__).with_name("watch.html")
ROOM = re.compile(r"^battle-[a-z0-9]+-\d+$")
CACHE_SECONDS = 10


def serve(config_file: str, host: str, port: int) -> None:
    lock = threading.Lock()
    cache: Dict[str, Tuple[float, bytes]] = {}
    app = AppConfig.load(config_file)
    battles = relay(app.server.websocket_url)
    live_dir = Path(app.telemetry.output_dir) / "live"

    def thoughts(room: str, start: int) -> list:
        """The players' decisions in this battle so far (written by the run as it plays), from `start`."""
        try:
            rows = (live_dir / f"{room}.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for row in rows[start:]:
            try:
                out.append(json.loads(row))
            except ValueError:
                break  # a line still being written: fetch it next time
        return out

    def watch_page(room: str) -> bytes:
        lines, _, joined = battles.lines(room)
        for _ in range(30):  # the first ask joins the room; wait for its log
            if joined:
                break
            time.sleep(0.1)
            lines, _, joined = battles.lines(room)
        players = {l.split("|")[2]: l.split("|")[3] for l in lines if l.startswith("|player|") and len(l.split("|")) > 3}
        title = " vs ".join(players.get(p, "?") for p in ("p1", "p2")) if players else room
        page = (WATCH.read_text(encoding="utf-8")
                .replace("__TITLE__", html.escape(title))
                .replace("__ROOM_JSON__", json.dumps(room))
                .replace("__COUNT__", str(len(lines)))
                # Showdown's convention for a log inlined in <script>: "/" becomes "\/", so it can't close the tag
                .replace("__LOG__", "\n".join(lines).replace("/", "\\/")))
        return page.encode("utf-8")

    def current() -> bytes:
        with lock:
            hit = cache.get("status")
            if hit and time.time() - hit[0] < CACHE_SECONDS:
                return hit[1]
            app_cfg = AppConfig.load(config_file)  # re-read: models join and leave between runs
            data: Dict[str, Any] = status(app_cfg)
            data["live"] = asyncio.run(live_battles(app_cfg))
            body = json.dumps(data).encode("utf-8")
            cache["status"] = (time.time(), body)
            return body

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
            path = self.path.split("?")[0].rstrip("/")
            if path in ("", "/index.html"):
                self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
            elif path.startswith("/watch/") and ROOM.match(path[len("/watch/"):]):
                self._send(200, "text/html; charset=utf-8", watch_page(path[len("/watch/"):]))
            elif path.startswith("/api/battle/") and ROOM.match(path[len("/api/battle/"):]):
                query = self.path.partition("?")[2]
                start = int(m.group(1)) if (m := re.search(r"(?:^|&)from=(\d+)", query)) else 0
                tstart = int(m.group(1)) if (m := re.search(r"(?:^|&)tfrom=(\d+)", query)) else 0
                room = path[len("/api/battle/"):]
                lines, ended, _ = battles.lines(room, start)
                body = {"lines": lines, "ended": ended, "thoughts": thoughts(room, tstart)}
                self._send(200, "application/json", json.dumps(body).encode("utf-8"))
            elif path == "/api/status":
                try:
                    self._send(200, "application/json", current())
                except Exception as e:  # report it on the page instead of dropping the connection
                    self._send(500, "application/json", json.dumps({"error": str(e)}).encode("utf-8"))
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, code: int, kind: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:  # quiet: every open page polls every 15 s
            pass

    ThreadingHTTPServer((host, port), Handler).serve_forever()
