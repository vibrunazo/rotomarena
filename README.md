# ⚡ RotomArena

**RotomArena** is a production-grade, local Pokémon AI battle benchmarking testbed designed for Generation 9 OverUsed (Gen 9 OU) competitive battles. It natively integrates **PokéChamp** (one-turn maximin search with Gen 9 heuristics), **Direct LLM Agents** (Chain-of-Thought reasoning), a local headless **Pokémon Showdown** server with timers disabled, team management, and complete per-turn reasoning telemetry.

---

## 🌟 Key Features

1. **Dual-Runtime Architecture:**
   - **Game Server Layer (Node.js):** Automated setup, execution, health checking, and background management of headless `smogon/pokemon-showdown` with timers disabled.
   - **Intelligence Layer (Python):** Battle protocols via `poke-env`, tree search via `rotomarena.search`, and provider-agnostic LLM communication.

2. **Modular Agent Backends:**
   - **PokéChamp Agent:** One-turn maximin search over sampled opponent replies, with alpha-beta pruning and Gen 9 type chart heuristics. It uses no LLM, so it is free and serves as a ladder anchor.
   - **Direct LLM Agent:** One call per turn (`<thought>` + `<decision>`) under a per-turn output-token budget. The decision must name a legal action exactly; otherwise the default move is played and the turn is tagged in telemetry.
   - **Baseline Agents:** Heuristic damage maximizer (`MaxDamagePlayer`) and `RandomPlayer` for zero-cost test validation and baseline calibration.

3. **Provider-Agnostic LLM Layer:**
   - Pre-configured profiles for **OpenRouter** (default, with a free test model), **local** llama.cpp servers, **Google Gemini**, **Ollama**, and **vLLM**.
   - Standard OpenAI SDK compatibility with latency and token telemetry.

4. **Team Management & Matchmaker:**
   - Smogon `.txt` export format parser, validator, and Showdown packed team generator.
   - Includes standard Gen 9 OU sample teams (Balance, Hyper Offense, Bulky Offense, Rain).
   - 1v1 battle series runner that alternates sides every game and swaps teams every two games.

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

#### 1v1 Matchup: a model from the config registry vs PokéChamp
```bash
uv run rotomarena battle --config config.yaml --p1 bonsai_2_27b --p2 pokechamp --games 4
```

Sides alternate every game and the two teams swap every two games, so 4 games cover every combination.

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
