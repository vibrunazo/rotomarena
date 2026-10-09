"""Teambuilding: a model drafts its own team from the format's rules, in two stages, refereed by Showdown.

Stage 1: the model gets the rules of the format (clauses, bans and the list of legal Pokémon) and picks six Pokémon.
Stage 2: it gets the abilities and learnable moves of those six, as the format allows them, and builds the full
sets. Both are rules, not strategy, the way a battle gives the legal moves: what a team is meant to do, and which
of the legal options serve it, stays the model's. Listing every Pokémon's moves at once would be about 150k tokens;
after the picks, it is a couple of thousand.

Each stage is checked (stage 1 against the list and Species Clause, stage 2 by Showdown's validator) and illegal
answers go back to the model with the exact problems, for a few attempts each. Every attempt is recorded and
published. A model that never gets there plays anyway, with its answer repaired by replacing only what was
rejected with deliberately middling choices (repair_team.js): a handicap for the mistake, not a punishment and not
an upgrade.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rotomarena.agents.factory import llm_client_for
from rotomarena.config import AgentConfig, AppConfig
from rotomarena.llm.client import recover_answer

PROMPT_VERSION = "draft-3"  # draft-2: retries carried every failed answer and overflowed local context
ATTEMPTS = 5  # per stage
DRAFTS_DIR = Path("data/drafts")
_RULES_SCRIPT = Path(__file__).with_name("format_rules.js")
_OPTIONS_SCRIPT = Path(__file__).with_name("species_options.js")
_REPAIR_SCRIPT = Path(__file__).with_name("repair_team.js")

DRAFT_SYSTEM_PROMPT = """You are building a team for competitive Pokémon battles on Pokémon Showdown, in the format {format}. \
You will play this team yourself, against other players, in a series of rated battles. You build it in two steps: \
first you pick six Pokémon, then you get the abilities and moves each of them can have and build their sets.

RULES OF THE FORMAT
- Exactly 6 Pokémon, all level 100.
{clauses}
- Banned abilities: {abilities}
- Banned moves: {moves}
- Banned items: {items}
- Legal Pokémon (any other Pokémon is banned): {species}"""

PICK_PROMPT = """Step 1: pick your six Pokémon from the legal list.

ANSWER FORMAT
<thought>2-4 sentences: what the team is built to do.</thought>
<pokemon>
One Pokémon per line, six lines, names exactly as in the legal list.
</pokemon>"""

BUILD_PROMPT = """Step 2: build the sets. Here is what each of your six Pokémon can have in this format:

{options}

Each Pokémon needs an item, one of its abilities above, a Tera Type (any type), EVs (at most 252 in one stat and 510 \
in total), a nature, and up to 4 of its moves above. Use exactly these six Pokémon.

ANSWER FORMAT
<thought>2-4 sentences: how the sets serve the team's plan.</thought>
<team>
The six Pokémon in Showdown's export format, each like this:

Species @ Item
Ability: Ability Name
Tera Type: Type
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Move One
- Move Two
- Move Three
- Move Four
</team>"""

RETRY_PICK = """Those picks were rejected:
{problems}

Pick again, in the same format, with all six Pokémon."""

RETRY_BUILD = """Pokémon Showdown rejected your team:
{problems}

Fix the team and answer again in the same format, with the whole team."""


def _showdown_dir(app_cfg: AppConfig) -> Path:
    from rotomarena.server.manager import install_custom_formats  # the validator needs RotomArena's formats too

    path = Path(app_cfg.server.server_dir).resolve()
    install_custom_formats(path)
    return path


def _node(app_cfg: AppConfig, script: Path, *args: str, stdin: str = "") -> Any:
    result = subprocess.run(["node", str(script.resolve()), *args], input=stdin, cwd=_showdown_dir(app_cfg),
                            capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def format_rules(app_cfg: AppConfig, fmt: Optional[str] = None) -> Dict[str, Any]:
    """The format's legal species (with their base species), clauses and bans, read from the local Showdown.
    `fmt` defaults to the format being played (ruleset.format), as in the helpers below."""
    return _node(app_cfg, _RULES_SCRIPT, fmt or app_cfg.ruleset.format)


def species_options(app_cfg: AppConfig, names: List[str], fmt: Optional[str] = None) -> Dict[str, Any]:
    """{species: {name, types, abilities, moves}}: what each Pokémon may have in the format."""
    return _node(app_cfg, _OPTIONS_SCRIPT, fmt or app_cfg.ruleset.format, *names)


def validate_team(app_cfg: AppConfig, team_text: str, fmt: Optional[str] = None) -> List[str]:
    """Showdown's validator messages for a team in export format; empty when the team is legal."""
    result = subprocess.run(["node", "pokemon-showdown", "validate-team", fmt or app_cfg.ruleset.format], input=team_text,
                            cwd=_showdown_dir(app_cfg), capture_output=True, text=True, encoding="utf-8")
    if result.returncode == 0:
        return []
    return [line.strip() for line in (result.stdout + result.stderr).splitlines() if line.strip()] or ["Invalid team."]


