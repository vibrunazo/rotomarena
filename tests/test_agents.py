"""Tests for Agent implementations and decision formatting."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from poke_env.battle import MoveCategory
from rotomarena.agents.heuristic import MaxDamagePlayer, HeuristicPlayer
from rotomarena.agents.direct_llm import DirectLLMPlayer
from rotomarena.agents.random import RandomBenchmarkPlayer
from rotomarena.llm.client import LLMClient
from rotomarena.llm.schemas import ActionDecision, LLMUsageMetrics
from .mocks import MockBattle


@pytest.mark.asyncio
async def test_heuristic_player_choice():
    player = HeuristicPlayer(player_name="TestHeuristic")
    battle = MockBattle()
    order = await player.choose_move(battle)
    assert order is not None
    # Great Tusk against Heatran should select Earthquake
    assert "earthquake" in str(order.message).lower()


@pytest.mark.asyncio
async def test_max_damage_player_choice():
    player = MaxDamagePlayer(player_name="TestMaxDmg")
    battle = MockBattle()
    order = await player.choose_move(battle)
    assert order is not None
    assert "earthquake" in str(order.message).lower()


@pytest.mark.asyncio
async def test_direct_llm_player_decision_and_fallback():
    mock_llm = MagicMock(spec=LLMClient)
    # Mock LLM returning valid move
    mock_llm.generate_cot_decision = AsyncMock(
        return_value=ActionDecision(
            action_type="MOVE",
            target="earthquake",
            terastallize=False,
            reasoning="Earthquake hits 4x super effective against Heatran.",
            metrics=LLMUsageMetrics(prompt_tokens=100, completion_tokens=50, total_tokens=150, latency_ms=120.0),
        )
    )

    player = DirectLLMPlayer(player_name="TestLLM", llm_client=mock_llm)
    battle = MockBattle()
    order = await player._async_choose_move(battle)
    assert "earthquake" in str(order.message).lower()

    # Test fallback when LLM returns invalid move
    mock_llm.generate_cot_decision = AsyncMock(
        return_value=ActionDecision(
            action_type="MOVE",
            target="nonexistentmove",
            terastallize=False,
            reasoning="Invalid move hallucination",
        )
    )
    fallback_order = await player._async_choose_move(battle)
    assert fallback_order is not None


@pytest.mark.asyncio
async def test_agent_turn_timeout_fallback():
    mock_llm = MagicMock(spec=LLMClient)
    
    # Simulate a hanging LLM call
    async def _hanging_call(*args, **kwargs):
        await asyncio.sleep(5.0)
        return ActionDecision(action_type="MOVE", target="earthquake", reasoning="Too late")

    mock_llm.generate_cot_decision = _hanging_call

    # Set turn timeout to 0.1s
    player = DirectLLMPlayer(player_name="SlowLLM", llm_client=mock_llm, turn_timeout=0.1)
    battle = MockBattle()

    # choose_move should gracefully time out and return default fallback move
    order = await player.choose_move(battle)
    assert order is not None
    assert hasattr(order, "message")
