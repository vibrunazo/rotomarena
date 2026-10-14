# Plan: Champions c5 and the infrastructure around it

Written 11 Oct 2026, while c4 finishes. RotomArena began as quick live-streamed games and is now a serious-ish
benchmark; this plan asks what we would do differently if we started over, keeps what still holds, and orders the
changes. Gen 9 OU (s-versions) stays on hold.

**Principles.** Every result should mean one thing (validity) and not flip with more games (reliability), at the
lowest cost in dollars: money is the binding constraint, and new models arrive almost daily (Fable, Astra, Sol,
Terra, the pro tiers of GLM 5.3, K3 and DeepSeek...). Trading time for money is welcome. One published number per
model: drafting and battling together, as now. **Every change is smoke-tested small before a full run.**

---

## 1. What the data says (c4, 11 Oct)

Measured from c4's 741 rated games, s4 for comparison, and one free experiment (bots only).

| Finding | Number |
|---|---|
| The team decides a lot. PokéChamp piloting both sides, 8 c4 teams, 112 games: team win rates from 0% to 89% | SD 26 points (luck alone: 9); team strength vs the model's c4 rating: r = 0.9 |
| Gen 9 OU says more per game (same 14 players) | prediction 0.48 vs 0.33 bits/game; ratings settle with ~half the games; but 2.6x the turns, 3x the time |
| Round robin spends games on foregone conclusions | 26% of games had a side over 90% to win; 22% of game-hours. Neighbour pairings: 1.5x the information per game |
| Neighbours aren't separated yet | all 25 adjacent pairs' 95% intervals overlap after 741 games |
| A calculator ranks 6th | PokéChamp (one-turn search) outranks 19 of 24 models |
| Expensive models dominate spend | Opus: 36% of c4's $10.64 after 15 games ($0.25/game) |
| Waste | single-legal-option turns: 7% of decisions, 4% of cost; visible thoughts: ~5% of output tokens (23-27% for Gemini, Sonnet, GLM) |
| Models have no memory | each turn is a fresh request: the last 3 turns of the log, no earlier thoughts, hidden reasoning discarded |
| Anomaly to check | GPT-6 Luna Pro is billed ~6,500 input tokens per decision, GPT-6 Luna ~1,500, on the same prompt |

Caveats: s4 has only 107 games; the team experiment had 8 teams and a weak pilot (PokéChamp plays plain
attackers best).

## 2. Priorities

1. **Simulator instead of the chat server** (section 3). Removes a whole class of failures and unlocks parallel
   and batch play.
2. **c5 rules** (section 4): prompt fixes, thoughts as memory, three drafts per model, waste cuts.
3. **Scheduling** (section 5): free placement, then neighbours, to a precision target.
4. **Batch mode for expensive models** (section 6), once the simulator runs many games at once.
5. Site additions (section 7).

Each step: smoke test (a few games, free or cheap models first), read the raw answers, then commit.

## 3. Simulator instead of the chat server

**Status (11 Oct, evening): built and smoke-tested** (`server.engine: simulator`; the chat server stays the default
until c4's run ends). Tests passed: bots 40 games (PokéChamp 33-7 against MaxDamage, as on the server, after one
bug: teams skipped the validator, which applies Champions' level 50); a GLM 5.3 Flash game with every decision
answered and its raw answer kept; a 3-player round robin with parallel lanes; live watching in the run monitor.
Still to do: switch the default once c4 ends, then play c5 on it.

**Now.** Our players log into a local Pokémon Showdown *server* as users and challenge each other over
websockets (poke-env). The server is a chat site wrapped around Showdown's *simulator*: logins, usernames, rooms,
challenges. This week's failures all came from that layer: lane numbers in names ("Opus 5.5 2") and renaming them
in replays, a test game signing in under a ladder player's name and crashing the run, "expected one finished
battle" challenge races, `--join` coordination, one shared server that test games must not disturb.

**After.** Python starts Showdown's simulator directly (`pokemon-showdown simulate-battle`, or a Node
BattleStream), one battle per stream: write `>start`, `>player p1 {...}`, then each side's choices
(`>p1 move 1`); read the protocol back, split per side. Each side's messages go to that player's poke-env battle
object, so agents, prompts and state formatting are unchanged. Lowest-risk shape: a small adapter that stands in
for poke-env's server connection, so the player code doesn't know the difference.

