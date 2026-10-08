"""The run monitor's web server: the page and /api/status (cached for a few seconds, since every page on the LAN
polls it). Read-only."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple

from rotomarena.config import AppConfig
from rotomarena.dashboard.status import live_battles, status

PAGE = Path(__file__).with_name("page.html")
CACHE_SECONDS = 10


def serve(config_file: str, host: str, port: int) -> None:
    lock = threading.Lock()
    cache: Dict[str, Tuple[float, bytes]] = {}

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
