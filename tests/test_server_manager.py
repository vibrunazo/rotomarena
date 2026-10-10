"""Tests for Pokémon Showdown server config template and server manager."""

import pytest
from rotomarena.config import ServerConfig
from rotomarena.server.config_template import generate_showdown_config
from rotomarena.server.manager import ShowdownServerManager


def test_generate_showdown_config():
    cfg_text = generate_showdown_config(port=8000, no_security=True)
    assert "exports.port = 8000;" in cfg_text
    assert "exports.no_security = true;" in cfg_text
    assert "exports.forcetimer = false;" in cfg_text
    assert "exports.inactivitytimeout = 0;" in cfg_text
    assert "timer: false" in cfg_text
    assert "exports.bindaddress = '127.0.0.1';" in cfg_text


def test_server_manager_initialization(tmp_path):
    server_cfg = ServerConfig(
        host="127.0.0.1",
        port=8000,
        server_dir=tmp_path / "pokemon-showdown",
    )
    mgr = ShowdownServerManager(server_cfg)
    assert mgr.config.port == 8000
    assert mgr.config.websocket_url == "ws://127.0.0.1:8000/showdown/websocket"
    assert mgr.pid_file == tmp_path / "showdown.pid"


def test_a_run_never_restarts_the_server_another_live_run_plays_on(tmp_path):
    import asyncio
    import os
    import subprocess
    import sys

    import pytest

    from rotomarena.config import ServerConfig
    from rotomarena.server.manager import ShowdownServerManager

    manager = ShowdownServerManager(ServerConfig(server_dir=tmp_path / "pokemon-showdown"))
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        manager.run_file.write_text(str(other.pid))
        with pytest.raises(RuntimeError, match="Another RotomArena run"):
            asyncio.run(manager.ensure_running().__aenter__())
    finally:
        other.kill()
        other.wait()
    assert manager._live_run() is None  # a dead run's file doesn't block the next one
    manager.run_file.write_text(str(os.getpid()))
    assert manager._live_run() == os.getpid()


def test_a_late_completion_on_a_finished_windows_future_is_dropped():
    import asyncio
    import sys

    import pytest

    if sys.platform != "win32":
        pytest.skip("Windows' proactor loop only")
    import rotomarena  # noqa: F401  (applies the fix)
    from asyncio import windows_events

    loop = asyncio.new_event_loop()
    try:
        future = windows_events._OverlappedFuture(ov=None, loop=loop)
        future.cancel()
        future.set_exception(ConnectionResetError("WinError 995"))  # raised InvalidStateError before the fix
        future.set_result(1)
        assert future.cancelled()
    finally:
        loop.close()
