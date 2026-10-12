"""Battles in Showdown's simulator, without the chat server (rotomarena.server.sim). Needs Node and the local
Showdown build; skipped without them."""

import asyncio
import shutil
from pathlib import Path

import pytest

from rotomarena.agents.factory import create_agent_instance
from rotomarena.config import AgentConfig, AppConfig
from rotomarena.server.sim import Simulator

SHOWDOWN = Path(__file__).resolve().parents[1] / "server" / "pokemon-showdown"
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (SHOWDOWN / "dist" / "sim" / "battle-stream.js").exists(),
    reason="needs Node and the Showdown build",
)
FORMAT = "gen9championsrotomarenabssregmb"
DRAFT = Path(__file__).resolve().parents[1] / "data" / "drafts" / FORMAT / "c4" / "gemini_3_8_flash.json"


def _team() -> str:
    """A legal Champions team: one of c4's drafts."""
    import json

    from rotomarena.teams.draft import playable_team

    return playable_team(json.loads(DRAFT.read_text(encoding="utf-8")))


def _bots():
    from rotomarena.teams.loader import parse_smogon_team

    app = AppConfig(ruleset={"format": FORMAT, "pick": 3})
    team = parse_smogon_team(_team()).to_showdown_packed()
    players = []
    for name, kind in (("Search Bot", "pokechamp"), ("Chimps at the Zoo", "random")):
        player = create_agent_instance(AgentConfig(name=kind, type=kind, display_name=name), app, start_listening=False)
        player.update_team(team)
        players.append(player)
    return players


def test_a_battle_runs_to_the_end_at_the_formats_level():
    async def play():
        a, b = _bots()
        async with Simulator(SHOWDOWN) as sim:
            result = await sim.play(a, b, FORMAT, timeout=120)
        return a, b, result

    a, b, result = asyncio.run(play())
    battle = a.battles[result.tag]
    assert battle.finished and result.end["winner"] in (a.username, b.username)
    assert result.end["seed"]  # replayable: the seed and every input
    # Champions plays at level 50: the team only gets there through the format's validator, as on the server
    assert all(mon.level == 50 for mon in battle.team.values())
    assert any(line.startswith("|move|") for line in result.spectator)


def test_an_illegal_team_is_refused():
    async def play():
        a, b = _bots()
        import re

        a.update_team(re.sub(r"@ [^\n]+", "@ Leftovers", _team()))  # six Leftovers: Item Clause
        async with Simulator(SHOWDOWN) as sim:
            await sim.play(a, b, FORMAT, timeout=60)

    with pytest.raises(RuntimeError, match="illegal team"):
        asyncio.run(play())
