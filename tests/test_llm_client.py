"""Tests for LLM Client parsing, provider settings, and prompt formatting."""

import asyncio

import openai
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from rotomarena.config import provider_presets
from rotomarena.llm.client import Completion, LLMClient, ProviderLimitError, parse_decision
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
        ("LEAD: Great Tusk", "LEAD", "greattusk"),
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
        ("<decision>Earthquake, obviously.</decision>", "no MOVE, SWITCH or LEAD line"),
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
        mock_comp.return_value = Completion("<thought>Let me think about every possible line of play", "", metrics)
        decision = await client.generate_cot_decision("dummy state", max_tokens=1024)
    assert "cut off at the 1024-token budget" in decision.parse_error
    assert decision.metrics.finish_reason == "length"


@pytest.mark.asyncio
async def test_response_without_choices_is_retried(monkeypatch):
    client = LLMClient.from_provider_name("openrouter")
    monkeypatch.setattr("rotomarena.llm.client.asyncio.sleep", AsyncMock())
    error_body = SimpleNamespace(choices=None, error={"message": "Provider returned error", "code": 502})
    good = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            content="<decision>MOVE: surf</decision>", reasoning="Surf hits Heatran super effectively."))],
        usage=SimpleNamespace(prompt_tokens=1800, completion_tokens=900, total_tokens=2700,
                              completion_tokens_details=SimpleNamespace(reasoning_tokens=850), cost=0.0042),
    )
    create = AsyncMock(side_effect=[error_body, good])
    monkeypatch.setattr(client._client.chat.completions, "create", create)

    completion = await client.generate_completion([{"role": "user", "content": "hi"}])
    assert completion.text == "<decision>MOVE: surf</decision>"
    assert completion.reasoning == "Surf hits Heatran super effectively."  # OpenRouter's hidden reasoning field
    assert completion.metrics.cost_usd == 0.0042 and completion.metrics.reasoning_tokens == 850
    assert create.await_count == 2


def _status_error(code: int, message: str) -> openai.APIStatusError:
    response = SimpleNamespace(status_code=code, headers={}, request=None)  # all the SDK reads from it
    return openai.APIStatusError(message, response=response, body=None)


_GOOD = SimpleNamespace(
    choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="<decision>MOVE: surf</decision>"))],
    usage=None,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    _status_error(402, "Insufficient credits"),
    _status_error(429, "Rate limit exceeded: free-models-per-day"),
    SimpleNamespace(choices=None, error={"message": "Rate limit exceeded: free-models-per-day", "code": 429}),
])
async def test_credit_and_quota_limits_stop_at_once(monkeypatch, failure):
    client = LLMClient.from_provider_name("openrouter")
    sleep = AsyncMock()
    monkeypatch.setattr("rotomarena.llm.client.asyncio.sleep", sleep)
    create = AsyncMock(side_effect=failure if isinstance(failure, Exception) else [failure])
    monkeypatch.setattr(client._client.chat.completions, "create", create)

    with pytest.raises(ProviderLimitError):
        await client.generate_completion([{"role": "user", "content": "hi"}])
    assert create.await_count == 1 and sleep.await_count == 0


@pytest.mark.asyncio
async def test_rate_limits_back_off_then_give_up(monkeypatch):
    client = LLMClient.from_provider_name("openrouter")
    sleep = AsyncMock()
    monkeypatch.setattr("rotomarena.llm.client.asyncio.sleep", sleep)
    limited = _status_error(429, "Rate limit exceeded")

    create = AsyncMock(side_effect=[limited, limited, _GOOD])
    monkeypatch.setattr(client._client.chat.completions, "create", create)
    completion = await client.generate_completion([{"role": "user", "content": "hi"}], max_retries=1)
    assert completion.text == "<decision>MOVE: surf</decision>"  # 429s don't use up the server-error retries

    # Google's per-minute token limit says "quota" too, but clears: back off, don't stop
    per_minute = _status_error(429, "You exceeded your current quota. Quota exceeded for metric: "
                                    "generate_content_paid_tier_input_token_count, limit: 16000")
    create = AsyncMock(side_effect=[per_minute, _GOOD])
    monkeypatch.setattr(client._client.chat.completions, "create", create)
    assert (await client.generate_completion([{"role": "user", "content": "hi"}])).text

    create = AsyncMock(side_effect=limited)
    monkeypatch.setattr(client._client.chat.completions, "create", create)
    with pytest.raises(ProviderLimitError, match="still rate limited"):
        await client.generate_completion([{"role": "user", "content": "hi"}])
    assert create.await_count == 7  # the first try and six backed-off retries


