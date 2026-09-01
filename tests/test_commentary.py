"""Tests for play-by-play battle commentary generation and TTS replay embedding."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from rotomarena.commentary.generator import (
    BattleCommentary,
    CommentaryGenerator,
    TurnCommentary,
)
from rotomarena.telemetry.replay_saver import save_battle_replay_html


def test_commentary_data_models():
    turns = [
        TurnCommentary(turn=0, title="Opening Leads", commentary="Welcome to the match!"),
        TurnCommentary(turn=1, title="Turn 1", commentary="Great Tusk lands a massive Earthquake!"),
    ]
    battle_comm = BattleCommentary(
        match_id="test_match_001",
        format="gen9ou",
        p1_name="P1_Bot",
        p2_name="P2_Bot",
        winner="P1_Bot",
        total_turns=1,
        turns=turns,
    )

    assert battle_comm.get_turn(1) is not None
    assert battle_comm.get_turn(1).commentary == "Great Tusk lands a massive Earthquake!"
    assert battle_comm.get_turn(99) is None

    # Test serialization
    data = json.loads(battle_comm.model_dump_json())
    assert data["match_id"] == "test_match_001"
    assert len(data["turns"]) == 2


def test_parse_turn_events():
    generator = CommentaryGenerator()
    raw_logs = [
        "|init|battle",
        "|player|p1|Player One|1",
        "|player|p2|Player Two|2",
        "|switch|p1a: Great Tusk|Great Tusk|100/100",
        "|switch|p2a: Heatran|Heatran|100/100",
        "|turn|1",
        "|move|p1a: Great Tusk|Earthquake|p2a: Heatran",
        "|-damage|p2a: Heatran|0 fnt",
        "|faint|p2a: Heatran",
        "|win|Player One",
    ]

    events = generator.parse_turn_events(raw_logs)
    assert 0 in events
    assert 1 in events
    assert any("Player 1 sent out Great Tusk" in ev for ev in events[0])
    assert any("Earthquake" in ev for ev in events[1])
    assert any("FAINTED" in ev for ev in events[1])


@pytest.mark.asyncio
async def test_generate_commentary_with_mock_llm():
    mock_client = MagicMock()
    mock_client.generate_text = AsyncMock(
        return_value=json.dumps(
            {
                "turns": [
                    {
                        "turn": 0,
                        "title": "Opening Leads",
                        "commentary": "Great Tusk faces off against Heatran in a classic Gen 9 OU matchup!",
                    },
                    {
                        "turn": 1,
                        "title": "Turn 1: Decisive Earthquake",
                        "commentary": "Great Tusk drops the hammer with Earthquake, knocking Heatran out in a single blow!",
                    },
                ]
            }
        )
    )

    generator = CommentaryGenerator(llm_client=mock_client)
    raw_logs = [
        "|turn|1",
        "|move|p1a: Great Tusk|Earthquake|p2a: Heatran",
        "|-damage|p2a: Heatran|0 fnt",
        "|faint|p2a: Heatran",
        "|win|Player One",
    ]

    comm = await generator.generate_commentary(
        raw_logs=raw_logs,
        p1_name="Player One",
        p2_name="Player Two",
        match_id="test_mock_match",
        winner="Player One",
        total_turns=1,
    )

    assert comm.match_id == "test_mock_match"
    assert len(comm.turns) == 2
    assert "Earthquake" in comm.get_turn(1).commentary


def test_embed_commentary_into_replay_html(tmp_path):
    out_html = tmp_path / "replay.html"
    raw_logs = ["|turn|1", "|move|p1a: mon1|Tackle|p2a: mon2", "|win|P1"]
    
    comm = BattleCommentary(
        match_id="test_embed",
        p1_name="P1",
        p2_name="P2",
        winner="P1",
        total_turns=1,
        turns=[
            TurnCommentary(turn=0, title="Intro", commentary="Match intro test."),
            TurnCommentary(turn=1, title="Turn 1", commentary="Tackle lands for the win!"),
        ],
    )

    save_battle_replay_html(
        match_id="test_embed",
        player_1="P1",
        player_2="P2",
        winner="P1",
        total_turns=1,
        duration_seconds=3.0,
        raw_logs=raw_logs,
        output_path=out_html,
        commentary=comm,
    )

    assert out_html.exists()
    content = out_html.read_text(encoding="utf-8")
    assert "rotomarena-commentary-data" in content
    assert "Tackle lands for the win!" in content
    assert "Play-by-Play Esports Commentary &amp; TTS Caster" in content or "Play-by-Play Esports Commentary & TTS Caster" in content
    assert "window.speechSynthesis" in content
