"""Teambuilding for decision models, which can't write a team: they build it one Choice question at a time, from the
same legal lists the LLMs get, under the same rules, referee and repair.

Stage 1 picks six Pokémon one by one (options: the legal list, minus species already taken under Species Clause).
Stage 2 builds each set: its ability, item, Tera Type, nature and EV spread in one request, then its four moves one
at a time. LLMs write any EVs; a decision model picks one of the common spreads in EV_SPREADS. Under Item
Clause (Champions) an item a teammate already holds isn't offered, as a species already taken isn't. Showdown validates
the team; a rejected one is rebuilt with the problems added to the state, and after ATTEMPTS it is repaired."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from rotomarena.config import AgentConfig, AppConfig
from rotomarena.llm.decisions import Choice, DecisionClient, Question, Usage
from rotomarena.teams.draft import (
    ATTEMPTS, DraftUnavailable, PROMPT_VERSION, format_rules, is_champions, repair_team, species_options, system_prompt,
    validate_team,
)

DECISION_DRAFT_VERSION = "decision-draft-1"
EV_SPREADS = {
    "252 Atk / 4 SpD / 252 Spe": "Fast physical attacker.",
    "252 SpA / 4 SpD / 252 Spe": "Fast special attacker.",
    "4 Atk / 252 SpA / 252 Spe": "Fast mixed attacker.",
    "252 HP / 252 Atk / 4 SpD": "Bulky physical attacker.",
    "252 HP / 252 SpA / 4 SpD": "Bulky special attacker.",
    "252 HP / 4 Def / 252 Spe": "Bulky and fast.",
    "252 HP / 252 Def / 4 SpD": "Physically defensive.",
    "252 HP / 4 Def / 252 SpD": "Specially defensive.",
    "252 HP / 128 Def / 128 SpD": "Mixed defensive.",
}
# The same spreads in Pokémon Champions Stat Points (at most 32 in a stat, 66 in all)
CHAMPIONS_SPREADS = {
    "32 Atk / 2 SpD / 32 Spe": "Fast physical attacker.",
    "32 SpA / 2 SpD / 32 Spe": "Fast special attacker.",
    "2 Atk / 32 SpA / 32 Spe": "Fast mixed attacker.",
    "32 HP / 32 Atk / 2 SpD": "Bulky physical attacker.",
    "32 HP / 32 SpA / 2 SpD": "Bulky special attacker.",
    "32 HP / 2 Def / 32 Spe": "Bulky and fast.",
    "32 HP / 32 Def / 2 SpD": "Physically defensive.",
    "32 HP / 2 Def / 32 SpD": "Specially defensive.",
    "32 HP / 17 Def / 17 SpD": "Mixed defensive.",
}


def spreads_for(fmt: str) -> dict:
    return CHAMPIONS_SPREADS if is_champions(fmt) else EV_SPREADS
PICK_INSTRUCTIONS = ("You are building a team for competitive Pokémon battles on Pokémon Showdown under the rules in "
                     "the state, and you will play it yourself in rated battles. Which legal Pokémon should be pick "
                     "{n} of 6, to give the team the best chance to win?")
SET_INSTRUCTIONS = ("You are building {species}'s set for your team (the state has the rules and the team so far). "
                    "Which {what} should {species} have, to give the team the best chance to win?")
MOVE_INSTRUCTIONS = ("You are building {species}'s set for your team (the state has the rules and the team so far). "
                     "Which move should be its move {n} of 4, to give the team the best chance to win?")


def set_text(s: Dict[str, Any]) -> str:
    """One set in Showdown's export format."""
    lines = [f"{s['species']} @ {s['item']}" if s.get("item") else s["species"]]
    for key, label in (("ability", "Ability"), ("tera", "Tera Type"), ("evs", "EVs")):
        if s.get(key):
            lines.append(f"{label}: {s[key]}")
    if s.get("nature"):
        lines.append(f"{s['nature']} Nature")
    lines += [f"- {m}" for m in s.get("moves", [])]
    return "\n".join(lines)


