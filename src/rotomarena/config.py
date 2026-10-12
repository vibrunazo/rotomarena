"""Configuration models and loader for RotomArena."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


AgentType = Literal["pokechamp", "direct_llm", "decision", "heuristic", "max_damage", "random"]
# The agent types that are models being benchmarked (the rest are scripted bots): direct_llm writes its answer as
# text; decision models answer typed questions with probabilities (OpenRouter's Decisions API).
MODEL_TYPES = ("direct_llm", "decision")
AgentRole = Literal["anchor", "sparring", "control", "contestant"]
ReasoningLevel = Literal["off", "minimal", "low", "medium", "high"]

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
    engine: str = Field(
        default="server",
        description="Where games are played: 'simulator' (Showdown's simulator directly, no logins or server; "
        "seeded) or 'server' (bots log into the local chat server and challenge each other)",
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


# Ruleset profiles. ladder: models think (OpenRouter "medium") within a total token cap, and the clock only
# catches hung servers. concise: no hidden thinking and short answers, for fast games (videos, quick tests).
RULESET_PROFILES = {
    "ladder": {"reasoning": "medium", "max_output_tokens": 4096, "turn_timeout": 7200.0},
    "concise": {"reasoning": "off", "max_output_tokens": 1024, "turn_timeout": 900.0},
}


class RulesetConfig(BaseModel):
    """Rules shared by every player of a benchmark version. Recorded in every match; changing them needs a new version.
    `profile` fills in reasoning, max_output_tokens and turn_timeout unless they are set explicitly."""

    version: str = Field(default="s1", description="Ruleset version id: names one exact set of rules (see rulesets.py)")
    profile: Literal["ladder", "concise"] = Field(default="ladder")
    reasoning: Optional[ReasoningLevel] = Field(
        default=None, description="Hidden reasoning requested from every LLM (OpenRouter effort levels)"
    )
    thinking_budget: Optional[int] = Field(
        default=None, ge=1,
        description="Tokens of hidden thinking per turn, the same for every model: OpenRouter's reasoning.max_tokens "
        "(instead of an effort level) and llama.cpp's --reasoning-budget. The answer gets max_output_tokens minus "
        "this, so reaching the budget ends the thinking, not the answer",
    )
    max_output_tokens: Optional[int] = Field(
        default=None,
        description="Per-turn cap on everything an LLM writes, thinking included; a cut-off answer forfeits the turn. "
        "Local servers get half of it as their thinking budget",
    )
    draft_max_output_tokens: Optional[int] = Field(
        default=None,
        description="The same cap for each drafting answer (default: max_output_tokens). Writing six full sets takes "
        "more room than one battle turn; the thinking budget stays the same",
    )
    turn_timeout: Optional[float] = Field(
        default=None, description="Wall-clock limit per turn in seconds; only catches hung servers"
    )
    format: str = Field(default="gen9ou", description="Showdown format id the games are played in")
    thinking_exceptions: Dict[str, ReasoningLevel] = Field(
        default_factory=dict,
        description="{config id: effort level} for models whose provider ignores the thinking budget: the strongest "
        "effort level that stays within it is sent instead (Meta's endpoint for Muse Spark)",
    )
    agent_versions: Dict[str, int] = Field(
        default_factory=dict,
        description="{config id: version} of a scripted player's code (PokéChamp): bumping it retires only that "
        "player's games, which the round robin replays (a per-model rule, see rulesets.PER_MODEL_RULES)",
    )
    provider_routing: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="{config id: OpenRouter providers} a model is served by only these, when others ignore the thinking "
        "budget (DeepSeek V4.1 Flash: 4 of its providers enforce it, 4 think up to the cap)",
    )
    team_mode: Literal["fixed", "draft", "random"] = Field(
        default="fixed",
        description="fixed: every set plays the two `teams`, each from both sides. draft: each model plays the team it "
        "built itself (rotomarena teams draft; repaired if it never got a legal one). random: the format deals "
        "every player a random team (a format with team: 'random')",
    )
    pick: Optional[int] = Field(
        default=None, ge=1,
        description="How many Pokémon each player brings from team preview, chosen in order, the first leading "
        "(e.g. 3 for bring-6-pick-3 formats). Unset: all of them, and the player only chooses its lead",
    )
    answer_attempts: Optional[int] = Field(
        default=None, ge=1, le=3,
        description="Tries an LLM gets for each decision: a failed answer (empty, unreadable, cut off, or naming an "
        "action that isn't legal) is sent back with what went wrong, and only the last failure plays the default "
        "move. Unset: one try (versions before c4)",
    )
    battle_state: Optional[int] = Field(
        default=None, ge=1, le=2,
        description="Version of the battle state the players read. 2 (c4 on) adds what Showdown's interface shows a "
        "player: the recent turns list failed moves, turns lost to status or flinching, Protect and other effects, Mega "
        "Evolution, volatile conditions and each stat change's cause; legal moves carry their tooltip line, priority and "
        "effectiveness on the opposing Pokémon; abilities and items their descriptions; the opponent's stats are its "
        "possible range at its level, with a speed comparison; Champions shows Mega Evolution, not Terastallization. "
        "Unset: 1 (versions before c4)",
    )
    teams: List[str] = Field(
        default_factory=lambda: ["balance", "hyper_offense"],
        description="The two teams every ladder set uses in fixed mode (each played from both sides)",
    )

    @model_validator(mode="after")
    def _apply_profile(self) -> "RulesetConfig":
        for key, value in RULESET_PROFILES[self.profile].items():
            if getattr(self, key) is None:
                setattr(self, key, value)
        return self


class LadderConfig(BaseModel):
    """How ratings are computed and how many games placement and top-ups play."""

    anchor: str = Field(default="bonsai_2_27b", description="Config id whose rating is fixed")
    stall_minutes: float = Field(
        default=20.0, gt=0,
        description="A set with no decision from any player for this long is stuck (its connection to Showdown died): "
        "the run stops with exit code 4 and the run monitor's driver restarts it",
    )
    play_last: List[str] = Field(
        default_factory=list,
        description="Slow models whose pairs play after every other pair (even the anchor's), so the quick games "
        "fill the rankings first",
    )
    rest_minutes: float = Field(
        default=30, gt=0, description="How long the round robin rests a model that is unavailable (a provider limit, "
        "its games going void, its local server not starting) before trying its pairs again; doubles each time, up to "
        "4 hours",
    )
    max_rests: int = Field(
        default=6, ge=1, description="Rests a model gets in one run before the round robin leaves its pairs to the "
        "next run (6: about 15 hours of trying)",
    )
    best_of_three: Dict[str, List[List[str]]] = Field(
        default_factory=dict,
        description="Ruleset version -> pairs that play a best of three in its round robin: one game from each side "
        "and, at 1-1, a deciding third. Like cap_exempt_pairs they play past a game cap (the games still count toward "
        "it; extra_games can make room)",
    )
    cap_exempt_pairs: List[List[str]] = Field(
        default_factory=list,
        description="Pairs that play their games even when a player has reached its max_games (the games still "
        "count toward the cap), for a matchup worth paying for: e.g. a model against its own decision variant",
    )
    anchor_rating: float = Field(default=1500.0)
    parallel_games: int = Field(
        default=4, ge=1,
        description="Games of a set played at once, each by its own pair of players. Local servers get this many "
        "slots and batch the requests (GPT-OSS 2.4x, Qwen 1.6x, Bonsai 1x at four); remote and bot games just overlap",
    )
    games_per_set: int = Field(default=4, description="Games per opponent: 2 teams x 2 sides")
    provisional_games: int = Field(default=16, description="Valid games before a rating stops being provisional")
    max_autopilot: float = Field(
        default=0.5, description="A match is void when either side's fallback share of turns exceeds this"
    )
    bootstrap_samples: int = Field(default=1000)
    control_games: int = Field(default=3, description="Games against each control bot at the start of placement")
    control_max_cost_per_game_usd: float = Field(
        default=2.0, description="Models estimated to cost more per game skip the control games unless forced"
    )


def derived_model_key(agent_type: str, provider: Optional[str], model: Optional[str]) -> Optional[str]:
    """An OpenRouter slug names the weights ('nvidia/nemotron-3-ultra-550b-a55b:free' -> without ':free');
    local catalog keys don't, so local models need an explicit model_key."""
    if agent_type in MODEL_TYPES and provider == "openrouter" and model:
        return model.split(":")[0].lower()
    return None


