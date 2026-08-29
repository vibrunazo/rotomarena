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


def test_heuristic_player_choice():
    player = HeuristicPlayer(player_name="TestHeuristic")
    battle = MockBattle()
    order = player.choose_move(battle)
    assert order is not None
    # Great Tusk against Heatran should select Earthquake
    assert "earthquake" in str(order.message).lower()


def test_max_damage_player_choice():
    player = MaxDamagePlayer(player_name="TestMaxDmg")
    battle = MockBattle()
    order = player.choose_move(battle)
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
