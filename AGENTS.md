# 🤖 RotomArena AI Agent Instructions & Guidelines

## ⚠️ CRITICAL TESTING POLICY: Free LLM Model for Internal Testing
When running live test battles or automated verification runs that require an LLM agent:
- **NEVER use paid Gemini or paid models for test runs** to avoid burning the user's credits.
- **ALWAYS use the free OpenRouter model:** `nvidia/nemotron-3-ultra-550b-a55b:free`

### Standard Test Command:
```powershell
uv run rotomarena battle `
  --p1 direct_llm --p1-provider openrouter --p1-model nvidia/nemotron-3-ultra-550b-a55b:free `
  --p2 heuristic `
  --games 1
```

Teambuilding: `uv run rotomarena teams draft <config id>` has a model build its own Gen 9 OU team from the format's
rules (read from Showdown), with Showdown's validator as referee and up to 5 attempts; a team still illegal after
that is repaired with middling replacements. Results go to `data/drafts/gen9ou/`. The own-teams benchmark (`ruleset.team_mode:
draft`) plays these teams: `uv run rotomarena ladder round-robin` has every LLM play every other one. It refuses to start local models while other local servers run (a ladder run may own them).
Credited Smogon sample teams for tests and fixed-team benchmarks live in `data/teams/smogon/` (`index.json` has builders).

Benches and versions: config.yaml has `rulesets:` (every playable version: s4 = Gen 9 OU own teams, c1 = Pokémon
Champions BSS Reg M-B own teams) and `play:` (the one commands use; `--version` overrides for `teams draft` and
`ladder round-robin`). `benches:` are the benchmark families the site presents like SWE-bench (Rotom Gen9 Bench,
Rotom Champ Bench, Rotom BW Bench to come); each `benchmarks:` entry names its bench, the first being the main
leaderboard. Champions formats are RotomArena's copies in src/rotomarena/server/custom_formats.js (one game, no
timer). Benchmarks and versions: `benchmarks:` in config.yaml lists what the site ranks; each lists ruleset versions. A
version's exact rules (ruleset, format, prompt fingerprints) are stored in `data/rulesets/<version>.json` on its first
run; ladder commands refuse to play if the configuration no longer matches, so a rule change needs a new
`ruleset.version`. The export only rates games whose recorded rules match. Boards: Overall, categories, benchmarks.

Game data for videos and analysis: `runs/<match>/` has `breadcrumbs.json` (every decision: thought, action,
timing, tokens, cost; decision models also `probabilities` for every option), `battle_log.json` and `replay.html`;
`runs/live/<battle>.jsonl` has the same decisions written as they were made. A model's `battle_name` (16
characters at most) is its Showdown username; `display_name` is what the site shows.

Long runs: start them from the run monitor (`powershell -File scripts\monitor.ps1`, then its Start run button,
http://localhost:8765/), never from an agent's shell: the Claude desktop app kills its shells' child processes when it
restarts or updates, and console windows invite being closed. The monitor shows progress, live battles with the
models' thoughts, costs and a time range; its Stop run button also stops the Showdown and local model servers.
While a run plays, don't start another battle or ladder command: it would need the same Showdown server (refused).

Ladder commands (see README): `ladder status`, `ladder place <config id>`, `ladder fill --budget N`, `export-site`.
For ladder tests, point `--config` at a scratch config with its own `ruleset.version` and `telemetry.output_dir`
so test games never land in a real benchmark.

Or for non-LLM testing, prefer fast baseline agents:
```powershell
uv run rotomarena battle --p1 pokechamp --p2 heuristic --games 1
```

---

## ⚙️ Key System Specifications & Defaults
1. **Ruleset (the version being played, `ruleset:` in the tracked `config.yaml`, which also holds the `ladder:` settings and the `agents:` model registry):**
   - `profile: ladder` (default): hidden thinking at OpenRouter **medium** effort, a **4,096-token** cap per turn on
     everything the model writes (local servers stop the thinking at 2,048 and let the model answer), and a
     **2-hour** hang guard. `profile: concise`: thinking off, 1,024 tokens, 15 minutes (fast games, videos).
   - Models keep a short visible `<thought>` (2-4 sentences); the hidden reasoning is recorded too when the provider
     returns it, and OpenRouter's actual cost is logged per turn (`cost_usd`).
   - A cut-off, empty, unparseable or illegal answer plays the default move; from c4 (`answer_attempts: 2`) only after
     a second try that is told what was wrong (breadcrumbs record `attempts` and `first_try`). c4's battle state
     also lists failed moves, lost turns, Protect, Mega Evolution and what caused each boost (`turn_events: full`).
   - Every breadcrumb records its `decision_source` (`model`, `timeout`, `api_error`, `parse_error`, `invalid`, `error`).
   - Ladder runs (`place`, `place-all`, `fill`) stop with exit code 3 on a provider limit (402, a daily quota, or a 429
     that outlasts ~6.5 minutes of backoff) or on two void games in a row in one set; the same command resumes.
   - The ladder plays up to `ladder.parallel_games` (4) games of a set at once, each by its own pair of players;
     lanes after the first get a number in their Showdown name only (`username`), display names stay clean.
     Two different local models never generate at once; one model's requests are batched by its server.
     The round robin plays two streams of pairs at once: the pairs with a local model (GPU) and the rest (APIs,
     decision models, the chimps); the second gets lane numbers after the first's and never touches the servers.

2. **Providers:**
   - `openrouter` is the default; its default model is the free Nemotron above.
   - `local` models run on the Smooth Generator's llama.cpp servers (`gen llm serve --model <catalog key> --port <port>`).
     Each local registry entry has its own `port`; `battle` and the ladder start the servers a series needs and stop the
     others (`local_llm.manage` in config.yaml). Weights: `gen llm install --model <key>`.

3. **Pokémon Showdown Server:**
   - Server runs on port `8000` and listens on `127.0.0.1` only.
   - Guest autoconfirmation and battle chat are enabled.
   - Bot usernames are formatted cleanly based on their model/agent type without random hashes (e.g., `Gemini 3.7 Flash`, `DeepSeek V4`, `PokeChamp`). Only identical mirror matches receive clean numeric tags (e.g., `Gemini 3.7 Flash 1` vs `Gemini 3.7 Flash 2`).
