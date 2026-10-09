"""Exports every benchmark's games and ratings (and the retracted v0 archive) as JSON for the Astro site."""

from __future__ import annotations

import datetime
import json
import re
import statistics
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from rotomarena.config import MODEL_TYPES, AppConfig, derived_model_key
from rotomarena.ladder import LadderState, versions_state
from rotomarena.rulesets import stored_rules
from rotomarena.rating import Rating
from rotomarena.results import autopilot_rate, load_matches, player_turns, void_reason
from rotomarena.telemetry.breadcrumbs import MatchPlayer, MatchTelemetry, TurnBreadcrumb
from rotomarena.teams.draft import _id, load_drafts, team_species
from rotomarena.teams.loader import parse_smogon_team
from rotomarena.telemetry.replay_saver import flatten_logs

RETRACTED_SEASON = "v0"
GAME = "pokemon"  # this harness's game; a multi-game site keys its data folders and rankings by it
_SECRETS = re.compile(r"sk-[A-Za-z0-9_\-*]{6,}|AIza[0-9A-Za-z_\-]{10,}|Bearer\s+\S+")
_CHOICE = re.compile(r"/choose (move|switch) (\S+)( terastallize)?")
_PROPOSED = re.compile(r"'((?:MOVE|SWITCH): [^']*)'")


