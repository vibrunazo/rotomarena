"""Starts and stops the Smooth Generator's local llama.cpp servers (`gen llm ...`) around each game."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from rotomarena.config import AgentConfig, AppConfig


def _gen(app_cfg: AppConfig, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, app_cfg.local_llm.gen, "llm", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def running(app_cfg: AppConfig) -> Dict[int, str]:
    """{port: model alias} of the servers `gen llm status` reports as ready."""
    return {port: model for port, (model, _) in _status(app_cfg).items()}


def _status(app_cfg: AppConfig) -> Dict[int, Tuple[str, str]]:
    """{port: (model alias, "reasoning <mode> budget <n>")} of the ready servers."""
    out = _gen(app_cfg, "status").stdout
    return {int(port): (model, settings) for port, model, settings in re.findall(
        r"^port (\d+): (\S+) .*?(reasoning \S+ budget -?\d+)?, since .*: ready$", out, re.MULTILINE)}


def _reasoning_settings(app_cfg: AppConfig) -> str:
    """How `gen llm status` describes a server started for this ruleset (see _serve_args)."""
    if app_cfg.ruleset.reasoning == "off":
        return "reasoning off budget -1"
    return f"reasoning auto budget {app_cfg.ruleset.thinking_budget or app_cfg.ruleset.max_output_tokens // 2}"


def catalog_sizes(app_cfg: AppConfig) -> Dict[str, float]:
    """Model file sizes (GB) from the generator's catalog, used to start the smaller model first."""
    path = Path(app_cfg.local_llm.gen).parent / "tools" / "llm" / "llamacpp" / "models.json"
    try:
        models = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v.get("size_gb", 0.0) for k, v in models.items() if isinstance(v, dict)}


def cpu_load() -> Optional[int]:
    """Current CPU load in percent (Windows), or None if it can't be read."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average"],
            capture_output=True, text=True, timeout=20, check=False,
        ).stdout.strip()
        return int(float(out))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


@contextmanager
def session(app_cfg: AppConfig) -> Iterator[None]:
    """Stops every local server before and after a run. A server left from an interrupted run keeps generating
    the answer its dead client asked for (minutes at 1 tok/s), and the new run's requests queue behind it."""
    if app_cfg.local_llm.manage:
        _gen(app_cfg, "stop")
        load = cpu_load()
        if load is not None and load > 30:
            print(f"Warning: the CPU is already {load}% busy. Local models that don't fit in VRAM run partly on the "
                  "CPU and will be much slower (Qwen fell from 7 to 0.4 tok/s next to another heavy job).")
    try:
        yield
    finally:
        if app_cfg.local_llm.manage:
            _gen(app_cfg, "stop")


# Swap mode: {port: model} of a pair too big to share the GPU, and which of them is loaded right now.
_swap: Dict[int, str] = {}
_swap_cfg: Optional[AppConfig] = None
_loaded: Optional[int] = None


def swapping() -> bool:
    return bool(_swap)


_load_lock: Optional[asyncio.Lock] = None
_load_lock_loop: Optional[asyncio.AbstractEventLoop] = None


def _loading() -> asyncio.Lock:
    """One load at a time, per event loop (`ladder place-all` runs one loop per model)."""
    global _load_lock, _load_lock_loop
    loop = asyncio.get_running_loop()
    if _load_lock is None or _load_lock_loop is not loop:
        _load_lock, _load_lock_loop = asyncio.Lock(), loop
    return _load_lock


async def ensure_loaded(port: int) -> None:
    """In swap mode, makes the server on `port` the one that is loaded. Call it inside the local gate (only one
    model's requests run at a time); parallel requests for that model wait for a single load. The subprocess runs
    in a thread so the event loop (and the Showdown connections) keep going."""
    if port not in _swap or _loaded == port:
        return
    async with _loading():
        await _load(port)


