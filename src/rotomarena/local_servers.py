"""Starts and stops the Smooth Generator's local llama.cpp servers (`gen llm ...`) around each game."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, List

from rotomarena.config import AgentConfig, AppConfig


def _gen(app_cfg: AppConfig, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, app_cfg.local_llm.gen, "llm", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def running(app_cfg: AppConfig) -> Dict[int, str]:
    """{port: model alias} of the servers `gen llm status` reports as ready."""
    out = _gen(app_cfg, "status").stdout
    return {int(port): model for port, model in re.findall(r"^port (\d+): (\S+) .*: ready$", out, re.MULTILINE)}


def catalog_sizes(app_cfg: AppConfig) -> Dict[str, float]:
    """Model file sizes (GB) from the generator's catalog, used to start the smaller model first."""
    path = Path(app_cfg.local_llm.gen).parent / "tools" / "llm" / "llamacpp" / "models.json"
    try:
        models = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v.get("size_gb", 0.0) for k, v in models.items() if isinstance(v, dict)}


@contextmanager
def session(app_cfg: AppConfig) -> Iterator[None]:
    """Stops every local server before and after a run. A server left from an interrupted run keeps generating
    the answer its dead client asked for (minutes at 1 tok/s), and the new run's requests queue behind it."""
    if app_cfg.local_llm.manage:
        _gen(app_cfg, "stop")
    try:
        yield
    finally:
        if app_cfg.local_llm.manage:
            _gen(app_cfg, "stop")


def local_agents(agents: List[AgentConfig]) -> List[AgentConfig]:
    return [a for a in agents if a.type == "direct_llm" and a.provider == "local" and a.port]


def prepare(players: List[AgentConfig], app_cfg: AppConfig, log: Callable[[str], None] = print) -> None:
    """Leaves exactly the servers these players need running: stops the rest (to free memory), then starts
    any that are missing or crashed, smallest model first, so it gets the VRAM and the bigger one fits around it."""
    if not app_cfg.local_llm.manage:
        return
    needed = {a.port: a.model for a in local_agents(players)}
    current = running(app_cfg)
    for port, model in current.items():
        if needed.get(port) != model:
            log(f"Stopping local server {model} on port {port}")
            _gen(app_cfg, "stop", "--port", str(port))
    sizes = catalog_sizes(app_cfg)
    for port, model in sorted(needed.items(), key=lambda item: sizes.get(item[1], 0.0)):
        if current.get(port) == model:
            continue
        _gen(app_cfg, "stop", "--port", str(port))  # clears a crashed server's leftovers
        log(f"Starting local server {model} on port {port}")
        result = _gen(app_cfg, "serve", "--model", model, "--port", str(port),
                      "--ctx", str(app_cfg.local_llm.ctx), "--slots", str(app_cfg.local_llm.slots))
        if result.returncode != 0:
            raise RuntimeError(f"gen llm serve --model {model} --port {port} failed:\n{result.stdout}{result.stderr}")