**Gains**
- No logins: players are named whatever we like (display names, any length); no lanes, collisions or renames.
- No shared server: test games can't disturb a run; nothing to start, stop or health-check.
- Seeded battles: a game replays exactly from its seed and choices (debugging, "what if it had switched" studies).
- Hundreds of games in parallel, limited only by CPU and providers: what batch mode needs (section 6).
- Somewhat faster: no network hops.

**Losses and costs**
- Showdown's own spectating goes away. The run monitor's watch page reads each battle's log from our files instead
  (it already uses our own player page and polls our API).
- We leave poke-env's well-trodden path: the adapter must cover requests, forced switches, team preview, Mega
  Evolution, errors. Main risk; keep the adapter small and test it against recorded server games.
- Custom formats: the simulator loads the same `custom_formats.js`; team validation already uses the CLI.
- Roughly 2-4 days with tests.

**Replays** stay the same: a replay is the battle's protocol log played back, and the simulator writes the same
log (`battle_log.json`, `replay.html`). We also get the omniscient log of both sides.

**Smoke test.** Replay a handful of recorded c4 games' decisions through the simulator; then bot-vs-bot (free),
then one cheap model, comparing logs and breadcrumbs with server games.

## 4. c5 rules

All of these change fingerprinted rules, so they ship together as one new version. Before freezing it: every
model plays 2 games against PokéChamp on a scratch config, and we read the raw answers (breadcrumbs keep them
since 11 Oct). It would have caught Sonnet's doubles team and Opus's missing tags before 800 games.

### Prompts
- **Draft: say singles.** (TODO.md) "Singles: one Pokémon on the field per side; you bring 3 of your 6 to each
  battle and choose which."
- **Battle: state the answer format** (TODO.md), repeated as the last line of each turn's message.
- **Drop the persona** ("You are an expert competitive Pokémon player and ... grandmaster"): state the task.
- **Whole battle log** instead of the last 3 turns: Champions games are ~8 turns, so it's short.
- **Static parts first, changing parts last** (rules, then your own team's sets, then the turn's state), so
  providers' automatic prompt caching applies. Gemini's cost is mostly input (1,800 tokens in, 142 out).
- **Thoughts become memory** (decided 11 Oct; we try it and see). Today they are display only: each turn is a
  fresh request, nothing carries over, and the hidden reasoning is discarded. In c5 the visible thought is the
  model's notes for its later turns: the prompt says what they are for ("your plan, what you've learned about
  their sets", for long-term strategy), drops the punchline-brevity rule (that existed for videos), keeps a cost
  cap (~60 words), and each turn shows its earlier notes. Smoke test with cheap models against PokéChamp: cost
  per game (input grows with the notes), whether notes get used, results. If it doesn't pay, fall back to dropping
  the visible thought (~5% of output).

