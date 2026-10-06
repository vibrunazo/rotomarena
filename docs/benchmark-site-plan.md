# RotomArena: Benchmark Website Plan

A static site (Astro, hosted on Netlify) that presents RotomArena as a rigorous, peer-reviewed frontier-model
benchmark. It is a real benchmark with real numbers. The only joke is what it measures: which LLM is best at
competitive Pokémon.

> Other benchmarks measure how good agents are at coding. We focus on what people really care about.

**Decided so far**

- The name stays **RotomArena**.
- Season 1 uses only cheap open-weights models, mostly run locally (see section 5).
- Free sparring partners: **Nemotron** and **Gemma 4**.
- Phase 0a (removing the tournament and commentary code) is done.

---

## 1. Concept and voice

**Premise:** the site looks exactly like a serious AI lab's benchmark page crossed with an arXiv paper: a
leaderboard with confidence intervals, model cards, a methodology paper, BibTeX, an ethics statement, a
changelog, and reviewer comments. Every number on it is computed from real battles.

**Rules for the deadpan voice**

1. Never wink. No emoji, no "lol", no "just kidding", no exclamation marks. The site is 100% sincere.
2. The comedy comes from rigor applied to a silly subject: p-values, bootstrap CIs, "Figure 3", footnotes.
3. Every claim is true. Numbers come from the exporter (`findings.json`), never hand-typed into copy. The joke
   is on the benchmark and its subject, never a made-up claim about a real model.
4. Footnotes do most of the work. Main text stays straight, and the footnote does the twist.
5. Use the register of corporate and academic writing: "state-of-the-art", "frontier", "we are excited to
   share", "economically valuable tasks".

**Line bank** (draft copy)

- Other benchmarks measure how good agents are at coding. We focus on what people really care about.
- SWE-bench asks whether a model can resolve a GitHub issue. We ask whether it knows Ground is immune to
  Electric. Only one of these has ever come up at a family dinner.
- All results are reported with 95% confidence intervals. The intervals overlap. All of them. With each other.
- Ratings are computed with Bradley-Terry maximum likelihood and 1,000 bootstrap resamples, a level of rigor
  our sample size does not deserve.
- Human baseline: pending. Our human was busy.
- Benchmark contamination: we cannot rule out that models have read Bulbapedia. We assume they have. It did
  not help.
- Leaderboard saturation: not a concern.
- Results are final until we run more games.
- Peer reviewed: yes (by a peer).
- Compute was allocated in line with our priorities.
- Baselines (non-AI)¹ … ¹ Technically also AI. Please do not tell them.
- Head-to-head, empty cell: "These models have not met."
- Ethics statement: no Pokémon were harmed. Several fainted.
- Reproducibility: battles use Pokémon Showdown's RNG, which we did not seed. Neither did anyone else.
- Reviewer 2: "The authors should consider whether this is a good use of compute." Score: 3 (weak reject).
  Confidence: 5 (absolutely certain).
- Not affiliated with any AI lab, Nintendo, Game Freak, Creatures, The Pokémon Company, or Smogon, all of
  whom we assume would prefer it that way.

**Metric names** (all computed, all real)

| Metric | Definition |
|---|---|
| Rating (BT-Elo) | Bradley-Terry fit on the Elo scale, 95% bootstrap CI |
| Win rate | wins / valid games, shown with n |
| Autopilot Rate | % of turns where the fallback picked the move (timeout, API error, bank empty) |
| Hallucinated Move Rate | % of turns where the model asked for an action it did not have |
| Tokens per Turn | mean total tokens per decision |
| Tera Discipline | turn on which the model terastallized (lower = more impatient) |
| Switch Anxiety Index | switches per turn |
| Signature Move | the model's most-used move |

Decision time is not a metric: for local models it measures the graphics card, not the model.

---

## 2. How models get rated (the ladder)

**Question:** wouldn't pitting every model against every other model and computing Elo be the best benchmark?

**Answer:** it's the cleanest design, but you don't need it, and the cost grows with the square of the field.
Your runs so far cost a median of **~50k tokens per LLM per game** (18 turns; DeepSeek V4 is ~100k). An
LLM-vs-LLM game bills both sides.

| | Full round robin (4 games per pair) | Ladder placement (proposed) |
|---|---|---|
| Whole table, 10 models | 180 games, ~18M tokens | n/a |
| Adding model #11 | 40 games, ~4M tokens, half billed to incumbents (expensive ones included) | 16 games, ~1M tokens, ~0.2M billed to one incumbent |
| Adding model #21 | 80 games, ~8M tokens | still 16 games, ~1M tokens |

