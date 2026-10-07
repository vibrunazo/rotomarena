"""Configuration models and loader for RotomArena."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


AgentType = Literal["pokechamp", "direct_llm", "heuristic", "max_damage", "random"]
AgentRole = Literal["anchor", "sparring", "contestant"]
ReasoningLevel = Literal["off", "low", "medium", "high"]

# Free OpenRouter model used for tests and as the default LLM (see AGENTS.md).
FREE_TEST_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


class ServerConfig(BaseModel):
    """Configuration for the local Pokémon Showdown server."""

    host: str = Field(default="127.0.0.1", description="Server hostname; Showdown also binds to it")
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
    """Configuration for an OpenAI-compatible LLM provider."""

    base_url: str = Field(..., description="OpenAI-compatible base URL")
    api_key: Optional[str] = Field(default=None, description="Direct API key")
    api_key_env: Optional[str] = Field(
        default=None, description="Env variable name containing the API key"
    )
    api_style: Literal["openai", "openrouter", "llama.cpp"] = Field(
        default="openai", description="How reasoning settings are sent to this provider"
    )
    default_model: str = Field(..., description="Default model name")
    temperature: float = Field(default=0.2, description="Sampling temperature")
    timeout: float = Field(default=600.0, description="Request timeout in seconds")

    def get_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.getenv(self.api_key_env, "")
        return "local"


def provider_presets() -> Dict[str, ProviderConfig]:
    """Built-in provider profiles. Environment variables override models and local URLs."""
    return {
        "openrouter": ProviderConfig(
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            api_style="openrouter",
            default_model=os.getenv("OPENROUTER_MODEL", FREE_TEST_MODEL),
        ),
        "local": ProviderConfig(
            base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
            api_key="local",
            api_style="llama.cpp",
            default_model=os.getenv("LOCAL_LLM_MODEL", "bonsai"),
        ),
        "gemini": ProviderConfig(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key_env="GEMINI_API_KEY",
            default_model=os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
        ),
        "ollama": ProviderConfig(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key="ollama",
            default_model=os.getenv("OLLAMA_MODEL", "llama3.3:70b"),
        ),
        # vLLM's own default port (8000) is taken by the Showdown server.
        "vllm": ProviderConfig(
            base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8001/v1"),
            api_key="vllm",
            default_model=os.getenv("VLLM_MODEL", "meta-llama/Llama-3.3-70B-Instruct"),
        ),
    }


class RulesetConfig(BaseModel):
    """Rules shared by every player in a season. Recorded in every match; changing them starts a new season."""

    version: str = Field(default="s1", description="Season / ruleset identifier")
    max_output_tokens: int = Field(
        default=1024, description="Per-turn output budget for LLM players; a cut-off answer forfeits the turn"
    )
    turn_timeout: float = Field(
        default=900.0, description="Wall-clock limit per turn in seconds; only catches hung servers"
    )
    reasoning: ReasoningLevel = Field(
        default="off", description="Hidden reasoning level requested from every LLM"
    )
    teams: List[str] = Field(
        default_factory=lambda: ["balance", "hyper_offense"],
        description="The two teams every ladder set uses (each played from both sides)",
    )


class LadderConfig(BaseModel):
    """How ratings are computed and how many games placement and top-ups play."""

    anchor: str = Field(default="bonsai_2_27b", description="Config id whose rating is fixed")
    anchor_rating: float = Field(default=1500.0)
    games_per_set: int = Field(default=4, description="Games per opponent: 2 teams x 2 sides")
    provisional_games: int = Field(default=16, description="Valid games before a rating stops being provisional")
    max_autopilot: float = Field(
        default=0.5, description="A match is void when either side's fallback share of turns exceeds this"
    )
    bootstrap_samples: int = Field(default=1000)


class AgentConfig(BaseModel):
    """Configuration for a benchmark agent."""

    name: str = Field(default="agent", description="Unique agent identifier (config id)")
    type: AgentType = Field(default="heuristic", description="Agent backend type")
    role: AgentRole = Field(
        default="contestant", description="anchor: fixed reference; sparring: free standing opponent"
    )
    provider: Optional[str] = Field(
        default=None, description="LLM provider key (e.g. 'openrouter', 'local')"
    )
    model: Optional[str] = Field(
        default=None, description="LLM model override"
    )
    quantization: Optional[str] = Field(
        default=None, description="Weights format for local models (e.g. 'Q4_K_M'); part of the model's identity"
    )
    temperature: float = Field(
        default=0.2, description="LLM temperature override"
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


class TelemetryConfig(BaseModel):
    """Telemetry and replay recording settings."""

    output_dir: Path = Field(default=Path("./runs"))
    save_replays: bool = Field(default=True)
    save_breadcrumbs: bool = Field(default=True)
    save_reports: bool = Field(default=True)


class AppConfig(BaseSettings):
    """Top-level application settings."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    ruleset: RulesetConfig = Field(default_factory=RulesetConfig)
    ladder: LadderConfig = Field(default_factory=LadderConfig)
    providers: Dict[str, ProviderConfig] = Field(default_factory=provider_presets)
    agents: Dict[str, AgentConfig] = Field(default_factory=dict)
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

        # Providers named in the file extend the built-in presets instead of replacing them
        if "providers" in data and isinstance(data["providers"], dict):
            data["providers"] = {**provider_presets(), **data["providers"]}

        return cls(**data)

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "AppConfig":
        """The project config (the model registry lives in config.yaml); built-in defaults if it's missing."""
        return cls.load_from_yaml(path) if Path(path).exists() else cls.default_config()

    @classmethod
    def default_config(cls) -> "AppConfig":
        return cls(
            agents={
                "heuristic": AgentConfig(name="heuristic", type="heuristic"),
                "pokechamp": AgentConfig(name="pokechamp", type="pokechamp", role="anchor"),
                "nemotron_3_ultra": AgentConfig(
                    name="nemotron_3_ultra", type="direct_llm", role="sparring",
                    provider="openrouter", model=FREE_TEST_MODEL,
                ),
                "bonsai_2_27b": AgentConfig(
                    name="bonsai_2_27b", type="direct_llm", role="anchor", provider="local", model="bonsai", quantization="PQ2_0"
                ),
            },
        )