async def draft_team_by_decisions(agent: AgentConfig, app_cfg: AppConfig, attempts: int = ATTEMPTS,
                                  log=print) -> Dict[str, Any]:
    """The same record as draft_team (picks, attempts, legal, team, repairs), built from Choice answers."""
    rules = format_rules(app_cfg)
    client = DecisionClient.for_model(agent.model, app_cfg, agent.provider or "openrouter")
    record: Dict[str, Any] = {
        "config_id": agent.name, "model": client.model, "provider": client.provider_name,
        "model_key": agent.canonical_model_key(), "quantization": agent.quantization,
        "format": rules["id"], "prompt_version": PROMPT_VERSION, "decision_version": DECISION_DRAFT_VERSION,
        "ruleset_version": app_cfg.ruleset.version,
        "drafted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "picks": {"attempts": [], "legal": False, "species": [], "repairs": []},
        "attempts": [], "legal": False, "team": None, "thought": None, "repaired": False, "repairs": [],
    }

    async def ask(state: str, questions: Dict[str, Question], usage: Usage) -> Dict[str, Choice]:
        try:
            answers, used = await client.choose(state, questions)
        except Exception as e:
            raise DraftUnavailable(f"provider error: {str(e)[:300]}") from e
        usage.add(used)
        return answers

    rules_text = system_prompt(rules, with_species=False)
    champions = is_champions(rules["id"])

    # Stage 1: six picks, one at a time; Species Clause is kept by leaving taken species out of the options
    usage, picks, notes = Usage(), [], []
    for n in range(1, 7):
        taken = {rules["base"].get(p, p) for p in picks}
        options = {s: s for s in rules["species"] if rules["base"].get(s, s) not in taken}
        state = rules_text.replace("(you have already picked yours)", "(the options of this question)") + \
            f"\n\nYour team so far: {', '.join(picks) or 'nobody yet'}."
        choice = (await ask(state, {"pick": Question(PICK_INSTRUCTIONS.format(n=n), options)}, usage))["pick"]
        picks.append(choice.choice)
        notes.append(f"Pick {n}: {choice.summary()}")
    record["picks"]["attempts"].append(_attempt(1, usage, "\n".join(notes), {"pokemon": picks, "problems": []}))
    record["picks"].update(legal=True, species=picks)
    log(f"  picks: {', '.join(picks)}")

    # Stage 2: the sets
    options = species_options(app_cfg, picks)
    problems: List[str] = []
    team: Optional[str] = None
    for attempt in range(1, attempts + 1):
        usage, notes, sets = Usage(), [], []
        for species in picks:
            o = options.get(species) or {}
            current = {"species": species, "moves": []}

            def state() -> str:
                done = "\n\n".join(set_text(s) for s in sets + [current])
                rejected = ("\n\nYour previous team was rejected by Pokémon Showdown:\n" + "\n".join(f"- {p}" for p in problems)
                            if problems else "")
                return (f"{rules_text}\n\nYour six Pokémon: {', '.join(picks)}.\n\n{species} ({'/'.join(o.get('types', []))})"
                        f" can have\nAbilities: {', '.join(o.get('abilities', []))}\nMoves: {', '.join(o.get('moves', []))}"
                        f"\n\nYour sets so far:\n{done}{rejected}")

            answers = await ask(state(), {
                "ability": Question(SET_INSTRUCTIONS.format(species=species, what="ability"),
                                    {a: a for a in o.get("abilities", [])}),
                # Item Clause (Champions): an item a teammate already holds isn't offered, as taken species aren't
                "item": Question(SET_INSTRUCTIONS.format(species=species, what="held item"),
                                 {i: i for i in rules["items"] if not (champions and i in {t.get("item") for t in sets})}),
                # Champions has no Terastallization: no Tera Type to choose
                **({} if champions else {"tera": Question(SET_INSTRUCTIONS.format(species=species, what="Tera Type"),
                                                          {t: t for t in rules["types"]})}),
                "nature": Question(SET_INSTRUCTIONS.format(species=species, what="nature"),
                                   {n["name"]: (f"+{n['plus']}, -{n['minus']}" if n["plus"] else "neutral")
                                    for n in rules["natures"]}),
                "evs": Question(SET_INSTRUCTIONS.format(species=species, what="EV spread"), dict(spreads_for(rules["id"]))),
            }, usage)
            current.update({k: answers[k].choice for k in answers})
            notes += [f"{species} {k}: {answers[k].summary()}" for k in answers]
            for n in range(1, 5):
                left = {m: m for m in o.get("moves", []) if m not in current["moves"]}
                if not left:
                    break
                move = (await ask(state(), {"move": Question(MOVE_INSTRUCTIONS.format(species=species, n=n), left)},
                                  usage))["move"]
                current["moves"].append(move.choice)
                notes.append(f"{species} move {n}: {move.summary()}")
            sets.append(current)
        team = "\n\n".join(set_text(s) for s in sets)
        problems = validate_team(app_cfg, team + "\n")
        record["attempts"].append(_attempt(attempt, usage, "\n".join(notes), {"team": team, "problems": problems}))
        log(f"  sets {attempt}: " + ("legal team" if not problems else f"{len(problems)} problem(s): {problems[0][:100]}"))
        if not problems:
            record["team"] = team
            break
    if record["team"] is None:
        fixed = repair_team(app_cfg, team + "\n", seed=agent.name)
        record.update(team=fixed["team"], repairs=fixed["changes"])
        log(f"  sets repaired with {len(fixed['changes'])} change(s)")
    record["repaired"] = bool(record["repairs"])
    record["legal"] = not record["repaired"]
    return record


def _attempt(attempt: int, usage: Usage, answer: str, extra: Dict[str, Any]) -> Dict[str, Any]:
    """An attempt in draft_team's shape; the answer lists the probabilities behind each choice."""
    return {"attempt": attempt, "answer": answer, "reasoning": "", "thought": None, **extra,
            "tokens": usage.input_tokens, "latency_ms": round(usage.latency_ms), "cost_usd": usage.cost_usd,
            "finish_reason": "decision", "requests": usage.requests}
