"""Tests for LLM Client parsing, provider settings, and prompt formatting."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from rotomarena.config import provider_presets
from rotomarena.llm.client import LLMClient, parse_decision
from rotomarena.llm.schemas import LLMUsageMetrics
from rotomarena.llm.prompts import format_battle_state, format_recent_turns
from .mocks import MockBattle


def test_format_battle_state():
    battle = MockBattle()
    state_str = format_battle_state(battle)
    assert "YOUR BENCH:" in state_str and "YOUR ACTIVE POKÉMON:" in state_str
    assert "greattusk" in state_str.lower()
    assert "OPPONENT'S ACTIVE POKÉMON:" in state_str
    # the benches, which rarely change, come before the turn-specific sections
    assert state_str.index("YOUR BENCH:") < state_str.index("### Turn") < state_str.index("LEGAL ACTIONS")
    assert "heatran" in state_str.lower()
    assert "LEGAL ACTIONS THIS TURN:" in state_str
    assert "earthquake" in state_str.lower()
    assert "Weather: None" in state_str


def test_recent_turns_are_grouped_and_seen_from_our_side():
    battle = MockBattle()
    battle.player_role = "p1"
    battle.turn = 5
    battle._replay_data = [
        ["", "switch", "p1a: Great Tusk", "Great Tusk, L100", "100/100"],
        ["", "turn", "1"],
        ["", "move", "p1a: Great Tusk", "Headlong Rush", "p2a: Heatran"],
        ["", "turn", "2"],
        ["", "switch", "p2a: Corviknight", "Corviknight, L100", "100/100"],
        ["", "turn", "3"],
        ["", "switch", "p2a: Heatran", "Heatran, L100", "70/100"],
        ["", "turn", "4"],
        ["", "move", "p2a: Heatran", "Magma Storm", "p1a: Great Tusk"],
        ["", "-supereffective", "p1a: Great Tusk"],
        ["", "-sidestart", "p1: Bot", "move: Stealth Rock"],
        ["", "turn", "5"],
    ]
    assert format_recent_turns(battle) == [
        "Turn 2:", "- Opposing Corviknight came in",
        "Turn 3:", "- Opposing Heatran came in",
        "Turn 4:", "- Opposing Heatran used Magma Storm", "- It was super effective",
        "- Stealth Rock set on your side",
    ]


def test_parse_decision_reads_thought_move_and_tera_tag():
    decision = parse_decision(
        "<thought>Heatran is 4x weak to Ground.</thought>\n<decision>\nACTION: MOVE: earthquake [TERA]\n</decision>"
    )
    assert decision.parse_error is None
    assert decision.action_type == "MOVE"
    assert decision.target == "earthquake"
    assert decision.terastallize is True
    assert decision.reasoning == "Heatran is 4x weak to Ground."


@pytest.mark.parametrize(
    "decision_block, kind, target",
    [
        ("MOVE: earthquake (Type: Ground, BP: 100, Acc: 100)", "MOVE", "earthquake"),
        ("3. SWITCH: landorustherian (89.5% HP)", "SWITCH", "landorustherian"),
        ("**SWITCH:** Landorus-Therian", "SWITCH", "landorustherian"),
        ("- MOVE: U-turn", "MOVE", "uturn"),
    ],
)
def test_parse_decision_normalizes_targets_to_showdown_ids(decision_block, kind, target):
    decision = parse_decision(f"<decision>{decision_block}</decision>")
    assert decision.parse_error is None
    assert (decision.action_type, decision.target) == (kind, target)


def test_tera_blast_does_not_terastallize_without_the_tag():
    decision = parse_decision("<decision>MOVE: terablast</decision>")
    assert decision.target == "terablast"
    assert decision.terastallize is False


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("I will use Earthquake because it is super effective.", "missing <decision>"),
        ("<decision>Earthquake, obviously.</decision>", "no MOVE or SWITCH line"),
        ("<decision>MOVE: earthquake\nMOVE: closecombat</decision>", "exactly one is allowed"),
        ("<decision>MOVE: [TERA]</decision>", "empty action target"),
    ],
)
def test_parse_decision_rejects_unusable_answers(raw, reason):
    decision = parse_decision(raw)
    assert decision.action_type is None
    assert reason in decision.parse_error


@pytest.mark.asyncio
async def test_cut_off_answer_reports_the_token_budget():
    client = LLMClient.from_provider_name("openrouter")
    metrics = LLMUsageMetrics(completion_tokens=1024, finish_reason="length")
    with patch.object(client, "generate_completion", new_callable=AsyncMock) as mock_comp:
        mock_comp.return_value = ("<thought>Let me think about every possible line of play", metrics)
        decision = await client.generate_cot_decision("dummy state", max_tokens=1024)
    assert "cut off at the 1024-token budget" in decision.parse_error
    assert decision.metrics.finish_reason == "length"


@pytest.mark.asyncio
async def test_response_without_choices_is_retried(monkeypatch):
    client = LLMClient.from_provider_name("openrouter")
    monkeypatch.setattr("rotomarena.llm.client.asyncio.sleep", AsyncMock())
    error_body = SimpleNamespace(choices=None, error={"message": "Provider returned error", "code": 502})
    good = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="<decision>MOVE: surf</decision>"))],
        usage=None,
    )
    create = AsyncMock(side_effect=[error_body, good])
    monkeypatch.setattr(client._client.chat.completions, "create", create)

    text, metrics = await client.generate_completion([{"role": "user", "content": "hi"}])
    assert text == "<decision>MOVE: surf</decision>"
    assert create.await_count == 2


def test_reasoning_settings_per_provider_style():
    presets = provider_presets()
    openrouter = LLMClient(presets["openrouter"], "openrouter")
    local = LLMClient(presets["local"], "local")
    gemini = LLMClient(presets["gemini"], "gemini")

    assert openrouter._reasoning_kwargs("off") == {"extra_body": {"reasoning": {"enabled": False}}}
    assert openrouter._reasoning_kwargs("high") == {"extra_body": {"reasoning": {"effort": "high"}}}
    assert local._reasoning_kwargs("off") == {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False, "reasoning_effort": "low"}}
    }
    assert gemini._reasoning_kwargs("off") == {}
    assert gemini._reasoning_kwargs("medium") == {"reasoning_effort": "medium"}


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        LLMClient.from_provider_name("openruoter")