class AgentConfig(BaseModel):
    """Configuration for a benchmark agent."""

    name: str = Field(default="agent", description="Unique agent identifier (config id)")
    type: AgentType = Field(default="heuristic", description="Agent backend type")
    role: AgentRole = Field(
        default="contestant",
        description="anchor: fixed reference; sparring: free standing opponent; control: a weak bot (Random AI) "
        "that cheap models meet first in placement",
    )
    provider: Optional[str] = Field(
        default=None, description="LLM provider key (e.g. 'openrouter', 'local')"
    )
    model: Optional[str] = Field(
        default=None, description="LLM model override"
    )
    display_name: Optional[str] = Field(
        default=None, description="Showdown name (max 18 chars); generated from the model id when unset"
    )
    port: Optional[int] = Field(
        default=None, description="For local models: the port of this model's llama.cpp server"
    )
    quantization: Optional[str] = Field(
        default=None, description="Weights format for local models (e.g. 'Q4_K_M'); part of the model's identity"
    )
    max_parallel_games: Optional[int] = Field(
        default=None, ge=1,
        description="At most this many of its games at once (ladder.parallel_games otherwise). For free APIs with a "
        "per-minute token quota: four lanes of Gemma 4 on OpenRouter's free tier went over Google's 16k tokens/min",
    )
    active: bool = Field(
        default=True, description="Plays new games; retired models keep their games and ratings, but sit out schedules",
    )
    battle_name: Optional[str] = Field(
        default=None, max_length=16,
        description="Its Showdown username when display_name is too long: Showdown allows 18 characters and a set's "
        "second game adds \" 2\", so 16 keep it whole (battle footage showed \"GPT-6 Luna Decisio\")",
    )
    weights: Optional[Literal["open", "closed"]] = Field(
        default=None, description="open: its weights are published (the site's 'open weights' filter)",
    )
    params_b: Optional[float] = Field(
        default=None, gt=0, description="Total parameters in billions, when published (the site's size filter; "
        "undisclosed sizes stay out of it)",
    )
    max_games: Optional[int] = Field(
        default=None, ge=0, description="At most this many games in each version (a spending cap for paid models); "
        "schedules skip it once reached",
    )
    decision_request: Dict[str, Any] = Field(
        default_factory=dict, description="Decision models: fields sent with every request, e.g. a local server's "
        "settings (Laya: its checkpoint and token budget)",
    )
    decision_max_options: Optional[int] = Field(
        default=None, ge=2, le=255, description="Decision models: most options in one Choice question (default 255); "
        "more are asked in chunks, then a final among their picks. For a model whose options share a short budget",
    )
    extra_games: Dict[str, int] = Field(
        default_factory=dict, description="Ruleset version -> games added to max_games in that version only (e.g. "
        "for a best of three there)",
    )
    opponents: Dict[str, List[str]] = Field(
        default_factory=dict, description="Ruleset version -> the only opponents it meets in that version's round robin "
        "(Sonnet and Opus in c4: three of the top, each other and the anchor)",
    )
    model_key: Optional[str] = Field(
        default=None,
        description="Canonical id of the weights, OpenRouter-style 'org/model' (e.g. 'qwen/qwen3.8-27b'), so other "
        "games' benchmarks can recognise the same model. Defaults to the OpenRouter slug without its ':variant'",
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

    def cap(self, version: str) -> Optional[int]:
        """Its game cap in this ruleset version: max_games plus that version's extra_games; None: no cap."""
        return None if self.max_games is None else self.max_games + self.extra_games.get(version, 0)

    def thinking(self, ruleset: "RulesetConfig") -> Tuple[Optional[str], Optional[int]]:
        """(reasoning level, thinking budget) this model is asked for: the ruleset's, unless it has an exception."""
        if self.name in ruleset.thinking_exceptions:
            return ruleset.thinking_exceptions[self.name], None
        return ruleset.reasoning, ruleset.thinking_budget

    @property
    def is_model(self) -> bool:
        return self.type in MODEL_TYPES

    def canonical_model_key(self) -> Optional[str]:
        """The cross-game identity of an LLM's weights; None for bots (they belong to one game)."""
        return self.model_key or derived_model_key(self.type, self.provider, self.model)


class LocalLLMConfig(BaseModel):
    """Local models run on the Smooth Generator's llama.cpp servers (`gen llm serve`), one port per model."""

    gen: str = Field(default="D:/docs/assets/generator/gen.py", description="Path to the Smooth Generator's gen.py")
    manage: bool = Field(
        default=True, description="Before each game, start the local servers it needs and stop the others"
    )
    ctx: int = Field(default=8192, description="Context per slot for arena servers (a turn needs about 3k tokens); "
                     "servers get one slot per parallel game (ladder.parallel_games)")
    vram_budget_gb: float = Field(
        default=12.5,
        description="Two local models stay loaded together when their files add up to at most this, or when the "
        "larger is a mixture-of-experts model (\"moe\" in the generator's catalog), which spills to RAM well; otherwise "
        "they swap, loading whichever one's turn it is (a dense model squeezed into the leftover VRAM ran at 1-2 tok/s)",
    )


class TelemetryConfig(BaseModel):
    """Telemetry and replay recording settings."""

    output_dir: Path = Field(default=Path("./runs"))
    save_replays: bool = Field(default=True)
    save_breadcrumbs: bool = Field(default=True)
    save_reports: bool = Field(default=True)


class BenchConfig(BaseModel):
    """A family of leaderboards for one game, presented like SWE-bench's benchmarks: its own page and tab, e.g.
    Rotom Gen9 Bench (Gen 9 OU) or Rotom Champ Bench (Pokémon Champions singles)."""

    id: str
    title: str
    tagline: str = Field(default="", description="One line: what is played")
    description: str = ""
    status: Literal["live", "coming"] = "live"


class BenchmarkConfig(BaseModel):
    """One leaderboard: a game format played under one kind of rules (say, Gen 9 OU with each model's own team).
    `versions` are the ruleset.version ids whose games count; each id names exact rules (see rulesets.py).
    `bench` is the family it belongs to; a bench's first benchmark is its main leaderboard, the rest its variants."""

    id: str
    title: str
    bench: str = ""
    category: str = Field(description="Group of benchmarks, e.g. Pokémon; categories get their own aggregate board")
    description: str = ""
    versions: List[str]
    archived: bool = Field(
        default=False, description="A superseded version: kept on the site's archive page, left out of the bench's "
        "pages, its leaderboard tabs and the Overall and category boards",
    )
    anchor: Optional[str] = Field(
        default=None, description="Config id fixed at ladder.anchor_rating on this benchmark's board (default: "
        "ladder.anchor). Each board has its own: a model that plays early and often, never at 0% or 100%",
    )


class PriceTier(BaseModel):
    """A price tier on the site, by cost per game in the main benchmark. `under`: a fixed upper edge in dollars.
    `like`: a reference model; the edge between two reference tiers is halfway (geometrically) between their
    models' costs, and a tier whose model hasn't played yet isn't shown. The first tier, without either, is 'free'."""

    name: str
    under: Optional[float] = None
    like: Optional[str] = None


class LeaderboardConfig(BaseModel):
    """A ranking: Bradley-Terry ratings fitted over the rated games of some ruleset versions. Games are played once;
    boards are views over them (Overall, a category, one benchmark), recomputed on every export."""

    id: str
    title: str
    description: str = ""
    kind: Literal["overall", "category", "benchmark"] = "benchmark"
    category: Optional[str] = None
    bench: Optional[str] = None
    versions: List[str]
    anchor: str = ""  # the config id this board's scale is pinned to
    archived: bool = False  # a superseded version (BenchmarkConfig.archived)


class AppConfig(BaseSettings):
    """Top-level application settings."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    ruleset: RulesetConfig = Field(default_factory=RulesetConfig, description="The version commands play (from play)")
    rulesets: Dict[str, RulesetConfig] = Field(
        default_factory=dict, description="Every version that can be played, by version id",
    )
    play: Optional[str] = Field(default=None, description="The version ladder and draft commands play by default")
    benches: List[BenchConfig] = Field(default_factory=list)
    price_tiers: List[PriceTier] = Field(default_factory=list, description="The site's price tiers, cheapest first")
    ladder: LadderConfig = Field(default_factory=LadderConfig)
    providers: Dict[str, ProviderConfig] = Field(default_factory=provider_presets)
    agents: Dict[str, AgentConfig] = Field(default_factory=dict)
    local_llm: LocalLLMConfig = Field(default_factory=LocalLLMConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    benchmarks: List[BenchmarkConfig] = Field(
        default_factory=list, description="The benchmarks the site ranks; empty = just the current ruleset version",
    )

    def boards(self) -> List[LeaderboardConfig]:
        """Overall (every benchmark) first, then one board per category if there is more than one, then one per
        benchmark."""
        benchmarks = self.benchmarks or [BenchmarkConfig(id=self.ruleset.version, title=self.ruleset.version,
                                                         category="Pokémon", versions=[self.ruleset.version])]
        current = [b for b in benchmarks if not b.archived]  # Overall and categories: the versions played now
        boards = [LeaderboardConfig(id="overall", title="Overall", kind="overall", anchor=self.ladder.anchor,
                                    description="Every rated game in every current benchmark: how good each model is overall.",
                                    versions=[v for b in current for v in b.versions])]
        categories = list(dict.fromkeys(b.category for b in current))
        if len(categories) > 1:
            boards += [LeaderboardConfig(id=c.lower().replace(" ", "-"), title=c, kind="category", category=c,
                                         anchor=self.ladder.anchor,
                                         description=f"Every current {c} benchmark together.",
                                         versions=[v for b in current if b.category == c for v in b.versions])
                       for c in categories]
        boards += [LeaderboardConfig(id=b.id, title=b.title, kind="benchmark", category=b.category, bench=b.bench or None,
                                     description=b.description, versions=b.versions, archived=b.archived,
                                     anchor=b.anchor or self.ladder.anchor) for b in benchmarks]
        return boards

    def anchor_for(self, version: Optional[str] = None) -> str:
        """The anchor of the benchmark that lists this version (default: the version being played)."""
        version = version or self.ruleset.version
        return next((b.anchor for b in self.benchmarks if version in b.versions and b.anchor), self.ladder.anchor)

    @model_validator(mode="after")
    def _pick_ruleset(self) -> "AppConfig":
        for version, ruleset in self.rulesets.items():
            ruleset.version = version
        if self.play:
            if self.play not in self.rulesets:
                raise ValueError(f"play: {self.play!r} is not one of the rulesets ({', '.join(self.rulesets)})")
            self.ruleset = self.rulesets[self.play]
        return self

    def playing(self, version: Optional[str]) -> "AppConfig":
        """This config set to play another version (a command's --version); itself when version is None."""
        if not version:
            return self
        if version not in self.rulesets:
            raise ValueError(f"No ruleset {version!r} in the config (have: {', '.join(self.rulesets)})")
        return self.model_copy(update={"ruleset": self.rulesets[version], "play": version})

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
                    name="bonsai_2_27b", type="direct_llm", role="anchor", provider="local", model="bonsai", port=8080,
                    quantization="PQ2_0",
                ),
            },
        )