def scrub(value: Any) -> Any:
    """Removes anything shaped like an API key from every string in a JSON-able structure."""
    if isinstance(value, str):
        return _SECRETS.sub("[redacted]", value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    return value


def parse_choice(chosen_action: str) -> Dict[str, Any]:
    """'/choose move terablast terastallize' -> {'kind': 'move', 'target': 'terablast', 'tera': True}."""
    lead = re.search(r"/team \d+ lead=(\S+)", chosen_action or "")
    if lead:
        return {"kind": "lead", "target": lead.group(1), "tera": False}
    m = _CHOICE.search(chosen_action or "")
    if not m:
        return {"kind": "default", "target": "", "tera": False}
    return {"kind": m.group(1), "target": m.group(2), "tera": bool(m.group(3))}


def _thought(crumb: TurnBreadcrumb) -> str:
    return crumb.reasoning if crumb.decision_source == "model" and crumb.agent_type in MODEL_TYPES else ""


def _turn_entries(match: MatchTelemetry) -> List[Dict[str, Any]]:
    roles = {p.username: p.role for p in match.players}
    entries = []
    for crumb in match.breadcrumbs:
        metrics = crumb.llm_metrics or {}
        entries.append({
            "turn": crumb.turn,
            "role": roles.get(crumb.agent_name, "?"),
            "action": parse_choice(crumb.chosen_action),
            "source": crumb.decision_source,
            "thought": _thought(crumb),
            "hidden_reasoning": crumb.hidden_reasoning,
            "note": crumb.reasoning if crumb.decision_source != "model" else "",
            "tokens": metrics.get("total_tokens", 0),
            "latency_ms": round(metrics.get("latency_ms", 0.0)),
            "cost_usd": metrics.get("cost_usd", 0.0),
        })
    return entries


def _user_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def public_log(lines: List[str]) -> List[str]:
    """The battle without its room: drops chat and HTML notices, and joins, leaves and renames by anyone who is not
    a player (spectators are real people with real usernames)."""
    players = {_user_id(line.split("|")[3]) for line in lines if line.startswith("|player|") and line.count("|") >= 3}
    kept = []
    for line in lines:
        parts = line.split("|")
        kind = parts[1] if len(parts) > 1 else ""
        if kind in ("c", "chat", "c:", "html", "uhtml", "raw"):
            continue
        if kind in ("j", "J", "join", "l", "L", "leave", "n", "N", "name") and _user_id(parts[2] if len(parts) > 2 else "") not in players:
            continue
        kept.append(line)
    return kept


def _raw_log(runs_dir: Path, match_id: str) -> List[str]:
    path = runs_dir / match_id / "battle_log.json"
    if not path.exists():
        return []
    return public_log(flatten_logs(json.loads(path.read_text(encoding="utf-8")).get("raw_logs", [])))


def model_key(player: MatchPlayer, app_cfg: AppConfig) -> Optional[str]:
    """The weights' cross-game id: from the registry, or derived for players that left it (pilot models)."""
    registry = app_cfg.agents.get(player.config_id)
    if registry:
        return registry.canonical_model_key()
    return derived_model_key(player.agent_type, player.provider, player.model)


def match_record(match: MatchTelemetry, runs_dir: Path, app_cfg: AppConfig) -> Dict[str, Any]:
    winner_role = next((p.role for p in match.players if p.username == match.winner), None)
    max_autopilot = app_cfg.ladder.max_autopilot
    return {
        "id": match.match_id,
        "game": GAME,
        "format": match.format,
        "version": match.ruleset.get("version"),
        "date": match.match_id.split("_")[1] if match.match_id.count("_") > 1 else "",
        "players": [
            {**p.model_dump(), "model_key": model_key(p, app_cfg), "autopilot_rate": round(autopilot_rate(match, p.role), 3)}
            for p in match.players
        ],
        "winner_role": winner_role,
        "turns": match.total_turns,
        "duration_seconds": match.duration_seconds,
        "void_reason": void_reason(match, max_autopilot),
        "log": _raw_log(runs_dir, match.match_id),
        "decisions": _turn_entries(match),
    }


def _median(values: Iterable[float]) -> Optional[float]:
    values = list(values)
    return statistics.median(values) if values else None


def model_stats(config_id: str, matches: List[MatchTelemetry]) -> Dict[str, Any]:
    """Behaviour across every match a model played in the exported versions, rated or not."""
    turns: List[TurnBreadcrumb] = []
    tera_turns, played = [], 0
    for m in matches:
        for p in m.players:
            if p.config_id != config_id:
                continue
            played += 1
            mine = player_turns(m, p.role)
            turns.extend(mine)
            tera = next((b.turn for b in mine if parse_choice(b.chosen_action)["tera"]), None)
            if tera is not None:
                tera_turns.append(tera)

    sources = Counter(b.decision_source for b in turns)
    choices = [parse_choice(b.chosen_action) for b in turns if b.decision_source == "model"]
    moves = Counter(c["target"] for c in choices if c["kind"] == "move")
    thoughts = [t for t in (_thought(b) for b in turns) if t.strip()]
    metrics = [b.llm_metrics for b in turns if b.llm_metrics]
    hallucinations = Counter(
        m.group(1) for b in turns if b.decision_source == "invalid" and (m := _PROPOSED.search(b.reasoning))
    )
    n = len(turns) or 1
    return {
        "matches_played": played,
        "turns": len(turns),
        "autopilot_rate": round((len(turns) - sources.get("model", 0)) / n, 3),
        "decision_sources": dict(sources),
        "hallucinated_move_rate": round(sources.get("invalid", 0) / n, 3),
        "tokens_per_turn": round(statistics.mean(x.get("completion_tokens", 0) for x in metrics)) if metrics else None,
        "cost_usd": round(sum(x.get("cost_usd", 0.0) for x in metrics), 4),
        "cost_per_game_usd": round(sum(x.get("cost_usd", 0.0) for x in metrics) / played, 4) if played else 0.0,
        "switch_rate": round(sum(1 for c in choices if c["kind"] == "switch") / (len(choices) or 1), 3),
        "signature_move": moves.most_common(1)[0][0] if moves else None,
        "most_used_pokemon": Counter(b.active_pokemon for b in turns).most_common(1)[0][0] if turns else None,
        "median_tera_turn": _median(tera_turns),
        "longest_thought": max(thoughts, key=lambda t: len(t.split()), default=None),
        "shortest_thought": min(thoughts, key=lambda t: len(t.split()), default=None),
        "hallucinations": [{"action": a, "count": c} for a, c in hallucinations.most_common(10)],
    }


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) < 3 or statistics.pstdev(xs) == 0 or statistics.pstdev(ys) == 0:
        return None
    return round(statistics.correlation(xs, ys), 3)


