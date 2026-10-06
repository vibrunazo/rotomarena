# ⚡ RotomArena

**RotomArena** is a production-grade, local Pokémon AI battle benchmarking testbed designed for Generation 9 OverUsed (Gen 9 OU) competitive battles. It natively integrates **PokéChamp** (Minimax search tree with heuristic priors and LLM state evaluation), **Direct LLM Agents** (Chain-of-Thought reasoning), a local headless **Pokémon Showdown** server with timers disabled, team management, and complete per-turn reasoning telemetry.

---

## 🌟 Key Features

1. **Dual-Runtime Architecture:**
   - **Game Server Layer (Node.js):** Automated setup, execution, health checking, and background management of headless `smogon/pokemon-showdown` with timers disabled.
   - **Intelligence Layer (Python):** Battle protocols via `poke-env`, tree search via `rotomarena.search`, and provider-agnostic LLM communication.

2. **Modular Agent Backends:**
   - **PokéChamp Agent:** Minimax tree search with configurable depth ($d=1, 2$), Alpha-Beta pruning, Gen 9 type chart heuristics, and toggleable LLM value priors.
   - **Direct LLM Agent:** Single-call Chain-of-Thought (CoT) reasoning with structured state serialization and legal action enforcement.
   - **Baseline Agents:** Heuristic damage maximizer (`MaxDamagePlayer`) and `RandomPlayer` for zero-cost test validation and baseline calibration.

3. **Provider-Agnostic LLM Layer:**
   - Pre-configured profiles for **Google Gemini** (Google AI Studio OpenAI endpoint), **OpenRouter**, **Ollama**, and **vLLM**.
   - Standard OpenAI SDK compatibility with latency and token telemetry.

4. **Team Management & Matchmaker:**
   - Smogon `.txt` export format parser, validator, and Showdown packed team generator.
   - Includes standard Gen 9 OU sample teams (Balance, Hyper Offense, Bulky Offense, Rain).
   - Automated 1v1 battle series runner with side swapping.

5. **Telemetry & Replays:**
   - Standalone interactive HTML replays and raw Showdown protocol dumps.
   - Per-turn JSON breadcrumbs capturing state snapshots, LLM reasoning thoughts, search tree evaluations, latencies, and token spend.
   - Markdown match summary reports.

---

## 🚀 Quick Start

### 1. Installation

Using `uv` (recommended):
```bash
# Clone or navigate to the repository
cd rotomarena

# Install dependencies and sync virtual environment
uv sync
```

### 2. Configure Environment & LLM Providers

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` to provide your API keys:
```ini
GEMINI_API_KEY=your_google_ai_studio_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

### 3. Local Pokémon Showdown Server

RotomArena can manage the local Showdown server automatically:
```bash
# Check status / setup Showdown server
uv run rotomarena server setup

# Start the headless server in background (port 8000, timers disabled)
uv run rotomarena server start

# Check server health
uv run rotomarena server status
```

### 4. Running Battles

#### 1v1 Matchup: PokéChamp vs Direct LLM
```bash
uv run rotomarena battle \
  --p1 pokechamp \
  --p2 direct_llm \
  --team1 balance \
  --team2 hyper_offense \
  --games 3
```

#### 1v1 Matchup: PokéChamp (Depth 2) vs Baseline Heuristic
```bash
uv run rotomarena battle \
  --p1 pokechamp \
  --p2 heuristic \
  --p1-depth 2 \
  --games 5
```

#### Manage Teams
```bash
# List available sample teams
uv run rotomarena teams list

# Inspect a team
uv run rotomarena teams show balance
```

---

## 📂 Repository Structure

```
rotomarena/
├── pyproject.toml               # Project packaging & dependencies (uv)
├── config.yaml.example          # Sample configuration file
├── .env.example                 # Environment variables template
├── server/                      # Local Pokemon Showdown installation directory
├── data/
│   └── teams/                   # Smogon Gen 9 OU sample teams (.txt)
│       ├── gen9ou_balance.txt
│       ├── gen9ou_hyper_offense.txt
│       ├── gen9ou_bulky_offense.txt
│       └── gen9ou_rain.txt
├── src/
│   └── rotomarena/
│       ├── cli.py               # Typer CLI application
│       ├── config.py            # Pydantic Settings & YAML loader
│       ├── server/              # Pokémon Showdown Node.js server manager
│       ├── llm/                 # Provider-agnostic OpenAI client & prompts
│       ├── search/              # PokéChamp Minimax search, heuristics & simulator
│       ├── agents/              # Player implementations (PokéChamp, Direct LLM, etc.)
│       ├── teams/               # Smogon team parser & loader
│       ├── matchmaker/          # 1v1 battle series runner
│       └── telemetry/           # Breadcrumb logging, replay HTML saver & reports
└── tests/                       # Pytest test suite
```

---

## 📄 License
MIT
