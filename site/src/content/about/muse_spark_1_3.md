---
title: Muse Spark 1.3, and its thinking exception
---

<div class="credit">

**Muse Spark is a model from [Meta](https://ai.meta.com/).** We call it through
[OpenRouter](https://openrouter.ai/meta/muse-spark-1.3-contributor), which routes it to Meta's own endpoint.

</div>

## Why it plays by a slightly different rule

Every model in this version may think for up to 1,024 tokens per turn, then answer. Meta's endpoint ignores that
budget: asked for 1,024 tokens of thinking, Muse Spark thought for about 2,000 and ran into the per-turn cap before
it could answer, on 24 of its first 53 turns. A cut-off answer plays the default move, so about half of its moves
weren't its own.

The endpoint does follow effort levels, so Muse Spark gets the strongest one that stays within the budget,
"minimal" (about 335 tokens of thinking in our tests), instead of the token count. The exception is recorded in this
version's rules. Its first two games, played before it, are voided, and it drafted its team again under the
exception.

## Things to know

- **It thinks less than the others.** About a third of the budget, where most models use most of it. That is a
  handicap, but a smaller one than losing half its turns.
- **It is capped at 8 games** for now, like the other paid models; the two voided games count toward the cap, since
  they were paid for.
