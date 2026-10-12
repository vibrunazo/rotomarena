"""Expensive models: placement in the round robin, then sets against their nearest-rated neighbours."""

import asyncio

from rotomarena import ladder
from rotomarena.config import AgentConfig, AppConfig, LadderConfig
from rotomarena.rating import Rating


def _app():
    agents = {k: AgentConfig(name=k, type="direct_llm", provider="openrouter", model=f"lab/{k}")
              for k in ("anchor", "low", "mid", "high")}
    agents["chimps"] = AgentConfig(name="chimps", type="random", role="control")
    agents["opus"] = AgentConfig(name="opus", type="direct_llm", provider="openrouter", model="lab/opus",
                                 max_games=6, pairing={"v1": "neighbours"})
    return AppConfig(agents=agents, ladder=LadderConfig(anchor="anchor"), ruleset={"version": "v1"})


def test_a_neighbours_model_plays_only_its_placement_in_the_round_robin(monkeypatch):
    app = _app()
    monkeypatch.setattr(ladder, "round_robin_ids", lambda cfg, log=None: list(cfg.agents))
    state = ladder.LadderState([], [], {}, {})
    pairs = ladder.schedule(app, state, 3)
    assert {frozenset(p) for p in pairs if "opus" in p} == {frozenset(("opus", "anchor")), frozenset(("opus", "chimps"))}
    assert frozenset(("low", "high")) in {frozenset(p) for p in pairs}  # everyone else plays everyone


def test_neighbours_play_the_nearest_rating_until_the_cap(monkeypatch):
    app = _app()
    played = []
    ratings = {"anchor": 1500, "low": 1300, "mid": 1650, "high": 1900, "chimps": 1000, "opus": 1700}

    def state(cfg, rate=True):
        games = {}
        for a, b, n in played:
            games[frozenset((a, b))] = games.get(frozenset((a, b)), 0) + n
        return ladder.LadderState([], [], {k: Rating(k, r, r - 150, r + 150, 9, 5, 4, 0) for k, r in ratings.items()},
                                  games)

    async def play_set(a, b, cfg, done, games=None):
        played.append((a, b, games - done))
        return games - done

    monkeypatch.setattr(ladder, "round_robin_ids", lambda cfg, log=None: list(cfg.agents))
    monkeypatch.setattr(ladder, "version_state", state)
    monkeypatch.setattr(ladder, "play_set", play_set)
    monkeypatch.setattr(ladder, "games_left", lambda cfg, agent: 6 - sum(n for a, b, n in played if agent.name in (a, b))
                        if agent.name == "opus" else 99)
    asyncio.run(ladder.neighbours(app, 3, log=lambda msg: None))
    # opus (1700) meets its nearest, mid (1650), for the 2 sets ladder.neighbour_repeats allows; its cap (6) ends it there
    assert played == [("opus", "mid", 3), ("opus", "mid", 3)]


def test_neighbours_stop_once_the_rating_is_precise(monkeypatch):
    app = _app()
    precise = {"opus": Rating("opus", 1700, 1650, 1750, 40, 20, 20, 0), "mid": Rating("mid", 1650, 1600, 1700, 9, 5, 4, 0)}
    monkeypatch.setattr(ladder, "round_robin_ids", lambda cfg, log=None: list(cfg.agents))
    monkeypatch.setattr(ladder, "version_state", lambda cfg, rate=True: ladder.LadderState([], [], precise, {}))
    monkeypatch.setattr(ladder, "games_left", lambda cfg, agent: 10)
    called = []

    async def play_set(*args, **kwargs):
        called.append(args)
        return 3

    monkeypatch.setattr(ladder, "play_set", play_set)
    asyncio.run(ladder.neighbours(app, 3, log=lambda msg: None))
    assert called == []  # +-50 is within the default precision (100)
