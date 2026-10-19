---
title: What Laya RotomArena is, and whose teams taught it
---

<div class="credit">

**Laya RotomArena is [Laya](https://huggingface.co/convaiinnovations/laya), Convai Innovations' decision model
(its multilingual checkpoint, 322M parameters, Apache-2.0), fine-tuned by us** to draft Pokémon Champions teams. It
learned from teams drafted by the open-weight models credited below, whose licenses allow training on what they
write. **Built with Muse Spark Open**: Muse Spark Open's drafts are used under Meta's Muse Model License and its
Usage Policy.

</div>

## Why it exists

Base Laya drafts the same team every time: Rotom, Torkoal, Torterra, Scrafty, Sinistcha and Gourgeist. Piloted by
PokéChamp against the 228 teams the language models drafted, that team won 1 game in 60 and ranked last. A decision
model has no way to look up what wins, so we showed it.

## How it was taught

1. **Drafts.** 27 open-weight models drafted Pokémon Champions teams under c5's own rules, prompts and referee: the
   teams they play on the ladder, plus 8 extra drafts each from the API models. 228 distinct legal teams in all.
2. **A league of teams.** PokéChamp piloted both sides of every game, so the teams were the only difference. Each
   team played at least 40 games against random others; a Bradley-Terry fit turned the results into ratings.
3. **Lessons.** Every team rated above the pool's average became the questions Laya answers when it drafts, in the
   same wording and option lists, with that team's choices as the answers: its six picks, then each Pokémon's
   ability, item, nature, spread and four moves. Stronger teams count more. One team in ten was held out.
4. **Keeping its battling.** Laya's own answers from 300 games against PokéChamp went in beside the drafting lessons,
   so the fine-tune keeps battling as base Laya did.
5. **Training:** two epochs with Laya's own trainer (`laya-train`), on one consumer GPU, in about an hour.

## What changed

| | Base Laya | Laya RotomArena |
|---|---|---|
| Its team | Rotom, Torkoal, Torterra, Scrafty, Sinistcha-Masterpiece, Gourgeist-Super | Dragonite, Dragapult, Garchomp, Gholdengo, Kingambit, Rotom-Wash |
| Its team in the league (60 games each) | 829, last of 230 | 1542, 105th of 230 |
| Held-out drafting questions answered as the teams did | 29% | 68% |
| Wins against PokéChamp, same 200 team pairings | 9 | 14 |

It drafts far better and battles about as badly as before: it was taught to build teams, not to play them.

## Whose drafts taught it

Every model below drafted teams in the pool; the number is how many of its teams rated above average and became
lessons.

| Model | License | Teams used |
|---|---|---|
| [DeepSeek V4.1 Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash) | MIT | 12 |
| [GLM 5.3](https://huggingface.co/zai-org/GLM-5.3) | GLM-5.3 License | 11 |
| [Kimi K3](https://huggingface.co/moonshotai/Kimi-K3) | Kimi K3 License | 10 |
| [MiMo V2.6 Pro](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-RL) | MIT | 10 |
| [DeepSeek V4 Pro](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro) | MIT | 9 |
| [GLM 5.3 Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) | MIT | 9 |
| [GLM 5.2](https://huggingface.co/zai-org/GLM-5.2) | MIT | 8 |
| [Muse Spark Open](https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B) | Muse Model License | 8 |
| [MiMo V2.6 Flash](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Flash-RL) | MIT | 7 |
| [Qwen3.8 27B](https://huggingface.co/Qwen/Qwen3.8-27B) | Apache-2.0 | 7 |
| [Reflection Beam 1.0](https://huggingface.co/reflection/Beam-1.0-501B-A23B) | Apache-2.0 | 6 |
| [Gemma 4 31B](https://huggingface.co/google/gemma-4-31B-it) | Apache-2.0 | 5 |
| [Ling 3.1 Flash](https://huggingface.co/inclusionAI/Ling-3.1-flash) | MIT | 4 |
| [Ling 3.0 Flash](https://huggingface.co/inclusionAI/Ling-3.0-flash) | MIT | 3 |
| [Nex N2.5 Pro](https://huggingface.co/nex-agi/Nex-N2.5-Pro) | Apache-2.0 | 3 |
| [Inkling Small](https://huggingface.co/thinkingmachines/Inkling-Small) | Apache-2.0 | 3 |
| [Tencent Hy3](https://huggingface.co/tencent/Hy3) | Apache-2.0 | 3 |
| [Nemotron 3.5 Super VL](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16) | OpenMDW-1.1 | 2 |
| [Nemotron 3 Ultra](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16) | OpenMDW-1.1 | 2 |
| [Bonsai 2 27B](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf) | Apache-2.0 | 2 |
| [Muse Glimmer 30B](https://huggingface.co/meta-models/Muse-Glimmer-30B) | Apache-2.0 | 2 |
| [LongCat 2.0](https://huggingface.co/meituan-longcat/LongCat-2.0) | MIT | 2 |
| [GPT-OSS 20B](https://huggingface.co/openai/gpt-oss-20b) | Apache-2.0 | 1 |
| [Ornith 1.5 35B](https://huggingface.co/ornith-ai/ornith-1.5-35b-a3b) | MIT | 1 |
| [Nex N2.5 Mini](https://huggingface.co/nex-agi/Nex-N2.5-mini) | Apache-2.0 | 1 |

Ling 3.0 Tiny and Granite 4.2 8B drafted too, but none of their teams rated above average. Left out on purpose:
every closed model (their terms forbid training on their outputs), MiniMax M3 (its license is non-commercial) and
Drex (its license counts any model trained on its outputs as a derivative, and bars competing decision models).

The teams were rated with our [PokéChamp](/models/pokechamp/), and Showdown's validator refereed every draft, as on
the ladder.
