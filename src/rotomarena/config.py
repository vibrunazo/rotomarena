"""Configuration models and loader for RotomArena."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


class ServerConfig(BaseModel):
    """Configuration for the local Pokémon Showdown server."""

    host: str = Field(default="127.0.0.1", description="Server hostname")
    port: int = Field(default=8000, description="Server port")
    websocket_path: str = Field(
        default="/showdown/websocket", description="WebSocket endpoint path"
    )
    action_path: str = Field(
        default="/action.php?", description="Showdown action path"
    )
    no_security: bool = Field(
        default=True, description="Disable auth for local bots"
    )
    auto_start: bool = Field(
        default=True, description="Automatically launch server if not running"
    )
    server_dir: Path = Field(
        default=Path("server/pokemon-showdown"),
        description="Path to Pokémon Showdown repository",
    )

    @property
    def websocket_url(self) -> str:
        return f"ws://{self.host}:{self.port}{self.websocket_path}"

    @property
    def http_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class ProviderConfig(BaseModel):
    """Configuration for an LLM provider."""

    base_url: str = Field(..., description="OpenAI-compatible base URL")
    api_key: Optional[str] = Field(default=None, description="Direct API key")
    api_key_env: Optional[str] = Field(
        default=None, description="Env variable name containing the API key"
    )
    default_model: str = Field(..., description="Default model name")
    temperature: float = Field(default=0.2, description="Sampling temperature")
    timeout: float = Field(default=30.0, description="Request timeout in seconds")

    def get_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            env_val = os.getenv(self.api_key_env, "")
            if env_val:
                return env_val
        # Fallback for common providers
        if "generativelanguage.googleapis.com" in self.base_url:
            return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        if "openrouter.ai" in self.base_url:
            return os.getenv("OPENROUTER_API_KEY", "")
        return "local"


class AgentConfig(BaseModel):
    """Configuration for a benchmark agent."""

    name: str = Field(default="agent", description="Unique agent identifier")
    type: str = Field(
        default="heuristic",
        description="Agent backend type: 'pokechamp', 'direct_llm', 'heuristic', 'random'",
    )
    provider: Optional[str] = Field(
        default=None, description="LLM Provider key (e.g. 'gemini', 'openrouter')"
    )
    model: Optional[str] = Field(
        default=None, description="LLM model override"
    )
    depth: int = Field(
        default=1, description="Minimax search depth (PokéChamp only)"
    )
    use_llm_prior: bool = Field(
        default=False, description="Enable LLM value prior in PokéChamp"
    )
    temperature: float = Field(
        default=0.2, description="LLM temperature override"
    )
    turn_timeout: float = Field(
        default=100.0, description="Per-turn timeout in seconds before automated move fallback"
    )
    bank_timeout: float = Field(
        default=600.0, description="Total match chess-clock time bank in seconds (default: 600s / 10 min)"
    )
    evaluation_weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "alive_pokemon": 3.0,
            "hp_diff": 2.0,
            "status": 1.0,
            "boosts": 0.5,
            "hazards": 0.5,
            "matchup": 1.0,
        }
    )


class TournamentConfig(BaseModel):
    """Configuration for a round-robin tournament."""

    name: str = Field(default="Gen9 OU Tournament")
    format: str = Field(default="gen9ou")
    rounds_per_pair: int = Field(
        default=2, description="Number of games per pair (swapping sides)"
    )
    teams: List[str] = Field(
        default_factory=lambda: ["data/teams/gen9ou_balance.txt"]
    )
    participants: List[str] = Field(default_factory=list)
    initial_elo: float = Field(default=1500.0)
    k_factor: float = Field(default=32.0)


class TelemetryConfig(BaseModel):
    """Telemetry and replay recording settings."""

    output_dir: Path = Field(default=Path("./runs"))
    save_replays: bool = Field(default=True)
    save_breadcrumbs: bool = Field(default=True)
    save_reports: bool = Field(default=True)


class AppConfig(BaseSettings):
    """Top-level application settings."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: Dict[str, ProviderConfig] = Field(default_factory=dict)
    agents: Dict[str, AgentConfig] = Field(default_factory=dict)
    tournament: Optional[TournamentConfig] = Field(default=None)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def load_from_yaml(cls, path: str | Path) -> "AppConfig":
        yaml_path = Path(path)
        if not yaml_path.exists():
            return cls()
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Populate agent names from dict keys if missing
        if "agents" in data and isinstance(data["agents"], dict):
            for agent_name, agent_data in data["agents"].items():
                if isinstance(agent_data, dict) and "name" not in agent_data:
                    agent_data["name"] = agent_name

        return cls(**data)

    @classmethod
    def default_config(cls) -> "AppConfig":
        return cls(
            server=ServerConfig(),
            providers={
                "gemini": ProviderConfig(
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    api_key_env="GEMINI_API_KEY",
                    default_model=os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
                    temperature=0.2,
                ),
                "openrouter": ProviderConfig(
                    base_url="https://openrouter.ai/api/v1",
                    api_key_env="OPENROUTER_API_KEY",
                    default_model="anthropic/claude-3.5-sonnet",
                    temperature=0.2,
                ),
                "ollama": ProviderConfig(
                    base_url="http://localhost:11434/v1",
                    api_key="ollama",
                    default_model="llama3.3:70b",
                    temperature=0.2,
                ),
            },
            agents={
                "pokechamp_d1": AgentConfig(
                    name="pokechamp_d1",
                    type="pokechamp",
                    depth=1,
                    use_llm_prior=False,
                ),
                "pokechamp_d2": AgentConfig(
                    name="pokechamp_d2",
                    type="pokechamp",
                    depth=2,
                    use_llm_prior=False,
                ),
                "direct_llm_gemini": AgentConfig(
                    name="direct_llm_gemini",
                    type="direct_llm",
                    provider="gemini",
                    model="gemini-3.7-flash",
                ),
                "baseline_heuristic": AgentConfig(
                    name="baseline_heuristic",
                    type="heuristic",
                ),
                "baseline_random": AgentConfig(
                    name="baseline_random",
                    type="random",
                ),
            },
            tournament=TournamentConfig(
                participants=["pokechamp_d1", "baseline_heuristic", "baseline_random"]
            ),
            telemetry=TelemetryConfig(),
        )
