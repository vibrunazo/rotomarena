"""Local Pokémon Showdown Server Lifecycle Manager."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import AsyncIterator, Dict, Optional, Tuple
from contextlib import asynccontextmanager

import websockets
from rotomarena.config import ServerConfig
from rotomarena.server.config_template import generate_showdown_config


class ShowdownServerManager:
    """Manages the local headless Pokémon Showdown Node.js server."""

    def __init__(self, config: Optional[ServerConfig] = None):
        self.config = config or ServerConfig()
        self.server_dir = Path(self.config.server_dir).resolve()
        self.pid_file = self.server_dir.parent / "showdown.pid"
        self.run_file = self.server_dir.parent / "showdown.run"  # the PID of the run playing on the server
        self.log_file = self.server_dir.parent / "showdown_server.log"
        self._process: Optional[subprocess.Popen] = None
        self._ensure_node_on_path()

    def find_node_executable(self) -> Optional[str]:
        """Locate the Node.js executable on the host system."""
        # 1. PATH lookup
        node = shutil.which("node")
        if node:
            return node

        # 2. Dynamic environment path discovery
        if sys.platform == "win32":
            env_dirs = [
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramFiles(x86)"),
                os.environ.get("LOCALAPPDATA"),
                os.environ.get("APPDATA"),
                os.environ.get("USERPROFILE"),
            ]
            for base in env_dirs:
                if not base:
                    continue
                p_base = Path(base)
                for candidate in (
                    p_base / "nodejs" / "node.exe",
                    p_base / "Programs" / "node" / "node.exe",
                    p_base / "Programs" / "nodejs" / "node.exe",
                    p_base / "nvm" / "current" / "node.exe",
                ):
                    if candidate.exists():
                        return str(candidate)

        return None

    def find_npm_executable(self) -> Optional[str]:
        """Locate the npm executable on the host system."""
        npm = shutil.which("npm")
        if npm:
            return npm

        if sys.platform == "win32":
            env_dirs = [
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramFiles(x86)"),
                os.environ.get("APPDATA"),
                os.environ.get("LOCALAPPDATA"),
                os.environ.get("USERPROFILE"),
            ]
            for base in env_dirs:
                if not base:
                    continue
                p_base = Path(base)
                for candidate in (
                    p_base / "nodejs" / "npm.cmd",
                    p_base / "npm" / "npm.cmd",
                    p_base / "Programs" / "nodejs" / "npm.cmd",
                ):
                    if candidate.exists():
                        return str(candidate)

        return None

    def _ensure_node_on_path(self) -> None:
        """Ensures the Node.js directory is prepended to the system PATH."""
        node = self.find_node_executable()
        if node:
            node_dir = str(Path(node).parent)
            for key in ("PATH", "Path", "path"):
                if key in os.environ:
                    curr = os.environ[key]
                    if node_dir.lower() not in curr.lower():
                        os.environ[key] = f"{node_dir}{os.pathsep}{curr}"

    def get_subprocess_env(self) -> Dict[str, str]:
        """Generate environment dictionary with Node.js directory in PATH."""
        self._ensure_node_on_path()
        return os.environ.copy()

    def is_git_available(self) -> bool:
        """Check if Git is installed and available."""
        return shutil.which("git") is not None

    def setup(self, force_reclone: bool = False) -> Tuple[bool, str]:
        """Clone Showdown repository, install dependencies, and generate config."""
        node = self.find_node_executable()
        if not node:
            return (
                False,
                "Node.js is not found on your system. Please install Node.js (e.g. `winget install OpenJS.NodeJS.LTS`).",
            )

        npm = self.find_npm_executable()
        if not npm:
            return (
                False,
                "npm is not found on your system. Please ensure npm is installed alongside Node.js.",
            )

        if not self.is_git_available():
            return False, "Git is required to clone the Pokémon Showdown repository."

        self.server_dir.parent.mkdir(parents=True, exist_ok=True)
        env = self.get_subprocess_env()

        # 1. Clone repository if missing or force_reclone
        if force_reclone and self.server_dir.exists():
            shutil.rmtree(self.server_dir, ignore_errors=True)

        if not self.server_dir.exists():
            repo_url = "https://github.com/smogon/pokemon-showdown.git"
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", repo_url, str(self.server_dir)],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                )
            except subprocess.CalledProcessError as e:
                return False, f"Failed to clone Pokémon Showdown: {e.stderr}"

        # 2. Run npm install
        try:
            subprocess.run(
                [npm, "install"],
                cwd=str(self.server_dir),
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        except subprocess.CalledProcessError as e:
            # Fallback with ignore-scripts if needed
            try:
                subprocess.run(
                    [npm, "install", "--ignore-scripts"],
                    cwd=str(self.server_dir),
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                )
            except subprocess.CalledProcessError:
                return False, f"npm install failed: {e.stderr or e.stdout}"

        # 3. Build Showdown TypeScript assets
        try:
            subprocess.run(
                [node, "build"],
                cwd=str(self.server_dir),
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
        except Exception:
            pass

        # 4. Generate config/config.js with disabled timers and no-security
        self.write_config()

        return True, f"Pokémon Showdown setup successfully completed at {self.server_dir}"

    def write_config(self) -> None:
        """Writes config/config.js from ServerConfig (port, security, bind address)."""
        config_js = self.server_dir / "config" / "config.js"
        config_js.parent.mkdir(parents=True, exist_ok=True)
        config_js.write_text(
            generate_showdown_config(
                port=self.config.port,
                no_security=self.config.no_security,
                bind_address="127.0.0.1" if self.config.host == "localhost" else self.config.host,
            ),
            encoding="utf-8",
        )

    async def is_server_healthy(self, timeout: float = 3.0) -> bool:
        """Check if Showdown WebSocket server is responding."""
        urls = [
            self.config.websocket_url,
            f"ws://127.0.0.1:{self.config.port}{self.config.websocket_path}",
        ]
        for url in urls:
            try:
                async with websockets.connect(
                    url, open_timeout=timeout, close_timeout=timeout
                ) as ws:
                    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    return True
            except Exception:
                continue
        return False

    def start(self) -> Tuple[bool, str]:
        """Start the Showdown server in the background."""
        node = self.find_node_executable()
        if not node:
            return False, "Node.js executable not found. Please install Node.js."

        if not (self.server_dir / "pokemon-showdown").exists() and not (
            self.server_dir / "pokemon-showdown.js"
        ).exists():
            setup_ok, msg = self.setup()
            if not setup_ok:
                return False, f"Server setup failed: {msg}"

        # Check if already running
        if self.is_running():
            return True, f"Showdown server is already running (PID: {self.get_pid()})"

        # Rewrite config.js every start so it always matches ServerConfig
        self.write_config()

        # Launch process
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(self.log_file, "a", encoding="utf-8")

        cmd = [node, "pokemon-showdown", "start", "--skip-build", "--no-security"]
        creationflags = 0
        if sys.platform == "win32":
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            CREATE_NO_WINDOW = 0x08000000
            creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

        env = self.get_subprocess_env()
        self._process = subprocess.Popen(
            cmd,
            cwd=str(self.server_dir),
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=env,
            close_fds=(sys.platform != "win32"),
        )

        # Write PID
        self.pid_file.write_text(str(self._process.pid), encoding="utf-8")
        return True, f"Showdown server started with PID {self._process.pid} (Port {self.config.port})"

    def stop(self) -> Tuple[bool, str]:
        """Stop the running Showdown server."""
        pid = self.get_pid()
        if not pid:
            return True, "Showdown server is not running."

        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    check=False,
                    capture_output=True,
                )
            else:
                os.kill(pid, 15)  # SIGTERM
        except Exception as e:
            return False, f"Failed to stop server PID {pid}: {e}"
        finally:
            if self.pid_file.exists():
                self.pid_file.unlink(missing_ok=True)

        return True, f"Showdown server (PID {pid}) stopped."

    def get_pid(self) -> Optional[int]:
        """Retrieve the PID from the PID file if the process is alive."""
        if not self.pid_file.exists():
            return None
        try:
            pid = int(self.pid_file.read_text(encoding="utf-8").strip())
            if sys.platform == "win32":
                res = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if str(pid) in res.stdout:
                    return pid
                return None
            else:
                os.kill(pid, 0)
                return pid
        except (ValueError, OSError):
            return None

    def is_running(self) -> bool:
        """Check whether the server process is currently running."""
        return self.get_pid() is not None

    async def wait_until_ready(self, max_wait: float = 15.0, poll_interval: float = 0.5) -> bool:
        """Poll until the server responds to WebSocket handshakes."""
        start_t = time.time()
        while time.time() - start_t < max_wait:
            if await self.is_server_healthy(timeout=1.0):
                return True
            await asyncio.sleep(poll_interval)
        return False

    @asynccontextmanager
    async def ensure_running(self) -> AsyncIterator[ShowdownServerManager]:
        """Runs a fresh Showdown server for the duration of a run. A server that is already running may hold
        battles abandoned by an earlier, interrupted run (timers are off, so they never end), and bots logging
        in with the same names would rejoin those instead of playing their own game.
        A server another live run is playing on is left alone: restarting it would void that run's games."""
        owner = self._live_run()
        if owner and owner != os.getpid():
            raise RuntimeError(
                f"Another RotomArena run (PID {owner}) is playing on the Showdown server; restarting it would void "
                f"that run's games. Wait for it to finish, or stop it first."
            )
        if self.is_running():
            self.stop()
            await asyncio.sleep(1.0)
        if await self.is_server_healthy(timeout=1.0):
            raise RuntimeError(
                f"A Showdown server that RotomArena didn't start is answering on port {self.config.port}; stop it first."
            )
        ok, msg = self.start()
        if not ok:
            raise RuntimeError(f"Could not start Showdown server: {msg}")
        if not await self.wait_until_ready(max_wait=30.0):
            raise RuntimeError(f"Showdown server failed health check at {self.config.websocket_url}")
        self.run_file.write_text(str(os.getpid()), encoding="utf-8")
        try:
            yield self
        finally:
            self.stop()
            self.run_file.unlink(missing_ok=True)

    def _live_run(self) -> Optional[int]:
        """The PID of the run playing on the server, if that process is still alive."""
        try:
            pid = int(self.run_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return pid if _alive(pid) else None


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
