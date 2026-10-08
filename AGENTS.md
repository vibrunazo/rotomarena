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

Ladder commands (see README): `ladder status`, `ladder place <config id>`, `ladder fill --budget N`, `export-site`.
For ladder tests, point `--config` at a scratch config with its own `ruleset.version` and `telemetry.output_dir`
so test games never land in the real season.

Or for non-LLM testing, prefer fast baseline agents:
```powershell
uv run rotomarena battle --p1 pokechamp --p2 heuristic --games 1
```

---

## ⚙️ Key System Specifications & Defaults
1. **Ruleset (season `s1`, `ruleset:` in the tracked `config.yaml`, which also holds the `ladder:` settings and the `agents:` model registry):**
   - `profile: ladder` (default): hidden thinking at OpenRouter **medium** effort, a **4,096-token** cap per turn on
     everything the model writes (local servers stop the thinking at 2,048 and let the model answer), and a
     **2-hour** hang guard. `profile: concise`: thinking off, 1,024 tokens, 15 minutes (fast games, videos).
   - Models keep a short visible `<thought>` (2-4 sentences); the hidden reasoning is recorded too when the provider
     returns it, and OpenRouter's actual cost is logged per turn (`cost_usd`).
   - A cut-off or unparseable answer plays the default move.
   - Every breadcrumb records its `decision_source` (`model`, `timeout`, `api_error`, `parse_error`, `invalid`, `error`).
   - Ladder runs (`place`, `place-all`, `fill`) stop with exit code 3 on a provider limit (402, a daily quota, or a 429
     that outlasts ~6.5 minutes of backoff) or on two void games in a row in one set; the same command resumes.
   - The ladder plays up to `ladder.parallel_games` (4) games of a set at once, each by its own pair of players;
     lanes after the first get a number in their Showdown name only (`username`), display names stay clean.
     Two different local models never generate at once; one model's requests are batched by its server.

2. **Providers:**
   - `openrouter` is the default; its default model is the free Nemotron above.
   - `local` models run on the Smooth Generator's llama.cpp servers (`gen llm serve --model <catalog key> --port <port>`).
     Each local registry entry has its own `port`; `battle` and the ladder start the servers a series needs and stop the
     others (`local_llm.manage` in config.yaml). Weights: `gen llm install --model <key>`.

3. **Pokémon Showdown Server:**
   - Server runs on port `8000` and listens on `127.0.0.1` only.
   - Guest autoconfirmation and battle chat are enabled.
   - Bot usernames are formatted cleanly based on their model/agent type without random hashes (e.g., `Gemini 3.7 Flash`, `DeepSeek V4`, `PokeChamp`). Only identical mirror matches receive clean numeric tags (e.g., `Gemini 3.7 Flash 1` vs `Gemini 3.7 Flash 2`).