def findings(models: List[Dict[str, Any]], all_matches: List[MatchTelemetry]) -> List[Dict[str, Any]]:
    """Superlatives with real numbers. The site's copy decides how to phrase them; `show` hides empty ones."""
    llms = [m for m in models if m["type"] in MODEL_TYPES]
    ranked = sorted((m for m in models if m["rating"] is not None and m["role"] != "anchor"),
                    key=lambda m: m["rating"], reverse=True)
    out: List[Dict[str, Any]] = []

    if len(ranked) >= 2:
        top, bottom = ranked[0], ranked[-1]
        out.append({"id": "top-model", "show": True, "config_id": top["config_id"], "rating": top["rating"],
                    "ci": [top["ci_low"], top["ci_high"]], "bottom": bottom["config_id"],
                    "overlaps_bottom": top["ci_low"] <= bottom["ci_high"]})
    else:
        out.append({"id": "top-model", "show": False})

    with_tokens = [m for m in llms if m["tokens_per_turn"] and m["games"] > 0]
    r = _pearson([m["tokens_per_turn"] for m in with_tokens], [m["win_rate"] for m in with_tokens])
    out.append({"id": "tokens-vs-wins", "show": r is not None, "r": r, "models": len(with_tokens)})

    if len(with_tokens) >= 2:
        top_tokens = max(with_tokens, key=lambda m: m["tokens_per_turn"])
        median = statistics.median(m["tokens_per_turn"] for m in with_tokens)
        out.append({"id": "most-tokens", "show": True, "config_id": top_tokens["config_id"],
                    "tokens_per_turn": top_tokens["tokens_per_turn"],
                    "times_median": round(top_tokens["tokens_per_turn"] / median, 1)})
    else:
        out.append({"id": "most-tokens", "show": False})

    zero_token_wins = [
        {"config_id": p.config_id, "match_id": m.match_id, "version": m.ruleset.get("version")}
        for m in all_matches for p in m.players
        if p.username == m.winner and p.agent_type in MODEL_TYPES and autopilot_rate(m, p.role) == 1.0
    ]
    out.append({"id": "zero-token-wins", "show": bool(zero_token_wins), "wins": zero_token_wins})

    moves = Counter()
    for m in llms:
        if m["signature_move"]:
            moves[m["signature_move"]] += 1
    out.append({"id": "most-common-signature-move", "show": bool(moves),
                "move": moves.most_common(1)[0][0] if moves else None,
                "models": moves.most_common(1)[0][1] if moves else 0})

    hallucinators = [m for m in llms if m["hallucinations"]]
    if hallucinators:
        worst = max(hallucinators, key=lambda m: m["hallucinated_move_rate"])
        out.append({"id": "most-hallucinations", "show": True, "config_id": worst["config_id"],
                    "rate": worst["hallucinated_move_rate"], "example": worst["hallucinations"][0]["action"]})
    else:
        out.append({"id": "most-hallucinations", "show": False})
    return out


