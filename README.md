# ⚡ RotomArena

**A competitive Pokémon benchmark for language models.** Each model drafts its own team, then battles every other
model on [Pokémon Showdown](https://github.com/smogon/pokemon-showdown), one decision per turn. Ratings, every game's
replay and every model's reasoning are on the site: **[rotomarena.org](https://rotomarena.org/)**.

It is a joke presented with a straight face, and a real benchmark underneath: the rules are frozen per version, every
model gets the same prompt, budget and referee, and every number on the site is computed from recorded games.

---

## What it measures

The main benchmark, **Rotom Champ Bench** (ruleset `c5`), is Pokémon Champions singles under Regulation M-B: level 50,
bring six and pick three, Champions' Stat Points, one item per Pokémon, Mega Evolution instead of Terastallization.
An older **Rotom Gen9 Bench** (Gen 9 OU) is archived on the site.

- **Teams.** Each model drafts three teams from the format's legal lists: six picks, then each set's ability, item,
  nature, spread and moves. Showdown's validator referees; a team still illegal after five tries is repaired with
  middling replacements, and the site says so. A model's games take its three drafts in turn.
- **Battles.** Every turn the model gets the battle as Showdown's interface shows a player (the log so far, each legal
  move's tooltip, the opponent's possible stats, no damage calculator) and its own notes from its last three turns,
  then answers with a short thought and one legal action. Hidden thinking is capped at a 4,096-token budget inside an
  8,192-token turn. An answer that is cut off, unparseable or illegal gets one retry, told what was wrong; after
  that the default move plays and the turn is counted as a hallucination.
- **Ratings.** A Bradley-Terry fit on the Elo scale, anchored to GPT-OSS 20B at 1500, with bootstrap 95% intervals.
  Games where a side played the default move on most of its turns are void. The site also shows cost per game
  (OpenRouter's billed cost), tokens per turn and a rating-versus-cost chart.
- **Players.** Language models through OpenRouter or local llama.cpp servers; *decision models* (which return a
  probability for each option instead of text); **PokéChamp**, our rule-based implementation of the PokéChamp search
  ([Karten et al., ICML 2025](https://arxiv.org/abs/2503.04094)) with the language model taken out; and Random AI.

## Quick start

Needs Python 3.10+ with [uv](https://docs.astral.sh/uv/), Node.js 22 and git.

```bash
uv sync
cp .env.example .env              # add OPENROUTER_API_KEY
uv run rotomarena server setup     # clones and builds Pokémon Showdown into server/ (with our format copies)
```

A free test game (no API key needed), PokéChamp against the heuristic bot:

```bash
uv run rotomarena battle --p1 pokechamp --p2 heuristic --games 1
```

A registry model against PokéChamp (`config.yaml` → `agents:` lists every model and how it is called):

```bash
uv run rotomarena battle --p1 deepseek_v4_1_flash --p2 pokechamp --games 2
```

Test games play under the version in `play:`, so point `--config` at a scratch copy of `config.yaml` with its own
`ruleset.version` and `telemetry.output_dir`; then they never mix with a real benchmark's games.

## Running the ladder

```bash
uv run rotomarena teams draft <config id>        # a model drafts its teams (data/drafts/<format>/<version>/)
uv run rotomarena ladder round-robin              # every model plays every other one; resumable
uv run rotomarena ladder status                   # ratings of the version being played
uv run rotomarena export-site --out site/src/data # JSON for the website
```

`config.yaml` holds everything that decides a game: `rulesets:` (every playable version), `play:` (the one commands
use), `benchmarks:` (what the site ranks), `ladder:` (pairing, caps, anchors) and the model registry. A version's
exact rules are stored in `data/rulesets/<version>.json` on its first game, and ladder commands refuse to play if the
configuration no longer matches.

Games go to `runs/` (not in the repository): each has `breadcrumbs.json` (every decision with its thought, timing,
tokens and cost), `battle_log.json` (seed and input log, so it can be replayed exactly) and `replay.html`.

On Windows, `scripts\monitor.ps1` starts a run monitor at http://localhost:8765/: progress, live battles with the
models' thoughts, spending, and Start, Stop and Publish buttons. Long runs should start from there rather than a
terminal you might close.

**Local models.** `provider: "local"` entries talk to an OpenAI-compatible llama.cpp server on the entry's `port`. Our
setup starts and stops those servers through a personal tool (`local_llm.gen` in `config.yaml`) that isn't public;
set `local_llm.manage: false` and start a `llama-server` on each port yourself instead.

## The website

`site/` is an [Astro](https://astro.build/) static site built from the exported JSON:

```bash
cd site && pnpm install && pnpm run build   # large data: NODE_OPTIONS=--max-old-space-size=6144
```

## Laya RotomArena

`scripts/laya/` fine-tunes [Laya](https://huggingface.co/convaiinnovations/laya), an open decision model, to draft
teams: open-weight models whose licenses allow training on their outputs draft a pool of teams, a league rates the
teams, and the stronger teams become Laya's lessons. Its model page on the site credits every source model.

## Repository

```
config.yaml          rulesets, benchmarks, ladder settings and the model registry
src/rotomarena/
  agents/            players: LLM, decision model, PokéChamp, baselines
  llm/               provider client, prompts, battle state, batching
  search/            PokéChamp's one-turn maximin search and simulator
  server/            Showdown: the simulator driver, our format copies, the chat-server manager
  teams/             drafting, the validator, team parsing
  ladder.py          round robin, placement, pairing and caps
  rating.py          Bradley-Terry ratings with bootstrap intervals
  export/            the site's JSON
  dashboard/         the run monitor
data/
  drafts/            every team each model drafted, per version
  rulesets/          each version's stored rules
  teams/             sample teams (Smogon's are credited in data/teams/smogon/index.json)
  laya/              Laya's draft pool, team leagues and test drafts
docs/                plans and the project's opening prompt
scripts/             the run monitor, Laya's pipeline and maintenance scripts
site/                the website
tests/               pytest suite (uv run pytest)
```

## Credits

PokéChamp's design is the work of Seth Karten, Andy Luu Nguyen and Chi Jin; RotomArena's version is written from the
paper and contains none of their code. Battles run on Pokémon Showdown (Guangcong Luo and contributors) through
[poke-env](https://github.com/hsahovic/poke-env). Full provenance, including where each part of this repository came
from, is in [CREDITS.md](CREDITS.md).

## License

As close to the public domain as each kind of work allows; no attribution required.

- **Code** (`src/`, `tests/`, `site/` source, scripts): [MIT No Attribution](LICENSE) (MIT-0). Code takes MIT-0 rather
  than CC0 because CC0 explicitly withholds patent rights and isn't an OSI-approved software license.
- **Data and writing** (match records, ratings, rulesets, model-built teams in `data/drafts/`, the teams in
  `data/teams/*.txt`, the site's text and the paper): [CC0 1.0](LICENSES/CC0-1.0.txt), to the extent we hold any
  rights in them. Model-written text (thoughts, teams) is released as recorded.
- **Not ours, so not covered:** the reference teams in `data/teams/smogon/` belong to their builders (credited in its
  `index.json`); Pokémon Showdown, poke-env and other dependencies keep their own licenses (see [CREDITS.md](CREDITS.md));
  Pokémon names and sprites are trademarks of Nintendo, Creatures and GAME FREAK, and no license grants trademark rights.
