"""Starts and stops the Smooth Generator's local llama.cpp servers (`gen llm ...`) around each series."""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Callable, Dict, List

from rotomarena.config import AgentConfig, AppConfig


def _gen(app_cfg: AppConfig, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, app_cfg.local_llm.gen, "llm", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def running(app_cfg: AppConfig) -> Dict[int, str]:
    """{port: model alias} of the servers `gen llm status` reports."""
    out = _gen(app_cfg, "status").stdout
    return {int(port): model for port, model in re.findall(r"^port (\d+): (\S+)", out, re.MULTILINE)}


def local_agents(agents: List[AgentConfig]) -> List[AgentConfig]:
    return [a for a in agents if a.type == "direct_llm" and a.provider == "local" and a.port]


def prepare(players: List[AgentConfig], app_cfg: AppConfig, log: Callable[[str], None] = print) -> None:
    """Leaves exactly the servers these players need running: stops the rest (to free memory), then starts
    any that are missing, one at a time so each fits into what the previous one left."""
    if not app_cfg.local_llm.manage:
        return
    needed = {a.port: a.model for a in local_agents(players)}
    current = running(app_cfg)
    for port, model in current.items():
        if needed.get(port) != model:
            log(f"Stopping local server {model} on port {port}")
            _gen(app_cfg, "stop", "--port", str(port))
    for port, model in needed.items():
        if current.get(port) == model:
            continue
        log(f"Starting local server {model} on port {port}")
        result = _gen(app_cfg, "serve", "--model", model, "--port", str(port))
        if result.returncode != 0:
            raise RuntimeError(f"gen llm serve --model {model} --port {port} failed:\n{result.stdout}{result.stderr}")
