# TODO

Things worth doing later, with enough context to start without the conversation they came from.

## Drafting options with descriptions (test, then maybe a new version)

**Idea.** Decision models draft from bare names: every species, item, ability and move is offered as its name only
(`teams/draft_decisions.py`). A model that knows Pokémon fills in the rest; a small one cannot. Showdown's
teambuilder shows a human player more next to each option: types and base stats for species, and the one-line
description of each item, ability and move. Offering the same would follow the battle state's rule (give what
Showdown's interface shows, nothing more). The texts are already in `data/dex/<mod>.json`
(`scripts/dump_dex_text.js`).

**What we saw (10 Oct 2026).** Laya (322M, `convaiinnovations/laya` multilingual) picking Torkoal's held item from 24
items including Victreebelite, Charcoal, Heat Rock and Leftovers:

| Options | Laya's pick | Probability it gave Victreebelite |
|---|---|---|
| names only (as drafted now) | Leftovers | 4.1% |
| with Showdown's descriptions | Cheri Berry | 0.8% |

Descriptions steered it away from a Mega Stone for another species, but it then matched on wording rather than
value. One model, one question: not enough to decide anything.

**The test.** Same drafting questions, names only vs with descriptions, for several decision models of different
sizes (e.g. Laya, Drex v1.5 locally, Microsoft-Decision-1, Jev 1.13, GPT-6 Luna Decisions):

- Species picks for a Champions team: does the pick change, and towards meta Pokémon (`meta score` on the Teams page
  compares with Smogon's usage)?
- Held items: wrong-species Mega Stones and other useless items, with and without descriptions.
- Abilities and moves for a few set questions: does the pick move to what a strong player would choose?
- Record each option's probability, not just the pick; repeat each question a few times where the model isn't
  deterministic.

Run it against the drafting functions directly (scratch script, nothing saved to `data/drafts`), with free or
cheap models, outside a run's Showdown server. The LLM drafting prompt would get the same texts for parity.

**If it helps.** It changes the drafting rules (`decision_draft_prompt` and `draft_prompt` fingerprints), so it ships
as a new version with every model re-drafted, never mid-version.

## Champions draft prompt: say singles (next version)
c4's draft prompt says "bring 3 of your 6" but never "singles": only the format name's "BSS" (Battle Stadium Singles)
does, and "Regulation M-B" also names Champions' doubles rules. Sonnet 5.5 built for doubles (Protect x4, Fake Out,
Rock Slide, Tailwind), Haiku 5.5 too (Rage Powder), Gemma, Muse, GLM and MiniCPM partly. Next version: the rules line
"Singles: one Pokémon on the field per side; you bring 3 of your 6 to each battle and choose which." Sonnet and Opus
play only the top 5 in c4 (15 games) and get their full runs then.