def _sprite_ids(app_cfg: AppConfig, names: List[str]) -> Dict[str, Optional[str]]:
    """Showdown sprite ids for species names, from the local Showdown install."""
    if not names:
        return {}
    script = Path(__file__).resolve().parent.parent / "teams" / "sprite_ids.js"
    result = subprocess.run(["node", str(script), *names], cwd=Path(app_cfg.server.server_dir).resolve(),
                            capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


REFERENCE_TEAMS = Path("data/teams/smogon/index.json")


def smogon_usage(index: Path = REFERENCE_TEAMS) -> Tuple[Dict[str, int], int]:
    """({species id: how many of Smogon's sample teams use it}, how many sample teams there are): a rough meta yardstick."""
    if not index.exists():
        return {}, 0
    teams = json.loads(index.read_text(encoding="utf-8"))["teams"]
    usage: Dict[str, int] = {}
    for t in teams:
        path = index.parents[1] / f"{t['name']}.txt"
        for species in {_id(s) for s in team_species(path.read_text(encoding="utf-8"))} if path.exists() else ():
            usage[species] = usage.get(species, 0) + 1
    return usage, len(teams)


def draft_rows(app_cfg: AppConfig, drafts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every model's self-built team for the site: the final team, parsed, and each attempt with the validator's
    verdict. Raw answers and reasoning traces stay in data/drafts."""
    parsed = {cid: parse_smogon_team(d["team"]).members if d.get("team") else [] for cid, d in drafts.items()}
    sprites = _sprite_ids(app_cfg, sorted({m.species for members in parsed.values() for m in members}))
    usage, sample_teams = smogon_usage()
    rows = []
    for cid, d in sorted(drafts.items()):
        registry = app_cfg.agents.get(cid)
        counts = [usage.get(_id(m.species), 0) for m in parsed[cid]]
        rows.append({
            "config_id": cid,
            "display_name": (registry.display_name if registry and registry.display_name else cid),
            "model": d.get("model"), "model_key": d.get("model_key"), "format": d["format"],
            "prompt_version": d["prompt_version"], "drafted_at": d["drafted_at"],
            "legal": d["legal"], "repaired": d.get("repaired", False), "repairs": d.get("repairs", []),
            "thought": d.get("thought"), "team_text": d.get("team"),
            "members": [{"species": m.species, "sprite": sprites.get(m.species), "item": m.item, "ability": m.ability,
                         "tera_type": m.tera_type, "nature": m.nature,
                         "evs": {k: v for k, v in m.evs.items() if v}, "moves": m.moves,
                         "smogon_teams": n} for m, n in zip(parsed[cid], counts)],
            # The meta score: how many of its Pokémon appear in at least one of Smogon's sample teams
            "meta": {"used": sum(1 for n in counts if n), "of": len(counts), "slots": sum(counts),
                     "sample_teams": sample_teams},
            "picks": {"legal": d.get("picks", {}).get("legal", True), "species": d.get("picks", {}).get("species", []),
                      "repairs": d.get("picks", {}).get("repairs", []),
                      "attempts": [{"attempt": a["attempt"], "problems": a.get("problems") or [], "error": a.get("error"),
                                    "pokemon": a.get("pokemon", []), "thought": a.get("thought"), "tokens": a.get("tokens", 0)}
                                   for a in d.get("picks", {}).get("attempts", [])]},
            "attempts": [{"attempt": a["attempt"], "problems": a.get("problems") or [], "error": a.get("error"),
                          "thought": a.get("thought"), "team_text": a.get("team"), "tokens": a.get("tokens", 0),
                          "cost_usd": a.get("cost_usd", 0.0), "finish_reason": a.get("finish_reason")}
                         for a in d["attempts"]],
        })
    return rows


def _board_rating(state: LadderState, config_id: str, app_cfg: AppConfig) -> Optional[Dict[str, Any]]:
    """One model's standing on one leaderboard, or None if it has no rated game there."""
    rating: Optional[Rating] = state.ratings.get(config_id)
    if not rating or not rating.games:
        return None
    return {
        "rating": rating.rating, "ci_low": rating.ci_low, "ci_high": rating.ci_high, "games": rating.games,
        "wins": rating.wins, "losses": rating.losses, "draws": rating.draws,
        "win_rate": round((rating.wins + 0.5 * rating.draws) / rating.games, 3),
        "provisional": rating.games < app_cfg.ladder.provisional_games,
    }


def _head_to_head(state: LadderState) -> List[Dict[str, Any]]:
    rows: Dict[frozenset, Dict[str, Any]] = {}
    for o in state.outcomes:
        a, b = sorted((o.p1, o.p2))
        row = rows.setdefault(frozenset((a, b)), {"a": a, "b": b, "games": 0, "a_wins": 0, "b_wins": 0, "draws": 0})
        row["games"] += 1
        score_a = o.score_p1 if o.p1 == a else 1.0 - o.score_p1
        if score_a == 1.0:
            row["a_wins"] += 1
        elif score_a == 0.0:
            row["b_wins"] += 1
        else:
            row["draws"] += 1
    return sorted(rows.values(), key=lambda r: (r["a"], r["b"]))


def _model_rows(state: LadderState, app_cfg: AppConfig) -> List[Dict[str, Any]]:
    identities = {}
    for m in state.matches:
        for p in m.players:
            identities[p.config_id] = p
    rows = []
    for config_id, identity in sorted(identities.items()):
        rating: Rating = state.ratings.get(config_id) or Rating(config_id, None, None, None, 0, 0, 0, 0)
        registry = app_cfg.agents.get(config_id)
        games = rating.games
        rows.append({
            "config_id": config_id,
            "display_name": identity.display_name,
            "type": identity.agent_type,
            "role": registry.role if registry else "contestant",
            "provider": identity.provider,
            "model": identity.model,
            "model_key": model_key(identity, app_cfg),
            "quantization": identity.quantization,
            "rating": rating.rating,
            "ci_low": rating.ci_low,
            "ci_high": rating.ci_high,
            "provisional": games < app_cfg.ladder.provisional_games,
            "games": games,
            "wins": rating.wins,
            "losses": rating.losses,
            "draws": rating.draws,
            "win_rate": round((rating.wins + 0.5 * rating.draws) / games, 3) if games else 0.0,
            **model_stats(config_id, state.matches),
        })
    return rows


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scrub(data), indent=2, ensure_ascii=False), encoding="utf-8")


