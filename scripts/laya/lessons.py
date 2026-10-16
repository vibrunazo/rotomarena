"""Laya's drafting lessons, step 3: the training rows. Each team that beat the pool's average (team_league.py) becomes
the questions Laya answers when it drafts (teams/draft_decisions.py), in the same states, wordings and option chunks,
with the team's own choices as the answers: its six picks one at a time, then each set's ability, item, nature and
spread, then its moves one at a time. A pick or a move has no order in a finished team, so its answer is spread over
the members or moves still to come; each copy of a team takes them in a fresh order. Stronger teams get more copies.
Questions with more options than Laya takes at once are asked in chunks and then a final among the chunks' picks,
as at play time: a chunk holding none of the answers teaches nothing and is left out.

Battle rows keep Laya's battling as it was: states it saw in games (ROTOMARENA_DECISION_LOG), with its own
probabilities as the answers.

Writes data/laya/lessons/{train,eval}.jsonl ({state, questions, gold} rows, laya-train's format); eval holds every
tenth team out. Usage: uv run python scripts/laya/lessons.py [--battle-log FILE]"""
import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from rotomarena.config import AppConfig  # noqa: E402
from rotomarena.llm.decisions import _choice_question, _chunks  # noqa: E402
from rotomarena.teams.draft import format_rules, is_champions, species_options, system_prompt  # noqa: E402
from rotomarena.teams.draft_decisions import (  # noqa: E402
    MOVE_INSTRUCTIONS, PICK_INSTRUCTIONS, SET_INSTRUCTIONS, set_text, spreads_for,
)
from rotomarena.teams.loader import parse_smogon_team  # noqa: E402

DATA = ROOT / "data" / "laya"
STATS = {"HP": "hp", "Atk": "atk", "Def": "def", "SpA": "spa", "SpD": "spd", "Spe": "spe"}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def nearest_spread(evs: dict, spreads: dict) -> str:
    """The listed spread closest to a written one (LLMs write any; Laya picks from the list)."""
    def parse(text):
        return {STATS[s]: int(v) for v, s in re.findall(r"(\d+)\s*(HP|Atk|Def|SpA|SpD|Spe)", text)}
    have = {k: int(v) for k, v in evs.items()}
    return min(spreads, key=lambda s: sum(abs(parse(s).get(k, 0) - have.get(k, 0)) for k in STATS.values()))


class Lessons:
    def __init__(self, app: AppConfig, max_options: int, rng: random.Random):
        self.app, self.max_options, self.rng = app, max_options, rng
        self.rules = format_rules(app)
        self.rules_text = system_prompt(self.rules, with_species=False, version=app.ruleset.draft_prompts or 1)
        self.champions = is_champions(self.rules["id"])
        self.misses = {}

    def ask(self, questions: dict, gold: dict, finals: dict, finals_gold: dict, name: str, instructions: str,
            options: dict, answers: set) -> None:
        """One question, as DecisionClient.choose splits it, with `answers` (option keys) as the right ones."""
        answers = {a for a in answers if a in options}
        if len(options) < 2 or not answers:
            return
        chunks = _chunks(options, self.max_options)
        if len(chunks) == 1:
            questions[name] = _choice_question(instructions, options)
            gold[name] = {"probabilities": {a: 1 / len(answers) for a in answers}}
            return
        picks = []
        for i, chunk in enumerate(chunks):
            inside = sorted(answers & set(chunk))
            if inside:
                questions[f"{name}__part{i + 1}"] = _choice_question(instructions, chunk)
                gold[f"{name}__part{i + 1}"] = {"probabilities": {a: 1 / len(inside) for a in inside}}
            picks.append(self.rng.choice(inside or list(chunk)))  # this chunk's pick, a stand-in where none is right
        final = {k: options[k] for k in picks}
        right = [k for k in picks if k in answers]
        finals[name] = _choice_question(instructions, final)
        finals_gold[name] = {"probabilities": {a: 1 / len(right) for a in right}}

    def rows(self, state: str, build) -> list:
        q, g, fq, fg = {}, {}, {}, {}
        build(q, g, fq, fg)
        return [{"state": state, "questions": qs, "gold": gs} for qs, gs in ((q, g), (fq, fg)) if qs]

    def team_rows(self, text: str) -> list:
        team = parse_smogon_team(text)
        by_norm = {norm(s): s for s in self.rules["species"]}
        members = [m for m in team.members if norm(m.species) in by_norm]
        if len(members) != len(team.members):
            self.misses["species"] = self.misses.get("species", 0) + 1
        order = self.rng.sample(members, len(members))
        out, picks = [], []
        # Stage 1: the picks
        for n in range(1, len(order) + 1):
            taken = {self.rules["base"].get(p, p) for p in picks}
            options = {s: s for s in self.rules["species"] if self.rules["base"].get(s, s) not in taken}
            state = self.rules_text.replace("(you have already picked yours)", "(the options of this question)") + \
                f"\n\nYour team so far: {', '.join(picks) or 'nobody yet'}."
            left = {by_norm[norm(m.species)] for m in order[n - 1:]}
            out += self.rows(state, lambda q, g, fq, fg: self.ask(q, g, fq, fg, "pick", PICK_INSTRUCTIONS.format(n=n),
                                                                   options, left))
            picks.append(by_norm[norm(order[n - 1].species)])
        # Stage 2: the sets, in pick order
        opts = species_options(self.app, picks)
        spreads = spreads_for(self.rules["id"])
        sets = []
        for species, m in zip(picks, order):
            o = opts.get(species) or {}
            current = {"species": species, "moves": []}

            def state() -> str:
                done = "\n\n".join(set_text(s) for s in sets + [current])
                return (f"{self.rules_text}\n\nYour six Pokémon: {', '.join(picks)}.\n\n{species} ({'/'.join(o.get('types', []))})"
                        f" can have\nAbilities: {', '.join(o.get('abilities', []))}\nMoves: {', '.join(o.get('moves', []))}"
                        f"\n\nYour sets so far:\n{done}")

            abilities = {a: a for a in o.get("abilities", [])}
            items = {i: i for i in self.rules["items"] if not (self.champions and i in {t.get("item") for t in sets})}
            natures = {n["name"]: (f"+{n['plus']}, -{n['minus']}" if n["plus"] else "neutral") for n in self.rules["natures"]}
            spread = nearest_spread(m.evs, spreads)
            find = lambda opts_, name: next((k for k in opts_ if norm(k) == norm(name or "")), None)  # noqa: E731
            chosen = {"ability": find(abilities, m.ability), "item": find(items, m.item),
                      "nature": find(natures, m.nature), "evs": spread}

            def set_questions(q, g, fq, fg):
                for key, what, options in (("ability", "ability", abilities), ("item", "held item", items),
                                           ("nature", "nature", natures), ("evs", "EV spread", dict(spreads))):
                    if chosen[key]:
                        self.ask(q, g, fq, fg, key, SET_INSTRUCTIONS.format(species=species, what=what), options,
                                 {chosen[key]})
            out += self.rows(state(), set_questions)
            current.update({k: v for k, v in chosen.items() if v})
            learnset = {mv: mv for mv in o.get("moves", [])}
            moves = [find(learnset, mv) for mv in m.moves]
            moves = self.rng.sample([mv for mv in moves if mv], len([mv for mv in moves if mv]))
            for n in range(1, len(moves) + 1):
                left = {mv: mv for mv in o.get("moves", []) if mv not in current["moves"]}
                out += self.rows(state(), lambda q, g, fq, fg: self.ask(
                    q, g, fq, fg, "move", MOVE_INSTRUCTIONS.format(species=species, n=n), left, set(moves[n - 1:])))
                current["moves"].append(moves[n - 1])
            sets.append(current)
        return out


