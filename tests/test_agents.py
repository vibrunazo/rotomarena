"""Tests for Agent implementations and decision handling."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from rotomarena.agents.heuristic import MaxDamagePlayer, HeuristicPlayer
from rotomarena.agents.direct_llm import DirectLLMPlayer
from rotomarena.llm.client import LLMClient
from rotomarena.llm.schemas import ActionDecision, LLMUsageMetrics
from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder
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


def _llm_player(decision=None, side_effect=None):
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.generate_cot_decision = AsyncMock(return_value=decision, side_effect=side_effect)
    player = DirectLLMPlayer(player_name="TestLLM", llm_client=mock_llm)
    recorder = BreadcrumbsRecorder("test_match")
    player.set_recorder(recorder)
    return player, recorder


@pytest.mark.asyncio
async def test_direct_llm_plays_a_legal_move():
    player, recorder = _llm_player(
        ActionDecision(
            action_type="MOVE",
            target="earthquake",
            reasoning="Earthquake hits 4x super effective against Heatran.",
            metrics=LLMUsageMetrics(prompt_tokens=100, completion_tokens=50, total_tokens=150, latency_ms=120.0),
        )
    )
    order = await player._async_choose_move(MockBattle())
    assert "earthquake" in str(order.message).lower()
    crumb = recorder.breadcrumbs[-1]
    assert crumb.decision_source == "model"
    assert crumb.llm_metrics["total_tokens"] == 150


@pytest.mark.asyncio
async def test_direct_llm_switches_by_exact_species_id():
    player, recorder = _llm_player(ActionDecision(action_type="SWITCH", target="kingambit"))
    order = await player._async_choose_move(MockBattle())
    assert "kingambit" in str(order.message).lower()
    assert recorder.breadcrumbs[-1].decision_source == "model"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision, side_effect, source",
    [
        (ActionDecision(action_type="MOVE", target="earth"), None, "invalid"),  # no partial matches
        (ActionDecision(action_type="MOVE", target="kingambit"), None, "invalid"),  # a switch named as a move
        (ActionDecision(parse_error="missing <decision>...</decision> block", raw_response="hmm"), None, "parse_error"),
        (None, RuntimeError("LLM request failed"), "api_error"),
    ],
)
async def test_direct_llm_failures_play_the_default_move(decision, side_effect, source):
    player, recorder = _llm_player(decision, side_effect)
    battle = MockBattle()
    order = await player._async_choose_move(battle)
    assert battle.available_moves[0].id in str(order.message).lower()
    assert recorder.breadcrumbs[-1].decision_source == source


@pytest.mark.asyncio
async def test_hung_turn_times_out_to_the_default_move():
    mock_llm = MagicMock(spec=LLMClient)

    async def _hanging_call(*args, **kwargs):
        await asyncio.sleep(5.0)
        return ActionDecision(action_type="MOVE", target="earthquake")

    mock_llm.generate_cot_decision = _hanging_call
    player = DirectLLMPlayer(player_name="SlowLLM", llm_client=mock_llm, turn_timeout=0.1)
    recorder = BreadcrumbsRecorder("test_match")
    player.set_recorder(recorder)

    order = await player.choose_move(MockBattle())
    assert hasattr(order, "message")
    assert recorder.breadcrumbs[-1].decision_source == "timeout"
