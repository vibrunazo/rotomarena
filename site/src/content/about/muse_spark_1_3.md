---
title: Muse Spark 1.3, and its thinking exception
---

<div class="credit">

**Muse Spark is a model from [Meta](https://ai.meta.com/).** We call it through
[OpenRouter](https://openrouter.ai/meta/muse-spark-1.3-contributor), which routes it to Meta's own endpoint.

</div>

## Why it plays by a slightly different rule

Every model in a version may think for up to the same number of tokens per turn, then answer. Muse Spark can't be
given a number: [Meta's API](https://dev.meta.ai/docs/reasoning) controls its thinking only by effort level (minimal,
low, medium, high, xhigh), and a token budget sent through OpenRouter becomes one of those levels, which it overshoots.
In the first Champions versions, asked for 1,024 tokens of thinking, it thought for about 2,000 and ran into the
per-turn cap before answering on 24 of its first 53 turns. A cut-off answer plays the default move, so about half
of its moves weren't its own.

So Muse Spark gets an effort level instead of the token count, recorded in each version's rules as its exception:

- **Champions c1 to c3** (1,024 tokens for everyone): "minimal", about 335 tokens of thinking in our tests.
- **Champions c4** (2,048 tokens): "medium", a median of about 1,400 in our tests, sometimes more. It played its
  first 45 c4 games on "minimal", which left most of its budget unused; when the exception changed, those games were
  retired and replayed, and nobody else's games were touched.

## Things to know

- **It now thinks about as much as the others,** where it used to get about a third of the budget.
- **It is capped at 63 games in Champions c4,** like the other paid models: three against each opponent.
