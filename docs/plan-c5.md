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
2. **c5 rules** (section 4): prompt fixes, three drafts per model, both-ways pairs, waste cuts.
3. **Scheduling** (section 5): free placement, then neighbours, to a precision target.
4. **Batch mode for expensive models** (section 6), once the simulator runs many games at once.
5. Site additions (section 7).

Each step: smoke test (a few games, free or cheap models first), read the raw answers, then commit.

## 3. Simulator instead of the chat server

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
- **Thoughts: drop them, or make them memory** (decide by smoke test). Today they are display only: nothing
  carries between turns. Either (a) drop the visible thought (saves ~5% of output; video matches become
  exhibition games with thoughts on, unrated), or (b) make it notes for later turns: the prompt says what they
  are for ("your plan, what you've learned about their sets"), no punchline-brevity rule, a cost cap (~60 words),
  and each turn shows the earlier notes. Test both with cheap models against PokéChamp: cost per game and results.

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

### Both-ways pairs
A pair's games come in twos: each model once with its own team, once with its opponent's (as in duplicate
bridge). The rating fits how well each model plays and how strong its teams are, and **publishes only the sum**:
its own team, played by itself, as now. Swapped games still inform that sum (how it plays, how its team does in
other hands), and team matchups stop adding noise. Pairs play in units of two: 2, 4, 6 games. The control bots
already borrow their opponent's team, so they're unchanged.

Alternatives considered: fixed meta teams (no Champions BSS Reg M-B sample-teams thread found on Smogon; ladder
usage data exists) and random teams (more luck per game). Swapping needs nothing outside the field itself.

### Waste
- **No model call when only one action is legal** (7% of decisions, 4% of cost): play it and record it as such.
- Look into GPT-6 Luna Pro's input-token count before c5 (see section 1).

## 5. Scheduling: placement, then neighbours

Replaces the fixed round robin (325 pairs x 3 games, everyone against everyone):

1. **Placement against free opponents.** A new model first plays the anchor (GPT-OSS 20B, local), PokéChamp and
   the chimps: they cost nothing, so a paid model's first games cost only its own side.
2. **Neighbours.** Then it plays models near its current rating, in both-ways pairs, where results are still in
   doubt. Close pairs can meet again (4, 6 games).
3. **Stop at a precision target** (an interval half-width, e.g. +-100) or the model's dollar cap, whichever comes
   first. Cheap models naturally play more; expensive ones only what's needed.

A newcomer then costs a bounded number of games instead of a match against every model (the first design's goal:
adding a model shouldn't re-bill the incumbents). Lost: the complete head-to-head matrix; featured best-of-threes
can still be scheduled by hand. `ladder place` and `ladder fill` exist from the first design.

## 6. Batch mode for expensive models

OpenRouter's Batch API (`/api/v1/batches`, models with a `:batch` variant) costs about half, with results within
24 hours (median reported in minutes). One turn becomes one batch round trip, so a game takes hours: it pays off
only when all of a model's games run at once (15-60 in parallel), each round's decisions sent as one batch per
model. Trades days of waiting for half the bill on the expensive tier. Claude through the Max plan's key (BYOK)
uses Anthropic's own batch discount on the plan's API credits.

Needs the simulator's parallelism first. Smoke test: one model, a few games; check that reasoning settings, the
answer format and per-request cost survive batching, and what the wait really is. Risk: a 24-hour worst case per
turn.

## 7. Site

- A rating-against-cost chart: who plays best for the money (price tiers already exist).
- "N of 24 models beat a calculator": PokéChamp as the line.
- A free "draft grade" right after drafting: the model's teams against reference teams, PokéChamp piloting both
  sides (like the 11 Oct experiment).
- Later: a reference above the models (a two-turn PokéChamp), maybe a human baseline.

## 8. Open questions

- Thoughts: dropped or memory (smoke test decides).
- Precision target and dollar caps per tier.
- Batch mode: the real wait and real price, per model.
