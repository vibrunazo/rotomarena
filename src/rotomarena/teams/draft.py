"""Teambuilding: a model drafts its own team from the format's rules, refereed by Showdown's validator.

The model gets the rules of the format (its clauses, its bans and the list of legal Pokémon), the way a player in
a battle gets the list of legal moves: rules, not strategy. Showdown's validator checks the team; an illegal team
goes back to the model with the validator's own messages, as Showdown's teambuilder shows them to a human, for a
few attempts. Every attempt is recorded and published.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from rotomarena.agents.factory import llm_client_for
from rotomarena.config import AgentConfig, AppConfig

FORMAT = "gen9ou"
PROMPT_VERSION = "draft-1"
DRAFTS_DIR = Path("data/drafts")
_RULES_SCRIPT = Path(__file__).with_name("format_rules.js")

DRAFT_SYSTEM_PROMPT = """You are building a team for competitive Pokémon battles on Pokémon Showdown, in the format {format}. \
You will play this team yourself, against other players, in a series of rated battles.

RULES OF THE FORMAT
- Exactly 6 Pokémon, all level 100.
{clauses}
- Banned abilities: {abilities}
- Banned moves: {moves}
- Banned items: {items}
- Legal Pokémon (any other Pokémon is banned): {species}

Each Pokémon needs an item, an ability it can have, a Tera Type, EVs (at most 252 in one stat and 510 in total), a nature, \
and up to 4 moves it can learn.

ANSWER FORMAT
<thought>2-4 sentences: what the team is built to do.</thought>
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

RETRY_PROMPT = """Pokémon Showdown rejected your team:
{problems}

Fix the team and answer again in the same format, with the whole team."""


def _showdown_dir(app_cfg: AppConfig) -> Path:
    return Path(app_cfg.server.server_dir).resolve()


def format_rules(app_cfg: AppConfig, fmt: str = FORMAT) -> Dict[str, Any]:
    """The format's legal species, clauses and bans, read from the local Showdown install."""
    result = subprocess.run(["node", str(_RULES_SCRIPT.resolve()), fmt], cwd=_showdown_dir(app_cfg),
                            capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def validate_team(app_cfg: AppConfig, team_text: str, fmt: str = FORMAT) -> List[str]:
    """Showdown's validator messages for a team in export format; empty when the team is legal."""
    result = subprocess.run(["node", "pokemon-showdown", "validate-team", fmt], input=team_text,
                            cwd=_showdown_dir(app_cfg), capture_output=True, text=True, encoding="utf-8")
    if result.returncode == 0:
        return []
    return [line.strip() for line in (result.stdout + result.stderr).splitlines() if line.strip()] or ["Invalid team."]


def system_prompt(rules: Dict[str, Any]) -> str:
    clause_lines = "\n".join(f"- {c.split(': ', 1)[0]}: {c.split(': ', 1)[1].replace('&eacute;', 'é')}" for c in rules["clauses"])
    banned = rules["banned"]
    return DRAFT_SYSTEM_PROMPT.format(
        format=rules["format"], clauses=clause_lines, abilities=", ".join(banned["abilities"]) or "none",
        moves=", ".join(banned["moves"]) or "none", items=", ".join(banned["items"]) or "none",
        species=", ".join(rules["species"]),
    )


def _tag(text: str, name: str) -> Optional[str]:
    m = re.search(rf"<{name}>(.*?)</{name}>", text or "", re.S | re.I)
    return m.group(1).strip() if m else None


async def draft_team(agent: AgentConfig, app_cfg: AppConfig, attempts: int = 3,
                     log=print) -> Dict[str, Any]:
    """Asks one model for a team, feeding back Showdown's validator messages, and returns the full record."""
    rules = format_rules(app_cfg)
    client = llm_client_for(agent, app_cfg)
    messages = [{"role": "system", "content": system_prompt(rules)},
                {"role": "user", "content": "Build your team."}]
    record: Dict[str, Any] = {
        "config_id": agent.name, "model": client.default_model, "provider": client.provider_name,
        "model_key": agent.canonical_model_key(), "quantization": agent.quantization,
        "format": rules["id"], "prompt_version": PROMPT_VERSION,
        "drafted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "attempts": [], "legal": False, "team": None, "thought": None,
    }
    for attempt in range(1, attempts + 1):
        try:
            completion = await client.generate_completion(
                messages, max_tokens=app_cfg.ruleset.max_output_tokens, reasoning=app_cfg.ruleset.reasoning)
        except Exception as e:  # a provider failure ends the draft; the record says why
            record["attempts"].append({"attempt": attempt, "error": str(e)[:500]})
            log(f"  attempt {attempt}: provider error: {str(e)[:120]}")
            break
        answer = completion.text
        team = _tag(answer, "team")
        problems = validate_team(app_cfg, team + "\n") if team else [
            "No <team>...</team> block found" + (" (the answer was cut off at the token budget)."
                                                  if completion.metrics.finish_reason == "length" else ".")]
        record["attempts"].append({
            "attempt": attempt, "answer": answer, "reasoning": completion.reasoning, "thought": _tag(answer, "thought"),
            "team": team, "problems": problems, "tokens": completion.metrics.total_tokens,
            "latency_ms": round(completion.metrics.latency_ms), "cost_usd": completion.metrics.cost_usd,
            "finish_reason": completion.metrics.finish_reason,
        })
        log(f"  attempt {attempt}: " + ("legal team" if not problems else f"{len(problems)} problem(s): {problems[0][:100]}"))
        if not problems:
            record.update(legal=True, team=team, thought=_tag(answer, "thought"))
            break
        messages += [{"role": "assistant", "content": answer},
                     {"role": "user", "content": RETRY_PROMPT.format(problems="\n".join(f"- {p}" for p in problems))}]
    return record


def save_draft(record: Dict[str, Any], drafts_dir: Path = DRAFTS_DIR) -> Path:
    path = drafts_dir / record["format"] / f"{record['config_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_drafts(drafts_dir: Path = DRAFTS_DIR, fmt: str = FORMAT) -> Dict[str, Dict[str, Any]]:
    """{config id: draft record} for every model that has drafted in this format."""
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((drafts_dir / fmt).glob("*.json"))}
