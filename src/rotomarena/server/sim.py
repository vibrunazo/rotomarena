"""Battles in Pokémon Showdown's simulator, without its chat server.

The server is a chat site around the simulator: logins, usernames, rooms, challenges. Our players don't need any of
that, and it cost us: lane numbers in names, a test game signing in as a ladder player and crashing the run,
challenge races, one shared server that test games must not disturb. Here one Node process (sim_driver.js) runs the
simulator for any number of battles at once, and each side's messages go straight to that player's poke-env
handler, as if a server had sent them; what the player sends back (its /choose and /team commands) becomes its
choice. Agents, prompts and battle state are unchanged. Battles are seeded, so a game replays exactly from its seed
and choices.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DRIVER = Path(__file__).with_name("sim_driver.js")
_ids = itertools.count(1)


@dataclass
class SimBattle:
    """One battle's messages as they arrive, and the simulator's summary at the end."""

    tag: str
    inbox: Dict[str, asyncio.Queue] = field(default_factory=dict)  # side -> what that player receives
    spectator: List[str] = field(default_factory=list)  # the public log (what a replay shows)
    omniscient: List[str] = field(default_factory=list)  # both sides' private lines too
    end: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


class Simulator:
    """Showdown's simulator in one Node process: start it once, play many battles at once, close it."""

    def __init__(self, server_dir: str | Path):
        self.server_dir = Path(server_dir).resolve()
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._battles: Dict[str, SimBattle] = {}
        self._reader: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "Simulator":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def start(self) -> None:
        if self._proc and self._proc.returncode is None:
            return
        from rotomarena.server.manager import install_custom_formats

        install_custom_formats(self.server_dir)  # RotomArena's formats, where the simulator loads them
        self._proc = await asyncio.create_subprocess_exec(
            "node", str(DRIVER), str(self.server_dir),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=64 * 1024 * 1024,  # a battle's summary carries its whole log on one line
        )
        self._reader = asyncio.create_task(self._read())

    async def close(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
        if self._reader:
            self._reader.cancel()
        for battle in self._battles.values():  # nothing more will arrive
            battle.error = battle.error or "the simulator stopped"
            battle.done.set()

    async def _send(self, message: Dict[str, Any]) -> None:
        if not self._proc or self._proc.returncode is not None:
            raise RuntimeError("The simulator isn't running")
        async with self._lock:
            self._proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()

    async def _read(self) -> None:
        assert self._proc and self._proc.stdout
        async for raw in self._proc.stdout:
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            battle = self._battles.get(message.get("id"))
            if battle is None:
                continue
            to = message.get("to")
            if to in battle.inbox:
                if message["data"]:
                    battle.inbox[to].put_nowait(message["data"])
            elif to == "spectator":
                battle.spectator.extend(line for line in message["data"].split("\n") if line)
            elif to == "omniscient":
                battle.omniscient.extend(line for line in message["data"].split("\n") if line)
            elif "end" in message:
                battle.end = message["end"]
                battle.done.set()
            elif "error" in message:
                battle.error = message["error"]
                battle.done.set()
        stderr = (await self._proc.stderr.read()).decode("utf-8", "replace") if self._proc.stderr else ""
        for battle in self._battles.values():
            if not battle.done.is_set():
                battle.error = f"the simulator exited: {stderr[-500:]}"
                battle.done.set()

    async def play(self, p1: Any, p2: Any, formatid: str, seed: Optional[Any] = None,
                   timeout: Optional[float] = None) -> SimBattle:
        """Plays one battle between two poke-env players (p1 and p2 as given) with their current teams. Returns
        when it ends; each player's poke-env battle object is then finished, as after a server game."""
        tag = f"battle-{formatid}-{os.getpid()}{int(time.time())}{next(_ids)}"
        battle = SimBattle(tag=tag, inbox={"p1": asyncio.Queue(), "p2": asyncio.Queue()})
        self._battles[tag] = battle
        sides = {"p1": p1, "p2": p2}
        for side, player in sides.items():
            _route(player, tag, self, side)
        start: Dict[str, Any] = {"formatid": formatid}
        if seed is not None:
            start["seed"] = seed
        await self._send({"id": tag, "start": start, "players": {
            side: {"name": player.username, **({"team": player.next_team} if player.next_team else {})}
            for side, player in sides.items()
        }})
        feeders = [asyncio.create_task(_feed(player, battle, side)) for side, player in sides.items()]
        try:
            ended = asyncio.create_task(battle.done.wait())
            done, _ = await asyncio.wait([ended, *feeders], timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not ended and task.exception():
                    raise task.exception()  # a player failed: abandon the battle
            if not done:
                raise asyncio.TimeoutError(f"{tag} did not end within {timeout} s")
            if battle.error:
                raise RuntimeError(f"Simulator error in {tag}: {battle.error[-1000:]}")
            # the end arrives after the last lines; let both players read them (the |win| line finishes their battles)
            for side in sides:
                await battle.inbox[side].join()
            return battle
        except BaseException:
            await self._send({"id": tag, "close": True})
            raise
        finally:
            for task in feeders:
                task.cancel()
            for side, player in sides.items():
                _unroute(player, tag)
            self._battles.pop(tag, None)


async def _feed(player: Any, battle: SimBattle, side: str) -> None:
    """Hands one side's messages to its player in order, as a server connection would: room header first, and
    the battle's opening |init| line (the server adds it; the simulator doesn't) with the first message."""
    first = True
    inbox = battle.inbox[side]
    while True:
        data = await inbox.get()
        try:
            head = f">{battle.tag}\n" + ("|init|battle\n" if first else "")
            first = False
            await player._handle_battle_message([line.split("|") for line in (head + data).split("\n")])
        finally:
            inbox.task_done()


def _route(player: Any, tag: str, sim: Simulator, side: str) -> None:
    """Sends what the player says in this battle's room to the simulator: '/choose move 1' and '/team 123' become
    its choices; everything else (chat, /leave, /timer) had a server to talk to and is dropped."""
    client = player.ps_client
    routes = getattr(client, "_sim_routes", None)
    if routes is None:
        routes = client._sim_routes = {}
        server_send = client.send_message

        async def send_message(message: str, room: str = "", message_2: Optional[str] = None) -> None:
            target = client._sim_routes.get(room)
            if target is None:
                about_ours = message.startswith("/leave ") and message[len("/leave "):] in client._sim_routes
                if about_ours or getattr(client, "websocket", None) is None:  # no server to tell
                    return
                return await server_send(message, room, message_2)
            to_sim, to_side = target
            if message.startswith("/choose "):
                await to_sim._send({"id": room, "side": to_side, "choice": message[len("/choose "):]})
            elif message.startswith("/team "):
                await to_sim._send({"id": room, "side": to_side, "choice": message[1:]})

        client.send_message = send_message
    routes[tag] = (sim, side)


def _unroute(player: Any, tag: str) -> None:
    getattr(player.ps_client, "_sim_routes", {}).pop(tag, None)
