---
title: What PokéChamp is, and why it is here
---

<div class="credit">

**PokéChamp is the work of Seth Karten, Andy Luu Nguyen and Chi Jin**, published as
*PokéChamp: an Expert-level Minimax Language Agent*, a spotlight paper at ICML 2025.
[Project page](https://sites.google.com/view/pokechamp-llm) ·
[Paper (arXiv:2503.04094)](https://arxiv.org/abs/2503.04094) ·
[Code](https://github.com/sethkarten/pokechamp) ·
[Dataset](https://huggingface.co/datasets/milkkarten/pokechamp)

Their work showed that a language model can play competitive Pokémon at a high level when it sits inside a
game-theoretic search, and gave the field the tools and data to test that. This benchmark would not exist without
it. Seth Karten and Chi Jin, with collaborators from UT Austin, NYU, Johns Hopkins, Google DeepMind and Carnegie Mellon, also
organize the [PokéAgent Challenge](https://pokeagent.github.io/), a NeurIPS 2025 competition on Pokémon battling and
speedrunning agents.

</div>

## The version that plays here

The original PokéChamp is a minimax agent with a language model inside it: the model proposes candidate actions,
predicts what the opponent will do, and judges the positions the search reaches. What plays on RotomArena is our own
implementation of that design, written from the paper's description, **with the language model taken out**: every
one of those three jobs is done by a hand-written rule instead. It contains none of their code. We use it as a fixed reference opponent, not as a reproduction of the
paper's agent, which should be judged by the paper's own results.

So when the leaderboard says "PokéChamp", read it as "PokéChamp's search, without its brain". It reads no prompt,
writes no explanation and produces no tokens. Every turn, in a few milliseconds, it:

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
5. **Picks the action whose worst outcome is best.** This is the minimax idea at the heart of PokéChamp: assume
   the opponent finds the reply that hurts most, and play whatever survives that best.

It chooses its lead at random, which is the one part of its strategy it shares with Random AI.

## What our version cannot do

It looks exactly one turn ahead. It does not plan a sweep, scout, predict a double switch, save a Pokémon for
later, or remember what worked last game. Its damage formula ignores items and every ability except Guts, and it
knows nothing about the metagame beyond what that formula implies. Without the language model that the original
puts at its core, it is a calculator with opinions about HP.

That is what we want from a reference opponent: simple enough to describe in five steps, so that a result against
it means something.

## Why it is in the rankings

**It is a fixed yardstick.** Ratings only mean something relative to opponents whose strength does not change.
Our PokéChamp never updates, never gets deprecated and costs nothing to run, so every model added to the ladder,
now or later, plays the same set of games against the same program. That is what makes a rating
from one month comparable with a rating from the next.

**It sits where the interesting comparisons are.** Random AI marks the floor: a model that loses to it is broken.
PokéChamp's search marks something more useful, the strength of one-turn arithmetic done perfectly. A language
model that beats it is doing something a calculator cannot. A language model that loses to it has read the whole
battle, reasoned about it at length, and been outplayed by a handful of weighted numbers. The PokéChamp paper's
central point is that the best results come from combining the two.

**It is rated like everyone else.** Its rating is fitted from its games, with its own error bars, on the same
scale as the models. It is not the fixed point of the scale: that is the anchor model, which sits at 1500 by
definition. It has no rank number, because the ranking is for language models; it appears on the leaderboard the
way a reference line appears on a chart.

## Statistics that do not apply

Our PokéChamp has never hallucinated a move, run out of tokens, timed out, or been rate-limited. It has also never
explained a single decision. The autopilot, token and cost columns on the leaderboard are left blank for it,
which we consider a fair summary of its personality.

<p class="small muted">The design, the name and the idea are PokéChamp's; the implementation, and any mistakes in it,
are ours. Their own code is at github.com/sethkarten/pokechamp.</p>
