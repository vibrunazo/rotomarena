"""Tests for match outcomes, Bradley-Terry ratings, ladder planning and the site export."""

import json
import random


from rotomarena.config import AgentConfig, AppConfig, TelemetryConfig
from rotomarena.export.site import export_site, parse_choice, scrub
from rotomarena.ladder import closest_rated_llm, fill_pairs, fixed_placement_opponents
from rotomarena.rating import Rating, compute_ratings
from rotomarena.results import Outcome, outcome, void_reason
from rotomarena.telemetry.breadcrumbs import MatchPlayer, MatchTelemetry, TurnBreadcrumb


def make_match(match_id, p1, p2, winner, p1_sources=("model",) * 4, p2_sources=("model",) * 4, season="s1"):
    players = [
        MatchPlayer(role="p1", config_id=p1, display_name=p1.title(), agent_type="direct_llm", team="Balance"),
        MatchPlayer(role="p2", config_id=p2, display_name=p2.title(), agent_type="direct_llm", team="Rain"),
    ]
    crumbs = [
        TurnBreadcrumb(turn=i + 1, agent_name=pl.display_name, agent_type="direct_llm", decision_source=src,
                       chosen_action="/choose move earthquake", active_pokemon="greattusk",
                       reasoning="Earthquake is 4x super effective." if src == "model" else "[API ERROR] sk-live-123456789",
                       llm_metrics={"total_tokens": 1000 if pl.role == "p1" else 3000})
        for pl, sources in ((players[0], p1_sources), (players[1], p2_sources))
        for i, src in enumerate(sources)
    ]
    winner_name = {p1: p1.title(), p2: p2.title()}.get(winner)
    return MatchTelemetry(match_id=match_id, ruleset={"version": season}, players=players,
                          winner=winner_name, total_turns=len(p1_sources), breadcrumbs=crumbs)


def test_outcome_and_void_rules():
    assert outcome(make_match("m1", "alpha", "beta", "beta")).score_p1 == 0.0
    assert outcome(make_match("m2", "alpha", "beta", None)).score_p1 == 0.5
    assert void_reason(make_match("m3", "alpha", "alpha", "alpha"), 0.5) == "self-play"
    lazy = make_match("m4", "alpha", "beta", "alpha", p1_sources=("api_error",) * 3 + ("model",))
    assert "alpha was on autopilot for 75%" in void_reason(lazy, 0.5)
    assert void_reason(make_match("m5", "alpha", "beta", "alpha"), 0.5) is None


def test_ratings_recover_known_strengths_and_anchor():
    random.seed(7)
    true = {"heuristic": 1500, "strong": 1750, "weak": 1300, "even": 1500}
    outcomes = []
    for _ in range(3000):
        a, b = random.sample(list(true), 2)
        p = 1 / (1 + 10 ** ((true[b] - true[a]) / 400))
        outcomes.append(Outcome("m", a, b, 1.0 if random.random() < p else 0.0))
    ratings = compute_ratings(outcomes, "heuristic", bootstrap_samples=200)
    assert ratings["heuristic"].rating == 1500.0
    for pid, value in true.items():
        assert abs(ratings[pid].rating - value) < 60
        assert ratings[pid].ci_low <= ratings[pid].rating <= ratings[pid].ci_high
    assert ratings["strong"].rating > ratings["even"].rating > ratings["weak"].rating


def test_isolated_players_are_unranked_and_small_samples_stay_finite():
    outcomes = [Outcome("m", "heuristic", "rookie", 0.0)] * 4 + [Outcome("m", "island", "volcano", 1.0)]
    ratings = compute_ratings(outcomes, "heuristic", bootstrap_samples=100)
    assert not ratings["island"].ranked and ratings["island"].wins == 1
    rookie = ratings["rookie"]
    assert 1500 < rookie.rating < 2500
    assert rookie.ci_low < rookie.rating  # four straight wins still leave a wide interval


