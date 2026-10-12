"""Where games are played: Showdown's simulator directly (server.engine: simulator) or its chat server ("server").
Commands wrap their games in `battles(app_cfg)`; the runner and the player factory ask `simulator()` which one is
active."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from rotomarena.config import AppConfig
from rotomarena.server.sim import Simulator

_active: Optional[Simulator] = None


def simulator() -> Optional[Simulator]:
    """The simulator games are played in, or None when they go through the chat server."""
    return _active


@asynccontextmanager
async def battles(app_cfg: AppConfig, join: bool = False) -> AsyncIterator[None]:
    """Readies where this command's games are played, for as long as it runs. With the chat server, `join` plays
    on the server a live run already has up; the simulator needs no such care (each command runs its own)."""
    global _active
    if app_cfg.server.engine == "simulator":
        async with Simulator(app_cfg.server.server_dir) as sim:
            previous, _active = _active, sim
            try:
                yield
            finally:
                _active = previous
        return
    from rotomarena.server.manager import ShowdownServerManager

    manager = ShowdownServerManager(app_cfg.server)
    async with (manager.joined() if join else manager.ensure_running()):
        yield
