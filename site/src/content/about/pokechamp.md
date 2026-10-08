---
title: What PokéChamp is, and why it is here
---

PokéChamp is not a language model. It is a small search program, written for this benchmark, that plays the same
battles under the same rules as every model on the leaderboard. It reads no prompt, writes no explanation and
produces no tokens. It is here so that the language models have something fixed to be measured against.

## How it plays

Every turn, PokéChamp does the same thing, in a few milliseconds:

1. **Lists every legal action.** Each available move, each move again with Terastallization if that is still
   possible, and each switch.
2. **Guesses the opponent's three likeliest replies.** Moves it has already seen the opponent use, weighted by
   power and by how well they hit its own active Pokémon. If it has seen none yet, it assumes a strong attack of
   each of the opponent's types. If its own Pokémon threatens a super-effective hit, it also considers the
   opponent switching out.
3. **Plays out one turn for every pairing** with an approximate damage formula: real stats for its own Pokémon,
   estimates from base stats for the opponent's, entry hazards on switch-in, and a small penalty for switching,
   which costs a turn.
4. **Scores each resulting position** with a hand-tuned evaluation. Pokémon left standing count most, then HP,
   then status conditions and type matchups, then stat boosts and entry hazards.
5. **Picks the action whose worst outcome is best.** This is maximin search with alpha-beta pruning: it assumes
   the opponent will find the reply that hurts most, and plays whatever survives that best.

It chooses its lead at random, which is the one part of its strategy it shares with Random AI.

## What it cannot do

PokéChamp looks exactly one turn ahead. It does not plan a sweep, scout, predict a double switch, save a Pokémon
for later, or remember what worked last game. Its damage formula ignores items and every ability except Guts, and it
knows nothing about the metagame beyond what that formula implies. It is, in short, a calculator with opinions about HP.

This is deliberate. A reference opponent should be simple enough to describe in five steps, so that a result
against it means something.

## Why it is in the rankings

**It is a fixed yardstick.** Ratings only mean something relative to opponents whose strength does not change.
PokéChamp never updates, never gets deprecated and costs nothing to run, so every model added to the ladder, in
this season or a later one, plays the same set of games against the same program. That is what makes a rating
from one month comparable with a rating from the next.

**It sits where the interesting comparisons are.** Random AI marks the floor: a model that loses to it is broken.
PokéChamp marks something more useful, the strength of one-turn arithmetic done perfectly. A language model that
beats it is doing something a calculator cannot. A language model that loses to it has read the whole battle,
reasoned about it at length, and been outplayed by a handful of weighted numbers.

**It is rated like everyone else.** Its rating is fitted from its games, with its own error bars, on the same
scale as the models. It is not the fixed point of the scale: that is the anchor model, which sits at 1500 by
definition. PokéChamp has no rank number, because the ranking is for language models; it appears on the
leaderboard the way a reference line appears on a chart.

## Relation to the PokéChamp paper

The name and the minimax idea come from *PokéChamp: an Expert-level Minimax Language Agent* (Karten, Nguyen and
Jin, 2025), whose agent uses a language model inside its search to propose actions, predict the opponent and
evaluate positions. Ours replaces every one of those with a hand-written rule. It should not be taken as
representative of the original, which we expect would beat it.

## Statistics that do not apply

PokéChamp has never hallucinated a move, run out of tokens, timed out, or been rate-limited. It has also never
explained a single decision. The autopilot, token and cost columns on the leaderboard are left blank for it,
which we consider a fair summary of its personality.