def test_placement_plan_and_closest_rival():
    agents = {
        "heuristic": AgentConfig(name="heuristic", type="heuristic", role="anchor"),
        "pokechamp": AgentConfig(name="pokechamp", type="pokechamp", role="anchor"),
        "nemotron": AgentConfig(name="nemotron", type="direct_llm", role="sparring"),
        "gemma": AgentConfig(name="gemma", type="direct_llm", role="sparring"),
        "qwen": AgentConfig(name="qwen", type="direct_llm"),
        "granite": AgentConfig(name="granite", type="direct_llm"),
        "newbie": AgentConfig(name="newbie", type="direct_llm"),
    }
    assert fixed_placement_opponents("newbie", agents) == ["heuristic", "pokechamp", "nemotron"]
    assert fixed_placement_opponents("nemotron", agents) == ["heuristic", "pokechamp", "gemma"]
    ratings = {
        "newbie": Rating("newbie", 1610, 1400, 1800, 12, 7, 5, 0),
        "qwen": Rating("qwen", 1500, 1400, 1600, 16, 8, 8, 0),
        "granite": Rating("granite", 1650, 1550, 1750, 16, 10, 6, 0),
        "nemotron": Rating("nemotron", 1600, 1500, 1700, 16, 9, 7, 0),
    }
    assert closest_rated_llm("newbie", agents, ratings, exclude=["nemotron"]) == "granite"


def test_fill_prefers_overlapping_free_neighbours(tmp_path):
    agents = {
        "heuristic": AgentConfig(name="heuristic", type="heuristic", role="anchor"),
        "local_a": AgentConfig(name="local_a", type="direct_llm", provider="local", model="a"),
        "local_b": AgentConfig(name="local_b", type="direct_llm", provider="local", model="b"),
        "paid": AgentConfig(name="paid", type="direct_llm", provider="openrouter", model="lab/paid-model"),
    }
    from rotomarena.ladder import SeasonState
    state = SeasonState([], [], {
        "heuristic": Rating("heuristic", 1500, 1500, 1500, 8, 4, 4, 0),
        "local_a": Rating("local_a", 1600, 1450, 1750, 8, 5, 3, 0),
        "local_b": Rating("local_b", 1650, 1500, 1800, 8, 5, 3, 0),
        "paid": Rating("paid", 1700, 1600, 1800, 8, 6, 2, 0),
    }, {})
    assert fill_pairs(state, agents)[0] == ("local_b", "local_a")
    assert all("paid" not in pair for pair in fill_pairs(state, agents))
    assert any("paid" in pair for pair in fill_pairs(state, agents, free_only=False))


def test_parse_choice_and_scrub():
    assert parse_choice("/choose move terablast terastallize") == {"kind": "move", "target": "terablast", "tera": True}
    assert parse_choice("/choose switch kingambit")["kind"] == "switch"
    assert scrub({"a": ["Incorrect API key provided: sk-or-v1-abcdef123456"]}) == {"a": ["Incorrect API key provided: [redacted]"]}


def test_export_site_writes_the_season_and_the_archive(tmp_path):
    runs = tmp_path / "runs"
    matches = [
        make_match("match_20261006_100000_a_vs_b_g1", "heuristic", "qwen", "qwen"),
        make_match("match_20261006_100100_a_vs_b_g2", "qwen", "heuristic", "qwen"),
        make_match("match_20261006_100200_a_vs_b_g3", "heuristic", "granite", "heuristic"),
        make_match("match_20261006_100300_a_vs_b_g4", "granite", "qwen", "granite",
                   p1_sources=("api_error",) * 4),  # void: granite never answered
        make_match("match_20260830_120000_old_g1", "muse_spark", "deepseek", "muse_spark",
                   p1_sources=("api_error",) * 4, season="v0"),
    ]
    for m in matches:
        m.save_json(runs / m.match_id / "breadcrumbs.json")
    app_cfg = AppConfig(telemetry=TelemetryConfig(output_dir=runs))
    app_cfg.ladder.bootstrap_samples = 50

    counts = export_site(app_cfg, tmp_path / "data")
    assert counts == {"models": 3, "matches": 4, "rated": 3, "void": 1, "retracted": 1}

    data = tmp_path / "data"
    models = {m["config_id"]: m for m in json.loads((data / "models.json").read_text(encoding="utf-8"))}
    assert models["heuristic"]["rating"] == 1500.0
    assert models["qwen"]["games"] == 2 and models["qwen"]["signature_move"] == "earthquake"
    assert models["granite"]["autopilot_rate"] > 0
    findings = {f["id"]: f for f in json.loads((data / "findings.json").read_text(encoding="utf-8"))}
    # granite won a void match without answering once; muse_spark did it in the archive
    assert {w["config_id"] for w in findings["zero-token-wins"]["wins"]} == {"granite", "muse_spark"}
    void = json.loads((data / "matches" / "match_20261006_100300_a_vs_b_g4.json").read_text(encoding="utf-8"))
    assert "autopilot" in void["void_reason"]
    assert "sk-live" not in (data / "retracted" / "match_20260830_120000_old_g1.json").read_text(encoding="utf-8")
    assert json.loads((data / "meta.json").read_text(encoding="utf-8"))["retracted_matches"] == 1
