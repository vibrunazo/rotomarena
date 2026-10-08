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
uv run rotomarena battle --p1 bonsai_2_27b --p2 pokechamp --games 4
```

Sides alternate every game and the two teams swap every two games, so 4 games cover every combination.
`config.yaml` holds the ruleset version being played, the benchmarks the site ranks, the ladder settings and the model registry (`agents:`); API keys
stay in `.env`. Local models run on the Smooth Generator's llama.cpp servers, one port per model: before each
series RotomArena starts the servers it needs (`gen llm serve`) and stops the others.

### 5. The Ladder (ratings per benchmark)

Ratings are Bradley-Terry fits on the Elo scale, anchored to Ternary-Bonsai-2-27B at 1500, with 95% parametric
bootstrap intervals. Matches where either side fell back to the default move on more than half its turns are
void.

```bash
# Ratings of the version being played, plus any void matches and why
uv run rotomarena ladder status

# Placement for a registry entry: 4 games each against the anchors and a sparring partner,
# then 4 against the closest-rated LLM. Re-running resumes an interrupted placement.
uv run rotomarena ladder place bonsai_2_27b

# Top-up games between neighbours whose intervals still overlap (free models only by default)
uv run rotomarena ladder fill --budget 8

# JSON for the website (every benchmark + the retracted v0 archive)
uv run rotomarena export-site --out site/src/data
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
├── config.yaml                  # Ruleset, ladder settings & model registry
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
│       ├── results.py           # Loading matches, void rules, outcomes
│       ├── rating.py            # Bradley-Terry ratings with bootstrap intervals
│       ├── ladder.py            # Placement and top-up scheduling
│       ├── export/              # JSON export for the website
│       └── telemetry/           # Breadcrumb logging, replay HTML saver & reports
└── tests/                       # Pytest test suite
```

---

## 📄 License
MIT