### Drafts: three per model
One draft per version is one sample of a model's teambuilding: more games only measure that one team more
precisely (Sonnet's misread of singles shaped its whole c4 rating). So:
- At the start, each model drafts **three teams**, as three independent requests with the same prompt. No
  feedback between them: each is its own sample of what the model builds. Identical teams are allowed (that's the
  model's answer). Cost: three times a draft, cents per model ($0.04-0.07 per Sonnet or Opus draft in c4).
- Each game uses one of the model's teams, assigned by the schedule so its three teams play about equally often
  against a spread of opponents.
- Not now: redrafting mid-version with feedback (its earlier teams, win rates). That measures adaptation, a
  different skill, and makes ratings drift mid-version. A possible separate benchmark later.
- Model pages show the three teams and each one's record.

### Considered, not doing: swapped teams
Playing a pair both ways (each model once with its own team, once with its opponent's, as in duplicate bridge)
separates playing skill from team strength. With one published number (its own team, played by itself) that
split isn't needed, and a swapped game measures that number less directly than an own-team game. The one thing
it would add, averaging out lucky team matchups, the three drafts mostly cover: two models meet across up to 9
team combinations instead of one. Also considered: fixed meta teams (no Champions BSS Reg M-B sample-teams thread
found on Smogon) and random teams (more luck per game). Back on the table only if a separate battling score is
ever wanted. The control bots keep borrowing their opponent's team.

### Thinking: stay at medium, with more room (smoke-test high)
How it works (OpenRouter's reasoning docs, checked 11 Oct): a request sets `reasoning.effort` (low, medium,
high...) or `reasoning.max_tokens`, never both, and OpenRouter translates for each provider. Budget-based
providers (Anthropic) get a budget: effort is a share of the output cap (medium 50%, high 80%, low 20%), a number
is used as is. Effort-based providers (OpenAI, Gemini, Grok) get an effort level: a number is turned into one by
its share of the output cap (exact cutoffs unpublished; Gemini 3 maps it internally). A budget is a ceiling, not a
target: the model decides how much to think below it.

So c4 (2,048 of a 4,096 output cap, 50%) is **medium for everyone**: a 2,048 ceiling for budget-based models,
medium effort for effort-based ones; Muse is set to medium explicitly. c4's data: only Muse (45% of turns),
Solar (18%), MiMo (10%) and GPT-6 Luna Pro (9%) reach 2,048 reasoning tokens; Opus averages 526, Gemini 83,
Sonnet 148, GPT-6 Luna 259, by choice.

- **c5: 4,096 of 8,192** (still 50%, still medium). More room for the models that reach the ceiling; effort-based
  models unchanged. About +$0.40 on a c4-sized run (~4%).
- **The real quality decision is medium vs high.** High (80%) changes what effort-based models do (GPT-6,
  Gemini): they think more, and cost more. For budget-based models (Claude) it only raises the ceiling again.
- Smoke test before choosing: a few models at medium vs high, ~20 games each against PokéChamp (cheap ones
  first: Muse, Solar, GPT-6 Luna, Gemini 3.8 Flash): reasoning tokens and cost per turn, and whether results move.
- Local models get their budget at server start (`--reasoning-budget`): more thinking costs GPU time, not money.

**Smoke test, 12 Oct (medium vs high, 8,192 output cap, 20 games each against PokéChamp, simulator, $2.24):**

| Model | Thinking/turn medium → high | Cost/game | Wins (of 20) |
|---|---|---|---|
| Muse Spark 1.3 | 1,886 → 2,697 (+43%) | $0.0079 → $0.0102 | 9 → 9 |
| Solar Pro 4 | 1,229 → 1,017 (ignores it) | $0.0064 → $0.0047 | 15 → 15 |
| GPT-6 Luna | 283 → 428 (+51%) | $0.0039 → $0.0047 | 9 → 13 |
| Gemini 3.8 Flash | 100 → 95 (ignores it) | $0.0365 → $0.0377 | 11 → 13 |

High only changes some models (Muse, GPT-6 Luna think ~50% more, +20-30% cost; Solar and Gemini ignore it), and
no result difference is detectable at this size: all four went 44 → 50 wins of 80, about one standard error, and
Gemini won 2 more without thinking any more (a measure of the noise). A real 10-point gain would need a few
hundred games per level to show. **Decision pending; recommendation: medium** (4,096 of 8,192), since high costs
more where it does anything and shows no measurable gain.

**Changed 13 Oct: a 4,096-token budget for everyone** (`thinking_budget: 4096`; c1-c4's way, the same ceiling for
all), instead of medium effort, which providers read their own way (Sonnet thought nothing; Qwen Flash and MiniMax
spiralled). Exceptions only where a budget doesn't work: Gemini 4 Argon gets high effort (it barely thinks at any
budget). Measured the same 3 real c5 turns at both settings per model ($0.58): unchanged for most (Claude, GPT-6,
Gemini 3.8 Flash, Muse, Kimi, GLM Flash, DeepSeek Flash, MiMo Flash; local and decision models by construction);
changed for Solar Pro 4, Qwen 27B, Qwen Max Prime, MiMo Pro, Grok, GLM 5.3, DeepSeek V4 Pro (borderline) and Nemotron
(untested). Their 32 earlier c5 games are tagged `superseded:medium-effort:<model>` and still count; retire them
(void) once those models have enough games under the budget. c5's stored rules record the amendment.

### Waste
- **No model call when only one action is legal** (7% of decisions, 4% of cost): play it and record it as such.
- Look into GPT-6 Luna Pro's input-token count before c5 (see section 1).

### Progress (12 Oct)
Built, behind new ruleset settings so c4's rules stay unchanged; c5's ruleset is in config.yaml (not played yet):
- **Battle state 3** (`battle_state: 3`): the task and answer format stated plainly, no persona, notes as memory
  (`notes_shown: 3`), cache order, one-legal-action turns played without asking ("forced", not autopilot).
  Smoke test: a GLM 5.3 Flash game; its notes carried its plan from turn to turn. Prompts start at ~1,750 tokens
  (c4: ~2,000) and grow ~200 a turn.
- **Notes test** (12 Oct, $1.77): GLM 5.3 Flash, DeepSeek V4.1 Flash, GPT-6 Luna and Muse Spark, 26 games each
  against PokéChamp with notes shown (the last 3) and without (written, never shown). Every turn has notes;
  77-99% plan ahead (33-50 words). Shown notes are built on: 45-48% of the previous note carried forward (37-40%
  unseen). Muse held one plan for 12 turns ("preserve Multiscale, set up late, save Gholdengo") and won with it.
  Input +~150 tokens a turn (~7%). Results: 60 vs 61 wins of 104, no difference either way (a first 24-game
  sample looked 12-18 against notes: luck). Kept: notes as memory, 3 shown.
- **Draft prompts 2** (singles said outright) and **three drafts per model** (`drafts: 3`, played in turn).
  Smoke test: GLM and Sonnet, three legal, different teams each ($0.002 and $0.14). Sonnet dropped Tailwind and
  Rage Powder; it keeps Fake Out and Parting Shot on Incineroar, which singles uses too.
- **Medium effort** for everyone (decided): `reasoning: medium` with an 8,192 cap. Except Sonnet 5.5: at medium
  effort it never thought (0 thinking tokens in 85 c5 turns, batched or not; Opus, Haiku and Fable did), so c5
  asks it for the 4,096-token budget medium means for Claude (`thinking_exceptions` now takes a budget).
- **PokéChamp v4**: damaging moves listed first (a tie means attacking) and Sucker Punch fails against status
  moves: no more endless Swords Dance between two +6 Kingambit. Against MaxDamage 89-31 (v3: 92-28), mirror games
  8-11 turns.

Before c5 starts:
- **Local context**: a long game's prompt (~6,000 tokens by turn 20) plus 4,096 of thinking overflows the 8,192
  tokens per slot local servers have now: set `local_llm.ctx: 12288` and check the local models' VRAM in their
  smoke test (after c4's run, which uses the GPU).
- The all-model smoke test (2 games each against PokéChamp under c5, raw answers read), then drafting.

### c5 is played (13-14 Oct)
Smoke tests became the first real games: a **check run** (`ladder.ceiling`) capped every model at 2 games, then 9,
all against free opponents (the anchor, PokéChamp, the chimps); a watcher read every game for failed turns, answers
near the cap, reasoning spilled into answers and slow turns. Then the ceiling was lifted: the planned caps (cheap
120, DeepSeek V4.1 Flash and Solar Pro 4 60, mid 21, Opus and Sonnet 18, other expensive 9) and pairings. c5 replaced
c4 on the site on 13 Oct (c4 archived).

Found by the check run and fixed:
- **Dropped**: Mistral Large 4 and Hy4 Preview (think to the cap at any effort or budget), Nemotron 3 Ultra (NVIDIA's
  free endpoint down). Their unrepresentative games are voided by hand; Nemotron's valid ones stay.
- **A 4,096-token budget for everyone** instead of medium effort (an amendment recorded in data/rulesets/c5.json):
  measured per model, it changes Solar Pro 4, Qwen 27B, Qwen Max Prime, MiMo Pro, Grok, GLM 5.3, DeepSeek V4 Pro and
  Nemotron, whose 32 earlier games are tagged `superseded:medium-effort:<model>` and still count. **To do: void them
  once those models have enough games under the budget.** Exceptions: Gemini 4 Argon high effort (it barely thinks
  at any budget); Sonnet, Qwen Flash and MiniMax keep their own 4,096 entries (MiniMax overshoots it anyway: ~4%
  of its turns cut off).
- **Bugs**: a lowered evasion crashed battle state 3 (two games void, the run halted itself); a recharge turn crashed
  decision models, which now also play single-option turns without asking; batched answers were all rejected
  (`service_tier: "batch"`); Claude cached nothing (now cache breakpoints, ~43% of Opus's input from cache).
- **Against a control bot** the model is told it faces a copy of its own team (DeepSeek sacked a Pokémon to scout a
  move it already had); the 19 PokéChamp games before that note were voided by hand and replayed.
- **Hand-voided games don't use up caps** (`games_played`); the monitor's status no longer re-reads every match file
  per model (a minute per refresh, now seconds).
- Gemini 4 Argon added (13 Oct). **Relay games**: Argon played by hand in the Gemini app (Máx.) through the monitor's
  Relay panel, tagged `relay:gemini-app-max:gemini_4_argon`, rated but left out of cost figures.
- Ornith ran out of GPU memory twice with 2 slots (one game lost); if it recurs, give it 1 slot.

## 5. Scheduling: placement, then neighbours

Replaces the fixed round robin (325 pairs x 3 games, everyone against everyone):

1. **Placement against free opponents.** A new model first plays the anchor (GPT-OSS 20B, local), PokéChamp and
   the chimps: they cost nothing, so a paid model's first games cost only its own side.
2. **Neighbours.** Then it plays models near its current rating, where results are still in doubt. Close pairs
   can meet again.
3. **Stop at a precision target** (an interval half-width, e.g. +-100). Cheap models naturally play more.
4. **Expensive models ramp up** (decided 12 Oct): no dollar caps; expensive and very expensive models start with
   a low game cap, raised step by step as their games check out (answers, costs, no surprises), as Sonnet and
   Opus did in c4.

A newcomer then costs a bounded number of games instead of a match against every model (the first design's goal:
adding a model shouldn't re-bill the incumbents). Lost: the complete head-to-head matrix; featured best-of-threes
can still be scheduled by hand. `ladder place` and `ladder fill` exist from the first design.

## 6. Batch mode for expensive models

**Decided 12 Oct: we try it for the expensive and very expensive tiers.**

OpenRouter's Batch API (`/api/v1/batches`, models with a `:batch` variant) costs about half, with results within
24 hours (median reported in minutes). One turn becomes one batch round trip, so a game takes hours: it pays off
only when all of a model's games run at once (15-60 in parallel), each round's decisions sent as one batch per
model. Trades days of waiting for half the bill on the expensive tier. Claude through the Max plan's key (BYOK)
uses Anthropic's own batch discount on the plan's API credits.

Needs the simulator's parallelism first. Smoke test: one model, a few games; check that reasoning settings, the
answer format and per-request cost survive batching, and what the wait really is. Risk: a 24-hour worst case per
turn.

**Smoke test (12 Oct, built: `batch: {c5: true}` per model, llm/batch.py).** Sonnet 5.5, 4 games at once against
PokéChamp: every answer usable (57 model turns, no errors), **$0.063 a game against $0.12 direct**. Each batch took
2-17 minutes (mostly 5-10), so a game of ~15 turns took ~1h45. Wall time is per round, not per game: 4 games or 40
take about as long, so batched models need many games at once (more than `ladder.parallel_games` 4), e.g. their
whole set of opponents overnight. A first run lost every answer: OpenRouter labels batched results
`service_tier: "batch"`, which the openai library rejects (fixed, tested).

## 7. Site

- A rating-against-cost chart: who plays best for the money (price tiers already exist).
- "N of 24 models beat a calculator": PokéChamp as the line.
- A free "draft grade" right after drafting: the model's teams against reference teams, PokéChamp piloting both
  sides (like the 11 Oct experiment).
- Later: a reference above the models (a two-turn PokéChamp), maybe a human baseline.

## 8. Decisions and open questions

Decided 12 Oct: thoughts become memory for long-term planning; no dollar caps (expensive models ramp up their game
caps instead); batch mode is tried for the expensive and very expensive tiers.

Also decided 12 Oct: medium effort; notes of at most 60 words, the last 3 shown. c5's rules are complete.

Open (none of them a rule of the version, so they can change while c5 plays):
- The precision target.
- Batch mode: how the ladder plays batched models (all their games at once, not 4 at a time).

Prompt caching (checked 12 Oct): Claude cached nothing (Anthropic needs explicit breakpoints); now the system prompt
and the battle log (one block per turn) are breakpoints, and from the third turn about half of Sonnet's prompt is
read from cache at a tenth of the price. GPT-6 caches on its own; Gemini too once a prompt passes ~4,000 tokens
(mid-game on). Breadcrumbs now record `cached_tokens` and `cache_write_tokens`.