**Why the ladder works:** use Bradley-Terry instead of incremental Elo. It's what LLM leaderboards call "Elo":
the number is on the Elo scale, but it's fit over every game at once, so game order doesn't matter. It only
needs the who-played-whom graph to be connected. **Games are never replayed:** a game played in March counts
the same in October as long as the ruleset hasn't changed.

**Ladder design**

- **Anchors:** Heuristic AI and PokéChamp D1. They are free to run and never change. Heuristic = 1500 by
  definition.
- **Sparring partners:** Nemotron and Gemma 4, free, and permanently in the pool.
- **Placement for a new model:** 16 games, each set covering 2 teams × 2 sides:
  - 4 vs Heuristic AI and 4 vs PokéChamp D1 (only the new model pays)
  - 4 vs a free sparring partner (only the new model pays)
  - 4 vs the LLM with the closest provisional rating. This is the only set that costs an incumbent anything.
    Close matchups are the most informative games, and lopsided ones say little.
- **Local models:** tokens are free, so the cost becomes GPU time instead (section 5). The same 16 games
  apply.
- **Provisional badge** until a model has 16 valid games. CIs are shown either way.
- **Top-up:** `ladder fill --budget N` spends spare games (free models first) on the pairs whose CIs overlap
  the most.
- **What you give up:** non-transitive matchups (A beats B, B beats C, C beats A) are only visible where pairs
  actually met. The site shows a head-to-head matrix and labels empty cells "These models have not met."
- **Seasons:** the prompt, teams, timers, parser and reasoning settings form a versioned ruleset recorded in
  every match. Changing any of them starts a new season, and old seasons stay viewable. Keep prompt changes
  rare.

---

## 3. Phase 0: clean up and make the numbers real

### 0a. Remove dead code (done 6 Oct 2026)

- **Tournament:** delete the `TournamentOrchestrator`, the `tournament` CLI command, `matchmaker/elo.py`,
  `TournamentConfig` and the `tournament:` block in `config.yaml.example`. Move `create_agent_instance` and
  `format_bot_display_name` into `agents/factory.py`, since `battle` uses them. The ladder replaces all of
  this.
- **Commentary and TTS narration:** delete the `commentary/` package, the `commentary` CLI group, the
  `--commentary` and `--commentary-language` flags, `generate_commentary` and `commentary_language` in
  `TelemetryConfig`, the commentary step in `runner.py`, the commentary and Web Speech blocks in the
  `replay_saver.py` template, and `tests/test_commentary.py`. Then run `rotomarena replay refresh` so the
  local `replay.html` files are regenerated without it, and delete the stale `commentary.json` files.
- Remove the tests for deleted code, and keep the tests for `factory.py`.

### 0b. Fix the bugs that corrupt results

- [ ] Separate fallback turns from model decisions: tag each breadcrumb with `decision_source`
      (`model | timeout | bank | api_error | invalid | parse_error`) instead of parsing reasoning prefixes.
- [ ] Rewrite the decision parser: require `<decision>`, exact-match against legal action ids (normalized),
      no substring matching, no "TERA anywhere" check, and a parse failure becomes a recorded `parse_error`.
- [ ] Fix damage estimates against the opponent (poke-env reports opponent `max_hp` as 100, so damage is
      overestimated about 3×), the Stealth Rock check (string vs enum), and identical scores for all switches.
      The baselines are now the anchors, so this matters more.
- [ ] PokéChamp: implement depth > 1 or remove the option; fix the LLM prior (it scores the current state, the
      same for every candidate, so it costs N calls per turn and changes nothing).
