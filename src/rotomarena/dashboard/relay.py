"""Live battles for the run monitor: one spectator connection to the Showdown server, joined to a battle only while
someone watches it. Each watched battle's log is buffered here and handed out by line number, so the watch page can
start from the whole log and then fetch only new lines. A spectator sees what any spectator sees; the bots don't
notice it, and nothing they wait on goes through here."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import websockets

IDLE_SECONDS = 60  # leave a battle nobody has asked about for this long


@dataclass
class _Room:
    lines: List[str] = field(default_factory=list)
    last_asked: float = 0.0
    joined: bool = False
    ended: bool = False


class Relay:
    def __init__(self, websocket_url: str):
        self.url = websocket_url
        self.rooms: Dict[str, _Room] = {}
        self.lock = threading.Lock()
        self.loop = asyncio.new_event_loop()
        self.ws = None
        threading.Thread(target=self._run, daemon=True).start()

    def lines(self, room: str, start: int = 0) -> Tuple[List[str], bool, bool]:
        """(the room's log lines from `start`, whether the battle ended, whether we are joined yet). Asking keeps
        the room joined; the first ask joins it."""
        with self.lock:
            r = self.rooms.setdefault(room, _Room())
            r.last_asked = time.time()
            if not r.joined:
                asyncio.run_coroutine_threadsafe(self._send(f"|/join {room}"), self.loop)
            return r.lines[start:], r.ended, r.joined

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _send(self, message: str) -> None:
        if self.ws is not None:
            try:
                await self.ws.send(message)
            except Exception:
                pass

    async def _main(self) -> None:
        while True:  # reconnect when the server restarts between runs
            try:
                async with websockets.connect(self.url, max_size=None) as ws:
                    self.ws = ws
                    with self.lock:
                        for r in self.rooms.values():
                            r.joined = False
                    janitor = asyncio.create_task(self._janitor())
                    try:
                        async for message in ws:
                            self._receive(message)
                    finally:
                        janitor.cancel()
            except Exception:
                pass
            self.ws = None
            await asyncio.sleep(5)

    def _receive(self, message: str) -> None:
        if not message.startswith(">"):
            return
        head, _, body = message.partition("\n")
        room = head[1:].strip()
        with self.lock:
            r = self.rooms.get(room)
            if r is None:
                return
            lines = body.split("\n")
            if "|init|battle" in lines:  # joining sends the whole log so far
                r.lines, r.joined = [], True
            if "|deinit" in lines or any(l.startswith("|noinit|") for l in lines):
                r.ended = True
                r.joined = True
                lines = [l for l in lines if l != "|deinit"]
            r.lines.extend(l for l in lines if l and not l.startswith("|init|"))
            if any(l.startswith("|win|") or l == "|tie" for l in lines):
                r.ended = True

    async def _janitor(self) -> None:
        while True:
            await asyncio.sleep(15)
            now = time.time()
            with self.lock:
                idle = [k for k, r in self.rooms.items() if now - r.last_asked > IDLE_SECONDS]
                for k in idle:
                    del self.rooms[k]
            for k in idle:
                await self._send(f"{k}|/leave")


_relay: Optional[Relay] = None


def relay(websocket_url: str) -> Relay:
    global _relay
    if _relay is None:
        _relay = Relay(websocket_url)
    return _relay