@pytest.mark.asyncio
async def test_answer_filed_under_reasoning_is_recovered():
    """llama.cpp didn't know K2-Horizon's end-of-thinking tag and returned its whole output as reasoning."""
    client = LLMClient.from_provider_name("local")
    hidden = ("Heatran is Fire/Steel, Ground is 4x. So choose MOVE: earthquake.\n</ifm|think>\n"
              "<thought>\nEarthquake KOs Heatran.\n</thought>\n<decision>\nMOVE: earthquake\n</decision>")
    with patch.object(client, "generate_completion", new_callable=AsyncMock) as mock_comp:
        mock_comp.return_value = Completion("", hidden, LLMUsageMetrics(finish_reason="stop"))
        decision = await client.generate_cot_decision("dummy state")
    assert decision.parse_error is None
    assert (decision.action_type, decision.target) == ("MOVE", "earthquake")
    assert decision.reasoning == "Earthquake KOs Heatran."
    assert decision.hidden_reasoning.endswith("</ifm|think>")


def test_reasoning_settings_per_provider_style():
    presets = provider_presets()
    openrouter = LLMClient(presets["openrouter"], "openrouter")
    local = LLMClient(presets["local"], "local")
    gemini = LLMClient(presets["gemini"], "gemini")

    assert openrouter._reasoning_kwargs("off") == {"extra_body": {"reasoning": {"enabled": False}, "usage": {"include": True}}}
    assert openrouter._reasoning_kwargs("medium") == {"extra_body": {"reasoning": {"effort": "medium"}, "usage": {"include": True}}}
    assert local._reasoning_kwargs("off") == {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False, "reasoning_effort": "low"}}
    }
    assert gemini._reasoning_kwargs("off") == {}
    assert gemini._reasoning_kwargs("medium") == {"reasoning_effort": "medium"}


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        LLMClient.from_provider_name("openruoter")


@pytest.mark.asyncio
async def test_local_gate_batches_one_model_and_takes_turns_between_models():
    from rotomarena.llm.client import _local_gate

    gate, events = _local_gate(), []

    async def request(port: int, name: str, hold: float):
        async with gate.use(port):
            events.append(("start", name))
            await asyncio.sleep(hold)
            events.append(("end", name))

    first = asyncio.create_task(request(8081, "qwen-1", 0.05))
    await asyncio.sleep(0)
    others = [asyncio.create_task(request(8081, "qwen-2", 0.05)),  # joins the batch already running
              asyncio.create_task(request(8080, "bonsai-1", 0.01)),  # waits for qwen's batch
              asyncio.create_task(request(8081, "qwen-3", 0.01))]  # arrived after bonsai: waits its turn
    await asyncio.gather(first, *others)

    starts = [name for kind, name in events if kind == "start"]
    assert starts == ["qwen-1", "qwen-2", "bonsai-1", "qwen-3"]
    assert events.index(("start", "qwen-2")) < events.index(("end", "qwen-1"))  # overlapped
    assert events.index(("start", "bonsai-1")) > events.index(("end", "qwen-2"))  # never two models at once
    assert events.index(("start", "qwen-3")) > events.index(("end", "bonsai-1"))


@pytest.mark.asyncio
async def test_local_gate_batches_interleaved_requests_from_parallel_games():
    from rotomarena.llm.client import _LocalGate

    gate, events = _LocalGate(), []

    async def request(port: int, name: str, hold: float):
        async with gate.use(port):
            events.append(("start", name))
            await asyncio.sleep(hold)
            events.append(("end", name))

    first = asyncio.create_task(request(8081, "qwen-1", 0.05))
    await asyncio.sleep(0)
    others = [asyncio.create_task(request(8084, "ornith-1", 0.02)), asyncio.create_task(request(8081, "qwen-2", 0.02)),
              asyncio.create_task(request(8084, "ornith-2", 0.02))]
    await asyncio.gather(first, *others)

    starts = [name for kind, name in events if kind == "start"]
    assert starts == ["qwen-1", "ornith-1", "ornith-2", "qwen-2"]  # one batch per model, not four swaps
    assert events.index(("start", "ornith-2")) < events.index(("end", "ornith-1"))  # batched together
