"""Tests for PokéChamp Minimax Search Engine and Opponent Modeling."""

import pytest
import asyncio
from poke_env.battle import MoveCategory
from rotomarena.search.minimax import PokeChampSearchEngine
from rotomarena.search.opponent_model import sample_opponent_actions


from .mocks import MockBattle


@pytest.mark.asyncio
async def test_sample_opponent_actions():
    battle = MockBattle()
    actions = sample_opponent_actions(battle, top_k=3)
    assert len(actions) > 0
    # Expected to include flamethrower
    assert any("flamethrower" in tgt for _, tgt, _ in actions)


@pytest.mark.asyncio
async def test_pokechamp_search_depth_1():
    battle = MockBattle()
    engine = PokeChampSearchEngine(depth=1, use_llm_prior=False)
    order, telemetry = await engine.search(battle)

    assert telemetry.nodes_evaluated > 0
    assert telemetry.depth == 1
    assert len(telemetry.candidate_scores) > 0
    # Great Tusk against Heatran should favor Earthquake (Ground move)
    assert "earthquake" in telemetry.best_action.lower()


@pytest.mark.asyncio
async def test_pokechamp_search_depth_2():
    battle = MockBattle()
    engine = PokeChampSearchEngine(depth=2, use_llm_prior=False)
    order, telemetry = await engine.search(battle)

    assert telemetry.nodes_evaluated >= telemetry.depth
    assert telemetry.depth == 2
    assert telemetry.best_score > -1.0
