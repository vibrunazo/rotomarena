"""Tests for match outcomes, Bradley-Terry ratings, ladder planning and the site export."""

import json
import random
from types import SimpleNamespace

import pytest

from rotomarena.config import AgentConfig, AppConfig, TelemetryConfig
from rotomarena.export.site import export_site, parse_choice, public_log, scrub
from rotomarena.ladder import RunHalted, check_halt, closest_rated_llm, fill_pairs, fixed_placement_opponents
from rotomarena.rating import Rating, compute_ratings
from rotomarena.results import Outcome, outcome, void_reason
from rotomarena.telemetry.breadcrumbs import MatchPlayer, MatchTelemetry, TurnBreadcrumb


def make_match(match_id, p1, p2, winner, p1_sources=("model",) * 4, p2_sources=("model",) * 4, season="s1"):
    players = [
        MatchPlayer(role="p1", config_id=p1, display_name=p1.title(), username=p1.title(), agent_type="direct_llm",
                    team="Balance"),
        MatchPlayer(role="p2", config_id=p2, display_name=p2.title(), username=p2.title(), agent_type="direct_llm",
                    team="Rain"),
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
    from rotomarena.ladder import LadderState
    state = LadderState([], [], {
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
    app_cfg.ladder.anchor = "heuristic"
    app_cfg.agents["qwen"] = AgentConfig(name="qwen", type="direct_llm", provider="local", model="qwen3.8-27b",
                                         model_key="qwen/qwen3.8-27b")

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
    meta = json.loads((data / "meta.json").read_text(encoding="utf-8"))
    assert meta["retracted_matches"] == 1 and meta["game"] == "pokemon" and meta["formats"] == ["gen9ou"]
    # the cross-game identity: set in the registry for local models, absent for bots
    assert models["qwen"]["model_key"] == "qwen/qwen3.8-27b" and models["heuristic"]["model_key"] is None
    assert void["game"] == "pokemon" and {p["config_id"]: p["model_key"] for p in void["players"]}["qwen"] == "qwen/qwen3.8-27b"


def _fake_gen(monkeypatch, running):
    from rotomarena import local_servers

    calls = []
    monkeypatch.setattr(local_servers, "running", lambda cfg: dict(running))
    monkeypatch.setattr(local_servers, "catalog_sizes",
                        lambda cfg: {"bonsai": 7.2, "minicpm5-2b": 2.7, "qwen3.8-27b": 16.5})
    monkeypatch.setattr(local_servers, "_gen", lambda cfg, *args: calls.append(args) or type("R", (), {"returncode": 0})())
    return local_servers, calls


BONSAI = AgentConfig(name="bonsai_2_27b", type="direct_llm", provider="local", model="bonsai", port=8080)
MINICPM = AgentConfig(name="minicpm", type="direct_llm", provider="local", model="minicpm5-2b", port=8086)
QWEN = AgentConfig(name="qwen", type="direct_llm", provider="local", model="qwen3.8-27b", port=8081)


def test_a_pair_that_fits_stays_loaded_smallest_first(monkeypatch):
    local_servers, calls = _fake_gen(monkeypatch, {8083: "granite-4.2-30b"})
    local_servers.prepare([BONSAI, MINICPM], AppConfig(), log=lambda msg: None)
    serves = [c for c in calls if c[0] == "serve"]
    assert calls[0] == ("stop", "--port", "8083")
    assert [c[2] for c in serves] == ["minicpm5-2b", "bonsai"]
    first = list(serves[0])
    assert first[first.index("--ctx") + 1] == "8192" and first[first.index("--slots") + 1] == "4"  # one per parallel game
    assert first[first.index("--reasoning-budget") + 1] == "2048"  # half the ladder's 4096-token cap
    assert not local_servers.swapping()


def test_a_pair_too_big_for_the_gpu_swaps_per_request(monkeypatch):
    import asyncio

    local_servers, calls = _fake_gen(monkeypatch, {8080: "bonsai"})
    local_servers.prepare([QWEN, BONSAI], AppConfig(), log=lambda msg: None)
    assert local_servers.swapping()
    assert [c for c in calls if c[0] == "serve"] == []  # nothing loaded until someone asks

    calls.clear()

    async def two_lanes_ask_at_once():
        await asyncio.gather(local_servers.ensure_loaded(8081), local_servers.ensure_loaded(8081))

    asyncio.run(two_lanes_ask_at_once())  # one load, not two
    asyncio.run(local_servers.ensure_loaded(8081))  # already loaded: no-op
    asyncio.run(local_servers.ensure_loaded(8080))
    assert [c[:3] for c in calls] == [("serve", "--model", "qwen3.8-27b"), ("stop", "--port", "8081"),
                                      ("serve", "--model", "bonsai")]
    local_servers.prepare([BONSAI], AppConfig(), log=lambda msg: None)
    assert not local_servers.swapping()


def test_local_model_port_sets_the_endpoint():
    from rotomarena.agents.factory import create_agent_instance

    app_cfg = AppConfig.default_config()
    agent = create_agent_instance(app_cfg.agents["bonsai_2_27b"], app_cfg, start_listening=False)
    assert agent.llm_client.config.base_url == "http://127.0.0.1:8080/v1"


def test_control_games_only_for_models_under_the_cost_limit(monkeypatch):
    from rotomarena import ladder

    app = AppConfig(agents={
        "random_ai": AgentConfig(name="random_ai", type="random", role="control"),
        "local": AgentConfig(name="local", type="direct_llm", provider="local", model="bonsai"),
        "pricey": AgentConfig(name="pricey", type="direct_llm", provider="openrouter", model="lab/frontier"),
    })
    monkeypatch.setattr(ladder, "estimated_cost_per_game", lambda cfg, app_cfg: 0.0 if cfg.name == "local" else 3.5)
    quiet = lambda msg: None
    assert ladder.control_opponents("local", app, log=quiet) == ["random_ai"]
    assert ladder.control_opponents("pricey", app, log=quiet) == []
    assert ladder.control_opponents("pricey", app, force=True, log=quiet) == ["random_ai"]
    assert ladder.control_opponents("random_ai", app, log=quiet) == []


def test_public_log_keeps_the_battle_and_drops_the_room():
    log = [
        "|j|☆Bonsai 2 27B",
        "|player|p1|Bonsai 2 27B|1|",
        "|player|p2|Random AI|2|",
        "|j| somespectator",
        "|c|☆Bonsai 2 27B|Move locked in",
        '|html|<div class="message-error">You must be registered to chat</div>',
        "|move|p1a: Ting-Lu|Earthquake|p2a: Ribombee",
        "|l| somespectator",
        "|win|Bonsai 2 27B",
    ]
    assert public_log(log) == [log[0], log[1], log[2], log[6], log[8]]


def test_run_halts_on_a_provider_limit_or_two_void_games_in_a_row():
    void = make_match("m1", "alpha", "beta", "beta", p1_sources=("api_error",) * 4)
    fine = make_match("m2", "alpha", "beta", "beta")
    healthy = SimpleNamespace(provider_limit=None)
    check_halt("alpha vs beta", [healthy], [void, fine], 0.5)  # one void game is bad luck
    check_halt("alpha vs beta", [healthy], [void, fine, void], 0.5)
    with pytest.raises(RunHalted, match="two void games in a row"):
        check_halt("alpha vs beta", [healthy], [fine, void, void], 0.5)
    with pytest.raises(RunHalted, match="alpha vs beta: provider limit reached: HTTP 402"):
        check_halt("alpha vs beta", [SimpleNamespace(provider_limit="HTTP 402"), healthy], [], 0.5)


def test_parallel_rounds_keep_the_set_schedule():
    from rotomarena.ladder import rounds

    assert rounds(0, 4, 4) == [[0, 1, 2, 3]]
    assert rounds(1, 3, 4) == [[1, 2, 3]]  # resuming after one game
    assert rounds(0, 4, 3) == [[0, 1, 2], [3]]
    assert rounds(0, 3, 1) == [[0], [1], [2]]  # parallel_games: 1 plays one game at a time


def test_a_rate_limited_api_plays_fewer_games_at_once():
    from rotomarena.ladder import lane_count

    app_cfg = AppConfig()
    nemotron = AgentConfig(name="nemotron", type="direct_llm")
    gemma = AgentConfig(name="gemma", type="direct_llm", max_parallel_games=1)
    assert lane_count(nemotron, AgentConfig(name="pokechamp", type="pokechamp"), app_cfg, remaining=4) == 4
    assert lane_count(nemotron, gemma, app_cfg, remaining=4) == 1
    assert lane_count(nemotron, nemotron, app_cfg, remaining=3) == 3


def test_round_robin_pairs_every_model_once_in_balanced_rounds():
    from rotomarena.ladder import round_robin_pairs

    ids = [f"m{i}" for i in range(10)]
    pairs = round_robin_pairs(ids)
    assert len(pairs) == 45 and len({frozenset(p) for p in pairs}) == 45
    for r in range(9):  # each round of 5 games has every model exactly once
        assert sorted(x for p in pairs[r * 5:(r + 1) * 5] for x in p) == sorted(ids)
    assert len(round_robin_pairs(["a", "b", "c"])) == 3  # odd counts sit one out per round
    from rotomarena.ladder import anchor_first
    first = anchor_first(pairs, "m3")
    assert all("m3" in p for p in first[:9]) and set(map(frozenset, first)) == set(map(frozenset, pairs))


def test_own_teams_keep_each_players_team_and_alternate_sides():
    import asyncio
    from types import SimpleNamespace
    from rotomarena.matchmaker.runner import MatchRunner

    calls = []
    runner = MatchRunner()

    async def fake_battle(challenger, opponent, team_names, game):
        calls.append((challenger.agent_name, team_names))

    runner.run_single_battle = fake_battle
    team = lambda n: SimpleNamespace(name=n, to_showdown_packed=lambda: n)
    a = SimpleNamespace(agent_name="A", update_team=lambda t: None)
    b = SimpleNamespace(agent_name="B", update_team=lambda t: None)
    for g in range(4):
        asyncio.run(runner.run_game(a, b, team("A's team"), team("B's team"), g, own_teams=True))
    assert [c[0] for c in calls] == ["A", "B", "A", "B"]
    assert all(dict(zip((c[0], "A" if c[0] == "B" else "B"), c[1]))["A"] == "A's team" for c in calls)


def test_a_version_stores_its_rules_and_refuses_changed_ones(tmp_path):
    from rotomarena.rulesets import RulesChanged, register, same_rules, stored_rules

    cfg = AppConfig()
    rules = register(cfg, rulesets_dir=tmp_path)  # first run stores them
    assert stored_rules(cfg.ruleset.version, tmp_path) == rules and "battle_prompt" in rules and rules["format"] == "gen9ou"
    assert register(cfg, rulesets_dir=tmp_path) == rules  # same rules: fine
    cfg.ruleset.max_output_tokens = 1024
    with pytest.raises(RulesChanged, match="max_output_tokens"):
        register(cfg, rulesets_dir=tmp_path)
    # games are judged on what they recorded: older games lack the prompt fingerprints
    assert same_rules({"version": "s1", "max_output_tokens": 4096}, rules)
    assert not same_rules({"version": "s1", "max_output_tokens": 1024}, rules)