- [ ] Unknown agent types must raise (README's `direct-llm` currently runs a Random bot).
- [ ] Record a `players` block per match: `{config_id, type, provider, model, depth, team, reasoning_effort}`
      plus `ruleset_version`. Ratings are keyed by `config_id`, never by display name.
- [ ] `battle --games N` must alternate sides and teams.
- [ ] Use the same reasoning-effort and prompt settings for every provider.
- [ ] Replace the wall-clock turn timer and time bank with a per-turn output-token budget. Keep a long
      wall-clock limit only to catch a hung server (section 5).
- [ ] Add a `local` provider preset (`http://127.0.0.1:8080/v1`) and record the quantization as part of a
      model's identity.
- [ ] Default to the free OpenRouter model instead of paid Gemini when no provider is given.
- [ ] Bind Showdown to `127.0.0.1` instead of `0.0.0.0`.
- [ ] Escape `</` in everything inlined into `<script>` blocks (raw battle logs), since replays will be public.

### 0c. Old runs become a feature

The existing 55 runs predate these fixes. Migrate them once into a "Retracted results (v0)" archive instead of
keeping legacy handling in the exporter. That page holds the best existing data point: *Muse Spark failed to
respond on all 79 of its turns and still won a game against DeepSeek V4.* Present it deadpan: "We are calling
this Zero-Token Reasoning."

---

## 4. Phase 1: ladder and data pipeline (Python)

The Python package computes everything, and the site renders static JSON without doing any math.

- **`rotomarena/rating.py`:** Bradley-Terry fit (MM iterations, no scipy needed), Elo-scale conversion
  anchored at Heuristic = 1500, and bootstrap CIs over matches (1,000 resamples). Models not connected to the
  anchor are listed as *Unranked (isolated)*. Both the ladder and the exporter use it.
- **Model registry:** the `agents:` block of `config.yaml` (config id → type, provider, model, settings). It
  also flags which entries are anchors and free sparring partners.
- **`rotomarena ladder place <config_id>`:** runs the 16 placement games and picks the closest-rated paid
  opponent automatically.
- **`rotomarena ladder fill --budget N`:** extra games for the pairs whose CIs overlap the most.
- **`rotomarena ladder status`:** prints the current ratings table.
- **`rotomarena export-site --runs runs --out site/src/data`:**
  1. Load every match in the current season (and the v0 archive).
  2. Void a match when either side has an Autopilot Rate above 50%. Voided matches are listed but not rated.
  3. Rate the models, and compute per-model metrics, signature move, favorite Pokémon, longest and shortest
     `<thought>`, hallucinated actions with turn links, and the head-to-head matrix.
  4. Compute **findings**: superlatives with real numbers and a `show` flag (a finding hides itself when its
     condition is not met). Examples:
     - top model, and whether its CI overlaps the bottom model's
     - Pearson r between tokens per turn and win rate
     - most tokens per turn vs the field median
     - zero-token wins (games won with 100% Autopilot)
     - most hallucinated move, most common move across all LLMs
  5. Scrub secrets: OpenAI-style error messages can contain masked keys. Drop anything that matches
     `sk-|AIza|Bearer`.
  6. Write the files below.

```
site/src/data/
  meta.json          # generated_at, season / ruleset version, totals (matches, turns, tokens)
  models.json        # one row per model: identity, rating, CI, provisional flag, metrics, quote
  head_to_head.json  # pair → games, wins
  findings.json      # computed superlatives + show flags
  matches/<id>.json  # players, teams, winner, turns, duration, protocol log, per-turn
                     # {action, thought, latency, tokens, decision_source} for both sides
  retracted/<id>.json
```

The generated JSON is committed. Netlify never runs Python.

---

## 5. Season 1: local open-weights models

**Verdict:** viable. Eight local models come to roughly 1-2 days of GPU time for placement, as long as the
chess clock goes and every model fits in RAM + VRAM.

**Hardware:** RTX 5060 Ti 16 GB, 64 GB DDR5-6000, Ryzen 9 9900X, over 1 TB free on C:. That leaves room for
model files up to about 60 GB (about 13 GB in VRAM and the rest in system RAM).

**What a game costs locally.** Your runs average about 1.7k prompt tokens and a median of about 360 generated
tokens per turn, over about 18 turns per game. Speeds below are estimates for llama.cpp on this hardware;
measure each model with one test game before placement.

| Model class | Model file size | Generation speed | One side of one game | 16 placement games |
|---|---|---|---|---|
| Fits in VRAM (7-14B dense, Bonsai 27B ternary) | up to ~12 GB | 40-70 tok/s | ~3-5 min | ~1.5 h |
| Mixture-of-experts with the experts in system RAM | 20-60 GB | 8-30 tok/s | ~6-12 min | ~3 h |
| Dense, partly in system RAM (24-70B) | 20-45 GB | 2-6 tok/s | ~0.5-1 h | ~8-16 h |
| Too big | over ~60 GB | under 1 tok/s, reads from disk | hours | not viable; use OpenRouter |

With thinking enabled, generated tokens per turn go up 5-10× (the 90th percentile in your runs is 3.5k), and
the time goes up with them.

**Constraints and fixes**

- **The chess clock must go.** At 3 tok/s, a 400-token answer takes over 2 minutes, so the 120 s turn timer
  would turn slow hardware into Autopilot turns and punish the model for the graphics card. Replace it with
  an output-token budget per turn (e.g. 1,024 tokens) and keep a wall-clock limit (e.g. 15 min) only to catch
  a hung server.
- **Thinking off, visible thought on.** Season 1 ruleset: no hidden reasoning, and models reason in the
  `<thought>` block (200 words max). It's faster, the same for every model, and the thoughts are the site's
  best content. A thinking track can be a later season.
- **Two local models don't fit at once.** In an LLM-vs-LLM game both sides ask for a move at the same time.
  Put the models behind `llama-swap` (one OpenAI-compatible endpoint that loads the requested model). A swap
  takes seconds when the model file is still in the RAM file cache, longer for big mixture-of-experts models.
  Most placement games (anchors and API sparring partners) only need one local model loaded.
- **Quantization is part of the identity.** "Model X at Q4_K_M" is a different contestant from model X on an
  API, so record it and show it on the leaderboard. Site line: "All models were evaluated at the precision our
  graphics card could afford."
- **The GPU is busy during a season.** The Smooth Generator can't use it while games run, so run placements
  overnight.
- **Free API sparring partners have rate limits.** OpenRouter's free tier caps requests per minute and per
  day. A set of 4 games is about 72 requests, so one or two placements a day is safe.

**Serving setup**

- Following your global rule, the serving tool belongs in the Smooth Generator, not in RotomArena: generalize
  `gen llm serve` to take any GGUF from the HF cache (for example `gen llm serve --model <repo>/<file>`), with
  Bonsai as one entry. Bonsai needs PrismML's llama.cpp fork for its PQ2_0 format; other models use mainline
  llama.cpp.
- The server stays on `127.0.0.1:8080` with an OpenAI-compatible API. RotomArena's `local` provider points
  there and passes the model alias.
- Bonsai is already set up: Ternary-Bonsai-2-27B, 7.3 GB, thinking off, 2 slots (so a mirror match works).
  It can be contestant #1 today.
- The vLLM preset defaults to port 8000, which is the Showdown server's port. Change it.

**Shape of an 8-model lineup**

- 5 models that fit in VRAM: the fast majority, including Bonsai, and Gemma 4 if a size of it fits.
- 2 mixture-of-experts models with the experts in system RAM.
- At most 1 dense model that doesn't fit in VRAM (the overnight model).
- About 150-250 GB of disk in total.
- Nemotron (550B) is far too big to run locally, so it stays an OpenRouter sparring partner.

---

## 6. Phase 2: Astro site

**Stack:** current Astro, static output (no adapter needed), Content Layer collections
(`src/content.config.ts` with `file()` for `models.json` and `glob()` for `matches/*.json`), `@astrojs/mdx` for
the paper and changelog, and `@astrojs/sitemap`. Plain CSS with design tokens, no UI framework. The only
client JS is leaderboard sorting, the BibTeX copy button, and the replay embed.

```
site/
  astro.config.mjs          # site: 'https://<domain>', integrations: mdx, sitemap
  package.json
  public/                   # favicon, og.png, robots.txt
  src/
    content.config.ts
    data/                   # generated by export-site (committed)
    styles/tokens.css       # light + dark tokens
    layouts/Base.astro, Paper.astro
    components/
      LeaderboardTable.astro  HeadToHead.astro    StatStrip.astro
      ForestPlot.astro        Scatter.astro       Finding.astro
      ModelCard.astro         ReplayEmbed.astro   ThoughtTimeline.astro
      Footnote.astro          Citation.astro      Disclaimer.astro
    pages/
      index.astro
      leaderboard.astro
      models/[slug].astro
      matches/index.astro
      matches/[id].astro
      paper.mdx
      retracted.astro
      faq.astro
      submit.astro
      changelog.mdx
      404.astro
```

**Pages**

| Page | Content |
|---|---|
| `/` | Hero tagline; "State of the art: <top model>" with its CI; stat strip ("2,460 turns analyzed. 0 lines of code written."); 3 headline findings; "Read the paper" |
| `/leaderboard` | Sortable table: rank, model (with quantization), BT-Elo [CI], win rate (n), Autopilot, Hallucinated Moves, Tokens/Turn, Signature Move; provisional badge; anchors in a separate band with the "technically also AI" footnote; head-to-head matrix below |
| `/models/[slug]` | A "Model card" in the style of real model cards: Intended Use ("Gen 9 OU"), Capabilities, Known Limitations (computed: hallucinated moves), Most Memorable Thought (real quote), Signature Move, match list |
| `/matches/[id]` | Official Showdown replay embed + turn-aligned ThoughtTimeline (both players' `<thought>` per turn, AUTOPILOT / HALLUCINATION tags). No commentary or narration. |
| `/paper` | Abstract, 1 Introduction, 2 Related Work, 3 Methodology (the ladder, in full academic register), 4 Results (live figures), 5 Limitations, 6 Ethics, 7 Reproducibility, Reviewer Comments, BibTeX. "Download PDF" = a print stylesheet |
| `/retracted` | v0 results with a formal retraction notice; Zero-Token Reasoning |
| `/faq` | "Is this a real benchmark?" "Yes." / "Why Pokémon?" "We were asked to evaluate models on economically valuable tasks and interpreted this broadly." |
| `/submit` | How to add a model (a PR with a config entry). "Submissions are reviewed by a committee of one." No forms. |
| `/changelog` | Real fixes in deadpan: "v1.0.1: PokéChamp Depth 2 now searches to depth 2. Previously it did not. Rankings were unaffected, which concerns us." |
| `404` | "This page fainted." |

**Related work** (real, cite properly): PokéLLMon (Hu et al., 2024), PokéChamp (Karten et al., 2025),
poke-env, Twitch Plays Pokémon (2014), and the "Claude/Gemini Plays Pokémon" streams. Next to them:
SWE-bench, MMLU, ARC-AGI, "which measure other things."

**Figures** (rendered at build time as inline SVG, no chart library):

- Figure 1, forest plot: BT-Elo with 95% CIs, sorted. Caption: "Differences are not statistically significant.
  We present them in order anyway."
- Figure 2, scatter: tokens per turn vs win rate with the computed r. Caption states r plainly.
- Figure 3, stacked bars: decision source per model (model / timeout / API error / invalid).
- Figure 4: move-usage histogram ("Earthquake remains popular").

**Design:** an academic paper crossed with a lab leaderboard. Serif headings (e.g. Source Serif 4 or
Newsreader), a tabular monospace for numbers (IBM Plex Mono), generous whitespace, footnote superscripts,
"Figure N:" captions, and one restrained electric-orange accent. Light and dark themes. No Pokémon art or
logos outside the replay embed.

**Replay embed:** port the working pattern from `telemetry/replay_saver.py` (the `replay-embed.js` +
`battle-log-data` block and the fx/resource-prefix fix) into `ReplayEmbed.astro`, with `</` escaped. It loads
from play.pokemonshowdown.com, so include that domain in any CSP you add.

---

## 7. Phase 3: Netlify

`netlify.toml` at the repo root:

```toml
[build]
  base    = "site"
  command = "npm run build"
  publish = "dist"            # relative to base
  # Skip deploys when nothing under site/ changed (the ignore command runs from base)
  ignore  = "git diff --quiet $CACHED_COMMIT_REF $COMMIT_REF -- ."

[build.environment]
  NODE_VERSION = "22"

[[headers]]
  for = "/_astro/*"
  [headers.values]
    Cache-Control = "public, max-age=31536000, immutable"

[[redirects]]
  from = "/arxiv"
  to   = "/paper"
  status = 301
```

Setup steps:

1. Create a GitHub remote (the repo has none) and settle `master` vs `main`.
2. Netlify → Import from Git → the settings come from `netlify.toml`.
3. Custom domain + HTTPS (automatic).
4. Release flow: `ladder place` or `ladder fill` locally → `export-site` → commit `site/src/data` → push →
   Netlify builds. Deploy previews on PRs come free, and are a good place to review an update before it goes
   live.

---

## 8. Phase 4: content, assets, launch

- **Copy:** write the paper and FAQ in MDX. Numbers come in through components (`<Finding id="tokens-vs-wins" />`),
  never typed by hand.
- **Assets (Smooth Generator):** an OG image (`gen image`) and an original mascot that is *not* a Pokémon (a
  lab appliance with a clipboard).
- **Legal footer:** fan parody, non-commercial; Pokémon is a trademark of Nintendo / Creatures / GAME FREAK /
  The Pokémon Company; replays use Pokémon Showdown; model names are used to identify the models only, with
  no lab logos.
- **Launch checklist:** Lighthouse pass, phone width (the leaderboard scrolls inside its own container, never
  the page), dark mode, OG preview, 404, sitemap, and confirming no keys appear in `site/src/data`.

**Later, not now:** automated YouTube videos with play-by-play narration. When that becomes a priority,
pre-render the narration (Smooth Generator TTS) and the video (Motion studio) from the exported match JSON
instead of narrating live in the browser.

---

## 9. Open decisions

1. The domain (keep "Pokémon" out of it).
2. Which 8 local models. I can research a current shortlist with model file sizes and licenses.
3. Season 1 ruleset: thinking off with a visible `<thought>` (recommended), or thinking on.
4. Publish the retracted v0 archive (recommended, it has the best story) or drop it.
