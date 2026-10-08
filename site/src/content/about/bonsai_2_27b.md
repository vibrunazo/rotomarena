---
title: What Bonsai is, and why everything is measured against it
---

<div class="credit">

**Bonsai 2 27B is made by [Prism ML](https://prismml.com).** It is a ternary version of Qwen3.8-27B: every
language weight is stored as one of three values, which makes the model about nine times smaller than at full
precision while, by Prism ML's measurements, keeping most of its ability.
[Model card](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf) ·
[Whitepaper](https://github.com/PrismML-Eng/Bonsai-demo/blob/main/bonsai-2-27b-whitepaper.pdf) ·
[llama.cpp fork](https://github.com/PrismML-Eng/llama.cpp) · Apache 2.0

</div>

## What it does here

Bonsai is the **anchor** of the rating scale. Its rating is 1500 by definition, its error bars are zero by
construction, and every other number on the leaderboard says how much better or worse a model is than Bonsai.

It plays exactly like every other contestant: the same prompt, the same two teams, the same token budget, the same
rules for autopilot and void games. It runs on our own machine, on a single consumer graphics card, through Prism
ML's fork of llama.cpp, using the PQ2_0 packing (each three-valued weight stored in two bits).

## Why it is the anchor

A rating scale needs a fixed point, and the best fixed point is one that will still be there next year.

- **It cannot be deprecated.** The weights are on our disk. No vendor can retire it, change it silently, or
  raise its price.
- **It costs nothing per game.** It meets every new model during placement, and that has to be affordable
  forever.
- **It is a language model.** Anchoring to a bot would measure models against arithmetic; anchoring to a model
  measures them against another model, which is the question the leaderboard asks.

Choosing an anchor only decides where the numbers sit, not the gaps between them: had we pinned a different model at
1500, every rating would shift by the same amount and the order would not change.

## What it is not

Bonsai is not expected to be the best model here, and its rating says nothing about that: being the reference and
being good are different jobs. It is a 27-billion-parameter model compressed to fit on a laptop.

## A comparison built into the season

Qwen3.8 27B, the model Bonsai was made from, is also in the season 1 lineup, in a conventional 4-bit
quantization. Once both have played their placements, the leaderboard will show what ternary weights cost, or do not
cost, in competitive Pokémon. Prism ML did not ask us to test this, and we did not ask them first.

## A practical note

On our graphics card one game of Bonsai uses all of it: its custom ternary kernels keep the GPU at full power from
a single request, so unlike most models it gains nothing from playing several games at once. It is quick anyway.
