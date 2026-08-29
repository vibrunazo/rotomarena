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
