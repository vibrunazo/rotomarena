"""Tests for Agent implementations and decision handling."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from rotomarena.agents.heuristic import MaxDamagePlayer, HeuristicPlayer
from rotomarena.agents.direct_llm import DirectLLMPlayer
from rotomarena.llm.client import LLMClient, ProviderLimitError
from rotomarena.llm.schemas import ActionDecision, LLMUsageMetrics
from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder
from .mocks import MockBattle


@pytest.mark.asyncio
async def test_heuristic_player_choice():
    player = HeuristicPlayer(player_name="TestHeuristic", start_listening=False)
    battle = MockBattle()
    order = await player.choose_move(battle)
    assert order is not None
    # Great Tusk against Heatran should select Earthquake
    assert "earthquake" in str(order.message).lower()


@pytest.mark.asyncio
async def test_max_damage_player_choice():
    player = MaxDamagePlayer(player_name="TestMaxDmg", start_listening=False)
    battle = MockBattle()
    order = await player.choose_move(battle)
    assert order is not None
    assert "earthquake" in str(order.message).lower()


def _llm_player(decision=None, side_effect=None):
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.generate_cot_decision = AsyncMock(return_value=decision, side_effect=side_effect)
    player = DirectLLMPlayer(player_name="TestLLM", llm_client=mock_llm, start_listening=False)
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
async def test_provider_limit_puts_the_rest_of_the_game_on_autopilot():
    player, recorder = _llm_player(None, ProviderLimitError("openrouter: HTTP 402: Insufficient credits"))
    for _ in range(3):
        await player._async_choose_move(MockBattle())
    assert isinstance(player.provider_limit, ProviderLimitError)
    assert player.llm_client.generate_cot_decision.await_count == 1  # later turns don't call the API
    assert [c.decision_source for c in recorder.breadcrumbs] == ["api_error"] * 3


@pytest.mark.asyncio
async def test_hung_turn_times_out_to_the_default_move():
    mock_llm = MagicMock(spec=LLMClient)

    async def _hanging_call(*args, **kwargs):
        await asyncio.sleep(5.0)
        return ActionDecision(action_type="MOVE", target="earthquake")

    mock_llm.generate_cot_decision = _hanging_call
    player = DirectLLMPlayer(player_name="SlowLLM", llm_client=mock_llm, turn_timeout=0.1, start_listening=False)
    recorder = BreadcrumbsRecorder("test_match")
    player.set_recorder(recorder)

    order = await player.choose_move(MockBattle())
    assert hasattr(order, "message")
    assert recorder.breadcrumbs[-1].decision_source == "timeout"


@pytest.mark.asyncio
async def test_model_picks_its_lead_and_the_rest_keep_their_order():
    player, recorder = _llm_player(ActionDecision(action_type="LEAD", target="kingambit", reasoning="Kingambit walls Heatran."))
    battle = MockBattle()
    battle.teampreview_opponent_team = [battle.opponent_active_pokemon]
    assert await player.teampreview(battle) == "/team 21"
    crumb = recorder.breadcrumbs[-1]
    assert crumb.decision_source == "model" and crumb.chosen_action == "/team 21 lead=kingambit"
    prompt = player.llm_client.generate_cot_decision.call_args.kwargs["battle_state_str"]
    assert "LEAD: greattusk" in prompt and "heatran" in prompt


@pytest.mark.asyncio
async def test_bad_lead_falls_back_to_team_order():
    player, recorder = _llm_player(ActionDecision(action_type="LEAD", target="pikachu"))
    battle = MockBattle()
    assert await player.teampreview(battle) == "/team 12"
    assert recorder.breadcrumbs[-1].decision_source == "invalid"


@pytest.mark.asyncio
async def test_lead_during_a_turn_is_invalid():
    player, recorder = _llm_player(ActionDecision(action_type="LEAD", target="kingambit"))
    battle = MockBattle()
    order = await player._async_choose_move(battle)
    assert battle.available_moves[0].id in str(order.message).lower()
    assert recorder.breadcrumbs[-1].decision_source == "invalid"


@pytest.mark.asyncio
async def test_team_member_named_with_the_wrong_keyword_still_leads():
    player, recorder = _llm_player(ActionDecision(action_type="MOVE", target="kingambit"))
    assert await player.teampreview(MockBattle()) == "/team 21"
    assert recorder.breadcrumbs[-1].decision_source == "model"


def test_a_bring_n_format_sends_only_the_chosen_pokemon_in_order():
    from types import SimpleNamespace

    from rotomarena.agents.base import BaseBenchmarkPlayer

    battle = SimpleNamespace(team={f"p1: Mon{i}": SimpleNamespace() for i in range(6)})
    bring3 = SimpleNamespace(pick=3)
    assert BaseBenchmarkPlayer.bring_order(bring3, battle, [5, 2, 3]) == "/team 634"
    assert BaseBenchmarkPlayer.bring_order(bring3, battle, [4]) == "/team 512"  # missing picks follow the team order
    assert BaseBenchmarkPlayer.bring_order(SimpleNamespace(pick=None), battle, [2]) == "/team 312456"


def test_the_battle_prompt_names_the_format_and_keeps_gen9ou_unchanged():
    from rotomarena.llm.prompts import SYSTEM_PROMPT_DIRECT_COT, system_prompt_for

    assert system_prompt_for("gen9ou") is SYSTEM_PROMPT_DIRECT_COT
    champions = system_prompt_for("gen9championsrotomarenarandombss", pick=3)
    assert "Pokémon Champions singles" in champions and "BRING: <3 species" in champions and "Gen 9 OU" not in champions