def repair_team(app_cfg: AppConfig, team_text: str, seed: str, fmt: Optional[str] = None) -> Dict[str, Any]:
    """{team, changes, problems}: the team made legal by replacing only what the validator rejects."""
    return _node(app_cfg, _REPAIR_SCRIPT, fmt or app_cfg.ruleset.format, seed, stdin=team_text or "")


# Pokémon Champions formats (Showdown's champions mods) build teams differently from Gen 9 OU: level 50, bring 3 of
# the 6, Stat Points instead of EVs, Item Clause, Mega Evolution instead of Terastallization. The Gen 9 OU prompts
# are rewritten for them where they state OU's numbers.
CHAMPIONS_TEXT = [
    ("- Exactly 6 Pokémon, all level 100.",
     "- Exactly 6 Pokémon, all level 50. At team preview you bring 3 of your 6 to each battle and choose which."),
    ("Each Pokémon needs an item, one of its abilities above, a Tera Type (any type), EVs (at most 252 in one stat and 510 "
     "in total), a nature, and up to 4 of its moves above.",
     "Each Pokémon needs an item (no two may hold the same item; a Pokémon holding its own Mega Stone can Mega Evolve once "
     "per battle), one of its abilities above, Stat Points written on the EVs line (at most 32 in one stat and 66 in "
     "total), a nature, and up to 4 of its moves above. There is no Terastallization. Champions has far fewer items "
     "than other games: an item must come from this list (any other is illegal): {items}."),
    ("Tera Type: Type\nEVs: 252 Atk / 4 SpD / 252 Spe", "EVs: 32 Atk / 2 SpD / 32 Spe"),
]


def is_champions(fmt: str) -> bool:
    return fmt.startswith("gen9champions")


def prompts_for(fmt: str) -> Dict[str, str]:
    """The drafting prompts for a format: Gen 9 OU's as written, rewritten for Champions formats."""
    prompts = {"system": DRAFT_SYSTEM_PROMPT, "pick": PICK_PROMPT, "build": BUILD_PROMPT,
               "retry_pick": RETRY_PICK, "retry_build": RETRY_BUILD}
    if is_champions(fmt):
        for old, new in CHAMPIONS_TEXT:
            hits = [k for k, v in prompts.items() if old in v]
            assert len(hits) == 1, f"Champions text no longer matches the prompts: {old[:40]}"
            prompts[hits[0]] = prompts[hits[0]].replace(old, new)
    return prompts


def system_prompt(rules: Dict[str, Any], with_species: bool = True) -> str:
    clause_lines = "\n".join(f"- {c.split(': ', 1)[0]}: {c.split(': ', 1)[1].replace('&eacute;', 'é')}" for c in rules["clauses"])
    banned = rules["banned"]
    return prompts_for(rules["id"])["system"].format(
        format=rules["format"], clauses=clause_lines, abilities=", ".join(banned["abilities"]) or "none",
        moves=", ".join(banned["moves"]) or "none", items=", ".join(banned["items"]) or "none",
        species=", ".join(rules["species"]) if with_species else "(you have already picked yours)",
    )


def options_text(options: Dict[str, Any]) -> str:
    return "\n\n".join(f"{o['name']} ({'/'.join(o['types'])})\nAbilities: {', '.join(o['abilities'])}\n"
                       f"Moves: {', '.join(o['moves'])}" for o in options.values() if o)


def _tag(text: str, name: str) -> Optional[str]:
    m = re.search(rf"<{name}>(.*?)</{name}>", text or "", re.S | re.I)
    return m.group(1).strip() if m else None


def _id(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def check_picks(block: Optional[str], rules: Dict[str, Any], cut_off: bool = False) -> Tuple[List[str], List[str]]:
    """(the legal picks, in order, as named in the list; the problems). Lines may carry list markers or numbers."""
    if block is None:
        return [], ["No <pokemon>...</pokemon> block found" + (" (the answer was cut off at the token budget)." if cut_off else ".")]
    legal = {_id(s): s for s in rules["species"]}
    picks, problems, bases = [], [], {}
    for line in block.splitlines():
        name = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).split("@")[0].strip()
        if not name:
            continue
        species = legal.get(_id(name))
        if not species:
            problems.append(f"{name} is not a legal Pokémon in this format.")
            continue
        base = rules["base"].get(species, species)
        if base in bases:
            problems.append(f"{species} and {bases[base]} are the same species; Species Clause allows one.")
            continue
        bases[base] = species
        picks.append(species)
    if len(picks) + len(problems) != 6:
        problems.append(f"You listed {len(picks) + len(problems)} Pokémon; a team has exactly 6.")
    return picks, problems


