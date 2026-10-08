# Credits and provenance

Where RotomArena's parts come from, traced through the original Antigravity session that scaffolded the project
(Gemini, 29 August 2026; the user's opening prompt is in `docs/iniprompts.md`) and the git history since.

## PokéChamp (design)

Seth Karten, Andy Luu Nguyen and Chi Jin, *PokéChamp: an Expert-level Minimax Language Agent*, ICML 2025
(arXiv:2503.04094). Project page: https://sites.google.com/view/pokechamp-llm. Code:
https://github.com/sethkarten/pokechamp.

The opening prompt asked for a testbed "integrating PokéChamp". The PokéChamp code was never cloned or installed:
the scaffolding session ran three web searches about the paper (transcript steps 12, 16 and 22), whose summaries
describe its minimax search with a language model doing action sampling, opponent modeling and position evaluation,
and then wrote `src/rotomarena/search/` and `src/rotomarena/agents/pokechamp.py` from scratch (steps 72 to 94),
replacing each of those language-model parts with a hand-written rule. RotomArena therefore implements PokéChamp's
design without its language model and contains no code from the PokéChamp repository. The design, the name and the
idea of measuring language models at competitive Pokémon are theirs, and the site credits them as such.

## Pokémon Showdown

Guangcong Luo and contributors, MIT license, https://github.com/smogon/pokemon-showdown. Cloned and run locally at
setup (`server/`, not part of this repository). The replay player on the site loads Showdown's client
(`replay-embed.js`, sprites and effects) from play.pokemonshowdown.com at view time.

## poke-env

Haris Sahovic and contributors, MIT license, https://github.com/hsahovic/poke-env. A Python dependency.

## Teams (`data/teams/`)

Written by the scaffolding session from its own knowledge of the Gen 9 OU metagame (transcript steps 40 to 46,
described as "authentic Gen 9 OU sample teams"); no source was looked up, so no team builder can be credited. The
first test battle was rejected by Showdown ("Roaring Moon is tagged Uber, which is banned"), and the session
replaced Roaring Moon with Samurott-Hisui and, in the same pass, Archaludon with Zapdos (steps 446 to 462). The sets
reflect what Smogon's players developed for the format; they do not match Smogon's current SV OU sample-team thread.

## Smogon

The Gen 9 OverUsed tier, its rules, and the team export format.
