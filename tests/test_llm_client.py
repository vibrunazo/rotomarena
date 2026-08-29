"""Tests for LLM Client parsing, prompt formatting, and schemas."""

import pytest
from unittest.mock import AsyncMock, patch
from rotomarena.config import ProviderConfig
from rotomarena.llm.client import LLMClient
from rotomarena.llm.schemas import ActionDecision, LLMUsageMetrics, StateEvaluation
from rotomarena.llm.prompts import format_battle_state
from .mocks import MockBattle


def test_format_battle_state():
    battle = MockBattle()
    state_str = format_battle_state(battle)
    assert "YOUR TEAM:" in state_str
    assert "greattusk" in state_str.lower()
    assert "OPPONENT TEAM:" in state_str
    assert "heatran" in state_str.lower()
    assert "LEGAL ACTIONS THIS TURN:" in state_str
    assert "earthquake" in state_str.lower()


@pytest.mark.asyncio
async def test_llm_client_decision_parsing():
    client = LLMClient.from_provider_name("gemini")
    
    mock_cot_output = """
    <thought>
    Heatran is 4x weak to Ground moves. Great Tusk outspeeds and has STAB Earthquake.
    </thought>
    <decision>
    ACTION: MOVE: earthquake [TERA]
    </decision>
    """

    metrics = LLMUsageMetrics(
        prompt_tokens=50,
        completion_tokens=30,
        total_tokens=80,
        latency_ms=100.0,
        model="gemini-2.5-flash",
        provider="gemini",
    )

    with patch.object(client, "generate_completion", new_callable=AsyncMock) as mock_comp:
        mock_comp.return_value = (mock_cot_output, metrics)
        
        decision = await client.generate_cot_decision("dummy state")
        assert decision.action_type == "MOVE"
        assert decision.target == "earthquake"
        assert decision.terastallize is True
        assert "Heatran is 4x weak" in decision.reasoning


@pytest.mark.asyncio
async def test_llm_client_value_evaluation_parsing():
    client = LLMClient.from_provider_name("gemini")
    mock_eval_output = """```json
    {
      "score": 0.65,
      "win_probability": 0.82,
      "explanation": "Great Tusk dominates the active matchup with entry hazards in our favor."
    }
    ```"""

    metrics = LLMUsageMetrics(
        prompt_tokens=40,
        completion_tokens=20,
        total_tokens=60,
        latency_ms=80.0,
        model="gemini-2.5-flash",
        provider="gemini",
    )

    with patch.object(client, "generate_completion", new_callable=AsyncMock) as mock_comp:
        mock_comp.return_value = (mock_eval_output, metrics)
        
        evaluation = await client.evaluate_state("dummy state")
        assert evaluation.score == 0.65
        assert evaluation.win_probability == 0.82
        assert "dominates the active matchup" in evaluation.explanation