def team_species(team_text: str) -> List[str]:
    """The species of a team in export format ("Landorus (Landorus-Therian) (M) @ ..." is Landorus-Therian)."""
    from rotomarena.teams.loader import parse_smogon_team
    try:
        return [m.species for m in parse_smogon_team(team_text).members]
    except Exception:
        return []


def _attempt_record(attempt: int, completion, text: str, reasoning: str, extra: Dict[str, Any]) -> Dict[str, Any]:
    return {"attempt": attempt, "answer": text, "reasoning": reasoning, "thought": _tag(text, "thought"), **extra,
            "tokens": completion.metrics.total_tokens, "latency_ms": round(completion.metrics.latency_ms),
            "cost_usd": completion.metrics.cost_usd, "finish_reason": completion.metrics.finish_reason}


class DraftUnavailable(RuntimeError):
    """The provider failed: no draft is kept, since a repaired team would charge the model for an outage."""


async def draft_team(agent: AgentConfig, app_cfg: AppConfig, attempts: int = ATTEMPTS,
                     log=print, keep_picks: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Asks one model for its six picks, then for their sets, feeding back the problems at each stage. Each request
    carries the stage's prompt and only the latest rejected answer, so retries fit a local model's context window
    (8,192 tokens per game); stage 2 leaves out the legal list, which only stage 1 needs."""
    rules = format_rules(app_cfg)
    client = llm_client_for(agent, app_cfg)
    record: Dict[str, Any] = {
        "config_id": agent.name, "model": client.default_model, "provider": client.provider_name,
        "model_key": agent.canonical_model_key(), "quantization": agent.quantization,
        "format": rules["id"], "prompt_version": PROMPT_VERSION, "ruleset_version": app_cfg.ruleset.version,
        "drafted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "picks": {"attempts": [], "legal": False, "species": [], "repairs": []},
        "attempts": [], "legal": False, "team": None, "thought": None, "repaired": False, "repairs": [],
    }

    async def ask(messages: List[Dict[str, str]], attempt: int, marker: str):
        """(completion, answer, reasoning); raises DraftUnavailable when the provider fails."""
        try:
            completion = await client.generate_completion(
                messages, max_tokens=app_cfg.ruleset.draft_max_output_tokens or app_cfg.ruleset.max_output_tokens,
                reasoning=agent.thinking(app_cfg.ruleset)[0],
                thinking_budget=agent.thinking(app_cfg.ruleset)[1])
        except Exception as e:
            raise DraftUnavailable(f"provider error at attempt {attempt}: {str(e)[:300]}") from e
        return (completion, *recover_answer(completion.text, completion.reasoning, marker))

    def retry(answer: str, template: str, problems: List[str]) -> List[Dict[str, str]]:
        return [{"role": "assistant", "content": answer},
                {"role": "user", "content": template.format(problems="\n".join(f"- {p}" for p in problems))}]

    # Stage 1: six Pokémon from the legal list. `keep_picks` (an earlier draft's picks stage) skips it, for redoing
    # only the sets when the harness, not the model, spoiled them
    prompts = prompts_for(rules["id"])
    base = [{"role": "system", "content": system_prompt(rules)}, {"role": "user", "content": prompts["pick"]}]
    picks: List[str] = []
    plan: Optional[str] = None
    last: List[Dict[str, str]] = []
    if keep_picks:
        record["picks"] = json.loads(json.dumps(keep_picks))
        picks = list(keep_picks["species"])
        plan = next((a.get("thought") for a in reversed(keep_picks["attempts"]) if a.get("thought")), None)
        log(f"  picks kept from the earlier draft: {', '.join(picks)}")
    for attempt in range(1, attempts + 1 if not keep_picks else 1):
        completion, answer, reasoning = await ask(base + last, attempt, "<pokemon>")
        picks, problems = check_picks(_tag(answer, "pokemon"), rules, completion.metrics.finish_reason == "length")
        record["picks"]["attempts"].append(_attempt_record(attempt, completion, answer, reasoning,
                                                           {"pokemon": picks, "problems": problems}))
        log(f"  picks {attempt}: " + (", ".join(picks) if not problems else f"{len(problems)} problem(s): {problems[0][:100]}"))
        plan = _tag(answer, "thought") or plan
        if not problems:
            record["picks"]["legal"] = True
            break
        last = retry(answer, prompts["retry_pick"], problems)
    if not record["picks"]["legal"]:  # keep the legal picks, fill the rest with middling Pokémon
        stub = "\n\n".join(f"{p}\n- Protect" for p in picks) + "\n"
        filled = repair_team(app_cfg, stub, seed=agent.name)
        picks = team_species(filled["team"])
        record["picks"]["repairs"] = [c for c in filled["changes"] if "replaced by" in c or "filled with" in c]
        log(f"  picks repaired: {', '.join(picks)}")
    record["picks"]["species"] = picks

    # Stage 2: the sets, given each pick's legal abilities and moves, in a fresh conversation without the legal list
    intro = f"Step 1 is done. Your six Pokémon: {', '.join(picks)}." + (f" Your plan: {plan}" if plan else "")
    base = [{"role": "system", "content": system_prompt(rules, with_species=False)},
            {"role": "user", "content": intro + "\n\n" + prompts["build"].format(
                options=options_text(species_options(app_cfg, picks)), items=", ".join(rules.get("items", [])))}]
    last = []
    for attempt in range(1, attempts + 1):
        completion, answer, reasoning = await ask(base + last, attempt, "<team>")
        team = _tag(answer, "team")
        if team is None:
            problems = ["No <team>...</team> block found" + (" (the answer was cut off at the token budget)."
                                                             if completion.metrics.finish_reason == "length" else ".")]
        else:
            built = team_species(team)
            strays = [s for s in built if _id(s) not in {_id(p) for p in picks}]
            # Showdown accepts a team of fewer than six, so the six have to be checked here: Ling once closed
            # </team> after its first set and played with a lone Inteleon
            missing = [p for p in picks if _id(p) not in {_id(s) for s in built}]
            problems = ([f"{', '.join(strays)} {'is' if len(strays) == 1 else 'are'} not among the six Pokémon you "
                         f"picked ({', '.join(picks)})."] if strays else []) + \
                ([f"Your <team> block has {len(built)} Pokémon; it needs all six you picked, inside one <team>...</team> "
                  f"block. Missing: {', '.join(missing)}."] if missing else []) + validate_team(app_cfg, team + "\n")
        record["attempts"].append(_attempt_record(attempt, completion, answer, reasoning, {"team": team, "problems": problems}))
        log(f"  sets {attempt}: " + ("legal team" if not problems else f"{len(problems)} problem(s): {problems[0][:100]}"))
        if not problems:
            record.update(team=team, thought=_tag(answer, "thought"))
            break
        last = retry(answer, prompts["retry_build"], problems)
    if record["team"] is None:
        last = next((a.get("team") for a in reversed(record["attempts"]) if a.get("team")), "")
        fixed = repair_team(app_cfg, (last or "\n\n".join(f"{p}\n- Protect" for p in picks)) + "\n", seed=agent.name)
        record.update(team=fixed["team"], repairs=fixed["changes"],
                      thought=next((a.get("thought") for a in reversed(record["attempts"]) if a.get("thought")), None))
        log(f"  sets repaired with {len(fixed['changes'])} change(s)" + (f"; still: {fixed['problems']}" if fixed["problems"] else ""))
    record["repaired"] = not record["picks"]["legal"] or bool(record["repairs"])
    record["legal"] = not record["repaired"]
    return record


def playable_team(record: Dict[str, Any]) -> Optional[str]:
    """The team a model plays: its own legal team, or its repaired one."""
    return record.get("team")


def draft_cost(record: Dict[str, Any]) -> float:
    """What drafting cost this model under this version: every attempt of this draft, plus the drafts it replaced."""
    attempts = record.get("picks", {}).get("attempts", []) + record.get("attempts", [])
    return sum(a.get("cost_usd") or 0 for a in attempts) + (record.get("earlier_drafts_cost_usd") or 0)


def save_draft(record: Dict[str, Any], drafts_dir: Path = DRAFTS_DIR) -> Path:
    """Drafts are kept per ruleset version: the version's rules (thinking budget included) shaped them. A redraft
    replaces the team but keeps a count and the cost of the drafts before it."""
    path = drafts_dir / record["format"] / record["ruleset_version"] / f"{record['config_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        earlier = json.loads(path.read_text(encoding="utf-8"))
        record["earlier_drafts"] = (earlier.get("earlier_drafts") or 0) + 1
        record["earlier_drafts_cost_usd"] = round(draft_cost(earlier), 6)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_drafts(drafts_dir: Path = DRAFTS_DIR, fmt: str = "gen9ou", version: str = "") -> Dict[str, Dict[str, Any]]:
    """{config id: draft record} for every model that drafted in this format under this ruleset version (older
    folders are named by draft version: draft-1 for s2, draft-2 and draft-3 from before drafts followed versions)."""
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((drafts_dir / fmt / version).glob("*.json"))}