def battle_rows(path: Path) -> list:
    """Laya's own battle answers as targets (it keeps playing as it did)."""
    rows = []
    for line in path.open(encoding="utf-8"):
        r = json.loads(line)
        gold = {qid: {"probabilities": a["probabilities"]} for qid, a in r["answers"].items()
                if qid in r["questions"] and a.get("probabilities")}
        if gold:
            rows.append({"state": r["state"], "questions": {q: r["questions"][q] for q in gold}, "gold": gold})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battle-log", default=str(DATA / "battle_decisions.jsonl"))
    ap.add_argument("--min-games", type=int, default=20)
    ap.add_argument("--max-copies", type=int, default=3)
    args = ap.parse_args()
    app = AppConfig.load(str(ROOT / "config.yaml"))
    laya = app.agents["laya"]
    rng = random.Random(16)
    builder = Lessons(app, laya.decision_max_options or 255, rng)
    pool = json.loads((DATA / "pool.json").read_text(encoding="utf-8"))
    ratings = json.loads((DATA / "team_ratings.json").read_text(encoding="utf-8"))
    rated = {t: r for t, r in ratings.items()
             if r["games"] >= args.min_games and not any(s.startswith("test:") for s in pool[t]["sources"])}
    values = sorted(r["rating"] for r in rated.values())
    mean = sum(values) / len(values)
    sd = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    split = {"train": [], "eval": []}
    used = {"train": {}, "eval": {}}
    for tid, r in sorted(rated.items()):
        z = (r["rating"] - mean) / sd
        if z <= 0:
            continue
        part = "eval" if int(hashlib.sha1(tid.encode()).hexdigest(), 16) % 10 == 0 else "train"
        copies = 1 if part == "eval" else min(1 + int(z), args.max_copies)
        for _ in range(copies):
            split[part] += builder.team_rows(pool[tid]["team"])
        for s in pool[tid]["sources"]:
            used[part][s] = used[part].get(s, 0) + 1
    battle = battle_rows(Path(args.battle_log)) if Path(args.battle_log).exists() else []
    rng.shuffle(battle)
    held = len(battle) // 10
    split["eval"] += battle[:held]
    split["train"] += battle[held:]
    out = DATA / "lessons"
    out.mkdir(parents=True, exist_ok=True)
    for part, rows in split.items():
        rng.shuffle(rows)
        with (out / f"{part}.jsonl").open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {"teams_rated": len(rated), "rating_mean": round(mean, 1), "rating_sd": round(sd, 1),
               "train_rows": len(split["train"]), "eval_rows": len(split["eval"]), "battle_rows": len(battle),
               "teams_by_source": used, "misses": builder.misses}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))


main()
