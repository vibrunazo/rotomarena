"""Benchmark versions: the exact rules a set of games was played under.

A benchmark (say "Gen 9 OU, own teams") has versions; each version id (ruleset.version) names one exact set of rules:
the ruleset settings, the battle format, a fingerprint of the battle prompt and, for drafted teams, of the draft
prompt. The first run of a version stores its rules in data/rulesets/<version>.json; later runs refuse to start if
the configuration no longer matches (change a rule, and you start a new version), and the export only rates games
whose recorded rules match their version's.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from rotomarena.config import AppConfig
from rotomarena.llm.prompts import SYSTEM_PROMPT_DIRECT_COT, USER_PROMPT_DIRECT_COT_TEMPLATE

RULESETS_DIR = Path("data/rulesets")


class RulesChanged(RuntimeError):
    """The configuration no longer matches the stored rules of this version."""


def _sha(*texts: str) -> str:
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()[:12]


def current_rules(app_cfg: AppConfig) -> Dict[str, Any]:
    """Everything that decides how a game of this version is played, as recorded in every match."""
    # A rule left unset isn't recorded, so a new optional setting doesn't change the rules of earlier versions
    rules = {**{k: v for k, v in app_cfg.ruleset.model_dump().items() if v is not None},
             "battle_prompt": _sha(SYSTEM_PROMPT_DIRECT_COT, USER_PROMPT_DIRECT_COT_TEMPLATE)}
    # Models whose provider ignores the thinking budget, and the effort level each gets instead
    rules["thinking_exceptions"] = {k: a.thinking_effort for k, a in sorted(app_cfg.agents.items()) if a.thinking_effort}
    from rotomarena.agents import decision  # imported here, like the drafts below
    rules["decision_prompt"] = _sha(decision.TURN_INSTRUCTIONS, decision.LEAD_INSTRUCTIONS)
    if app_cfg.ruleset.team_mode == "draft":
        from rotomarena.teams import draft, draft_decisions  # imported here: drafting imports the agent factory
        rules["draft_prompt"] = _sha(draft.DRAFT_SYSTEM_PROMPT, draft.PICK_PROMPT, draft.BUILD_PROMPT, draft.RETRY_PICK,
                                     draft.RETRY_BUILD, draft.PROMPT_VERSION, str(draft.ATTEMPTS))
        rules["control_team"] = "opponent's"  # a control bot (Chimps at the Zoo) borrows its opponent's own team
        rules["decision_draft_prompt"] = _sha(
            draft_decisions.PICK_INSTRUCTIONS, draft_decisions.SET_INSTRUCTIONS, draft_decisions.MOVE_INSTRUCTIONS,
            json.dumps(draft_decisions.EV_SPREADS), draft_decisions.DECISION_DRAFT_VERSION)
    return rules


def stored_rules(version: str, rulesets_dir: Path = RULESETS_DIR) -> Optional[Dict[str, Any]]:
    path = rulesets_dir / f"{version}.json"
    return json.loads(path.read_text(encoding="utf-8"))["rules"] if path.exists() else None


def register(app_cfg: AppConfig, rulesets_dir: Path = RULESETS_DIR) -> Dict[str, Any]:
    """Stores this version's rules on its first run; raises RulesChanged if they no longer match."""
    rules = current_rules(app_cfg)
    version = app_cfg.ruleset.version
    stored = stored_rules(version, rulesets_dir)
    if stored is None:
        path = rulesets_dir / f"{version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": version, "registered_at": datetime.datetime.now(datetime.timezone.utc)
                                    .isoformat(timespec="seconds"), "rules": rules}, indent=2) + "\n", encoding="utf-8")
        return rules
    changed = sorted(k for k in set(stored) | set(rules) if stored.get(k) != rules.get(k))
    if changed:
        raise RulesChanged(f"the rules of version {version!r} changed ({', '.join(changed)}): give the new rules a new "
                           f"ruleset.version, so its games are not rated together with the old ones")
    return rules


def same_rules(recorded: Dict[str, Any], stored: Dict[str, Any]) -> bool:
    """A game matches its version if every rule it recorded agrees (games from before a rule was recorded, such as
    the prompt fingerprints, are judged on what they did record)."""
    return all(stored.get(k) == v for k, v in recorded.items() if k in stored)