async def _load(port: int) -> None:
    global _loaded
    if _loaded == port:
        return
    if _loaded is not None:
        await asyncio.to_thread(_gen, _swap_cfg, "stop", "--port", str(_loaded))
        _loaded = None
    result = await asyncio.to_thread(_gen, _swap_cfg, *_serve_args(_swap_cfg, _swap[port], port))
    if result.returncode != 0:
        raise RuntimeError(f"gen llm serve --model {_swap[port]} --port {port} failed:\n{result.stdout}{result.stderr}")
    _loaded = port


def forget(port: int) -> None:
    """After a failed request: reload the server next time instead of assuming it is up."""
    global _loaded
    if _loaded == port:
        _loaded = None


def _serve_args(app_cfg: AppConfig, model: str, port: int) -> List[str]:
    """`gen llm serve` arguments for an arena server under the ruleset being played."""
    args = ["serve", "--model", model, "--port", str(port),
            "--ctx", str(app_cfg.local_llm.ctx), "--slots", str(app_cfg.ladder.parallel_games)]
    if app_cfg.ruleset.reasoning == "off":
        return args + ["--reasoning", "off"]
    # Thinking on (each request asks for it); at half the output cap llama.cpp tells the model to stop
    # thinking, which leaves the other half for the answer instead of cutting it off.
    budget = app_cfg.ruleset.thinking_budget or app_cfg.ruleset.max_output_tokens // 2
    return args + ["--reasoning", "auto", "--reasoning-budget", str(budget)]


def stop(app_cfg: AppConfig, port: int) -> None:
    _gen(app_cfg, "stop", "--port", str(port))


def local_agents(agents: List[AgentConfig]) -> List[AgentConfig]:
    return [a for a in agents if a.type == "direct_llm" and a.provider == "local" and a.port]


def prepare(players: List[AgentConfig], app_cfg: AppConfig, log: Callable[[str], None] = print) -> None:
    """Leaves exactly the servers these players need running: stops the rest (to free memory), then starts
    any that are missing or crashed, smallest model first, so it gets the VRAM and the bigger one fits around it."""
    global _swap, _swap_cfg, _loaded
    if not app_cfg.local_llm.manage:
        return
    needed = {a.port: a.model for a in local_agents(players)}
    sizes = catalog_sizes(app_cfg)
    # A server started under other rules (another thinking budget) counts as the wrong server: it is restarted.
    current = {port: model for port, (model, settings) in _status(app_cfg).items()
               if settings == _reasoning_settings(app_cfg)}
    for port, (model, settings) in _status(app_cfg).items():
        if port not in current:
            log(f"Stopping local server {model} on port {port} (started with other thinking settings: {settings or '?'})")
            _gen(app_cfg, "stop", "--port", str(port))
    if len(needed) == 2 and sum(sizes.get(m, 99.0) for m in needed.values()) > app_cfg.local_llm.vram_budget_gb:
        for port, model in current.items():
            log(f"Stopping local server {model} on port {port}")
            _gen(app_cfg, "stop", "--port", str(port))
        if _swap != needed:
            log(f"{' and '.join(needed.values())} don't fit on the GPU together: loading whichever one's turn it is")
        _swap, _swap_cfg, _loaded = dict(needed), app_cfg, None
        return
    _swap, _swap_cfg, _loaded = {}, None, None
    for port, model in current.items():
        if needed.get(port) != model:
            log(f"Stopping local server {model} on port {port}")
            _gen(app_cfg, "stop", "--port", str(port))
    for port, model in sorted(needed.items(), key=lambda item: sizes.get(item[1], 0.0)):
        if current.get(port) == model:
            continue
        _gen(app_cfg, "stop", "--port", str(port))  # clears a crashed server's leftovers
        log(f"Starting local server {model} on port {port}")
        result = _gen(app_cfg, *_serve_args(app_cfg, model, port))
        if result.returncode != 0:
            raise RuntimeError(f"gen llm serve --model {model} --port {port} failed:\n{result.stdout}{result.stderr}")