def export_site(app_cfg: AppConfig, out_dir: str | Path) -> Dict[str, int]:
    """Writes meta, models, head-to-head, findings and per-match files. Returns counts for the CLI."""
    out = Path(out_dir)
    runs_dir = Path(app_cfg.telemetry.output_dir)
    boards = app_cfg.boards()
    states = {b.id: versions_state(app_cfg, b.versions) for b in boards}
    # every version any board shows, rated together: model stats, match pages and findings come from this
    all_versions = list(dict.fromkeys(s for b in boards for s in b.versions))
    state = states[boards[0].id] if set(boards[0].versions) == set(all_versions) else versions_state(app_cfg, all_versions)
    retracted = load_matches(runs_dir, RETRACTED_SEASON)
    models = _model_rows(state, app_cfg)
    for row in models:  # each model's standing on every board; top-level rating fields are the main board's
        row["boards"] = {b.id: r for b in boards if (r := _board_rating(states[b.id], row["config_id"], app_cfg))}
        main = row["boards"].get(boards[0].id)
        row.update({k: (main or {}).get(k) for k in ("rating", "ci_low", "ci_high")})

    for sub in ("matches", "retracted"):
        for stale in (out / sub).glob("*.json"):
            stale.unlink()

    for m in state.matches:
        _write_json(out / "matches" / f"{m.match_id}.json", match_record(m, runs_dir, app_cfg))
    for m in retracted:
        _write_json(out / "retracted" / f"{m.match_id}.json", match_record(m, runs_dir, app_cfg))

    _write_json(out / "models.json", models)
    _write_json(out / "drafts.json", draft_rows(app_cfg, load_drafts(version=app_cfg.ruleset.version)))
    reference = REFERENCE_TEAMS  # credited community teams: tests, fixed-team benchmarks and the meta score
    _write_json(out / "reference_teams.json", json.loads(reference.read_text(encoding="utf-8")) if reference.exists() else {"teams": []})
    _write_json(out / "head_to_head.json", {b.id: _head_to_head(states[b.id]) for b in boards})
    _write_json(out / "findings.json", findings(models, state.matches + retracted))
    _write_json(out / "meta.json", {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "game": GAME,
        "formats": sorted({m.format for m in state.matches}),
        "version": app_cfg.ruleset.version,
        "versions": all_versions,
        "rulesets": {v: stored_rules(v) for v in all_versions},
        "rules_mismatch": state.rules_mismatch,
        "leaderboards": [{**b.model_dump(), "rated_matches": len(states[b.id].outcomes),
                          "models": sum(1 for r in states[b.id].ratings.values() if r.games)} for b in boards],
        "ruleset": app_cfg.ruleset.model_dump(),
        "ladder": app_cfg.ladder.model_dump(),
        "matches": len(state.matches),
        "rated_matches": len(state.outcomes),
        "void_matches": state.void_count,
        "retracted_matches": len(retracted),
        "turns": sum(len(m.breadcrumbs) for m in state.matches),
        "tokens": sum((b.llm_metrics or {}).get("total_tokens", 0) for m in state.matches for b in m.breadcrumbs),
    })
    return {"models": len(models), "matches": len(state.matches), "rated": len(state.outcomes),
            "void": state.void_count, "retracted": len(retracted)}
