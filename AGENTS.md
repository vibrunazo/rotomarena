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

Or for non-LLM testing, prefer fast baseline agents:
```powershell
uv run rotomarena battle --p1 pokechamp --p2 heuristic --games 1
```

---

## ⚙️ Key System Specifications & Defaults
1. **Turn Limits & Chess-Clock:**
   - Default turn timeout: **120.0s** (`--turn-timeout 120`)
   - Default total match time bank: **15:00 / 900.0s** (`--bank-timeout 900`)
   - Auto-fallback moves execute upon timeout without crashing the match.

2. **Concise Reasoning & Effort Controls:**
   - OpenRouter calls default to `reasoning: {"effort": "medium"}`.
   - Direct LLM `<thought>` output must remain **under 60 words total**.
   - Focus on the single decisive tactical factor (speed tier, knockout threshold, or switch priority).

3. **Pokémon Showdown Server:**
   - Server runs on port `8000` (`http://127.0.0.1:8000`).
   - Guest autoconfirmation and battle chat are enabled.
   - Bot usernames are formatted cleanly based on their model/agent type without random hashes (e.g., `Gemini 3.7 Flash`, `Gemini 3.8 Flash`, `DeepSeek V4`, `PokeChamp D1`). Only identical mirror matches receive clean numeric tags (e.g., `Gemini 3.7 Flash 1` vs `Gemini 3.7 Flash 2`).
