"""Exports the current season (and the retracted v0 archive) as JSON for the Astro site."""

from __future__ import annotations

import datetime
import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from rotomarena.config import AppConfig
from rotomarena.ladder import SeasonState, season_state
from rotomarena.rating import Rating
from rotomarena.results import autopilot_rate, load_matches, player_turns, void_reason
from rotomarena.telemetry.breadcrumbs import MatchTelemetry, TurnBreadcrumb
from rotomarena.telemetry.replay_saver import flatten_logs

RETRACTED_SEASON = "v0"
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
    return crumb.reasoning if crumb.decision_source == "model" and crumb.agent_type == "direct_llm" else ""


def _turn_entries(match: MatchTelemetry) -> List[Dict[str, Any]]:
    roles = {p.display_name: p.role for p in match.players}
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


def _raw_log(runs_dir: Path, match_id: str) -> List[str]:
    path = runs_dir / match_id / "battle_log.json"
    if not path.exists():
        return []
    return flatten_logs(json.loads(path.read_text(encoding="utf-8")).get("raw_logs", []))


def match_record(match: MatchTelemetry, runs_dir: Path, max_autopilot: float) -> Dict[str, Any]:
    winner_role = next((p.role for p in match.players if p.display_name == match.winner), None)
    return {
        "id": match.match_id,
        "season": match.ruleset.get("version"),
        "date": match.match_id.split("_")[1] if match.match_id.count("_") > 1 else "",
        "players": [
            {**p.model_dump(), "autopilot_rate": round(autopilot_rate(match, p.role), 3)} for p in match.players
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
    """Behaviour across every match a model played this season, rated or not."""
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
        "tokens_per_turn": round(statistics.mean(x.get("total_tokens", 0) for x in metrics)) if metrics else None,
        "cost_usd": round(sum(x.get("cost_usd", 0.0) for x in metrics), 4),
        "cost_per_game_usd": round(sum(x.get("cost_usd", 0.0) for x in metrics) / played, 4) if played else 0.0,
        "switch_rate": round(sum(1 for c in choices if c["kind"] == "switch") / (len(choices) or 1), 3),
        "signature_move": moves.most_common(1)[0][0] if moves else None,
        "favorite_pokemon": Counter(b.active_pokemon for b in turns).most_common(1)[0][0] if turns else None,
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
    llms = [m for m in models if m["type"] == "direct_llm"]
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
        {"config_id": p.config_id, "match_id": m.match_id, "season": m.ruleset.get("version")}
        for m in all_matches for p in m.players
        if p.display_name == m.winner and p.agent_type == "direct_llm" and autopilot_rate(m, p.role) == 1.0
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


def _model_rows(state: SeasonState, app_cfg: AppConfig) -> List[Dict[str, Any]]:
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
    state = season_state(app_cfg)
    retracted = load_matches(runs_dir, RETRACTED_SEASON)
    models = _model_rows(state, app_cfg)

    for sub in ("matches", "retracted"):
        for stale in (out / sub).glob("*.json"):
            stale.unlink()

    for m in state.matches:
        _write_json(out / "matches" / f"{m.match_id}.json", match_record(m, runs_dir, app_cfg.ladder.max_autopilot))
    for m in retracted:
        _write_json(out / "retracted" / f"{m.match_id}.json", match_record(m, runs_dir, app_cfg.ladder.max_autopilot))

    head_to_head: Dict[frozenset, Dict[str, Any]] = {}
    for o in state.outcomes:
        a, b = sorted((o.p1, o.p2))
        row = head_to_head.setdefault(frozenset((a, b)), {"a": a, "b": b, "games": 0, "a_wins": 0, "b_wins": 0, "draws": 0})
        row["games"] += 1
        score_a = o.score_p1 if o.p1 == a else 1.0 - o.score_p1
        if score_a == 1.0:
            row["a_wins"] += 1
        elif score_a == 0.0:
            row["b_wins"] += 1
        else:
            row["draws"] += 1

    _write_json(out / "models.json", models)
    _write_json(out / "head_to_head.json", sorted(head_to_head.values(), key=lambda r: (r["a"], r["b"])))
    _write_json(out / "findings.json", findings(models, state.matches + retracted))
    _write_json(out / "meta.json", {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "season": app_cfg.ruleset.version,
        "ruleset": app_cfg.ruleset.model_dump(),
        "anchor": app_cfg.ladder.anchor,
        "anchor_rating": app_cfg.ladder.anchor_rating,
        "matches": len(state.matches),
        "rated_matches": len(state.outcomes),
        "void_matches": state.void_count,
        "retracted_matches": len(retracted),
        "turns": sum(len(m.breadcrumbs) for m in state.matches),
        "tokens": sum((b.llm_metrics or {}).get("total_tokens", 0) for m in state.matches for b in m.breadcrumbs),
    })
    return {"models": len(models), "matches": len(state.matches), "rated": len(state.outcomes),
            "void": state.void_count, "retracted": len(retracted)}
