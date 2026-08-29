"""Tests for telemetry breadcrumb recording, replay export, and reports."""

import json
import pytest
from pathlib import Path
from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder, TurnBreadcrumb, MatchTelemetry
from rotomarena.telemetry.replay_saver import save_battle_replay_html, save_battle_raw_json
from rotomarena.telemetry.reporter import generate_match_markdown_report


def test_breadcrumbs_recorder(tmp_path):
    recorder = BreadcrumbsRecorder("test_match_001", "P1_PokeChamp", "P2_DirectLLM")
    recorder.record_turn(
        TurnBreadcrumb(
            turn=1,
            agent_name="P1_PokeChamp",
            agent_type="pokechamp",
            active_pokemon="Great Tusk",
            active_hp_pct=100.0,
            opponent_active="Heatran",
            opponent_hp_pct=100.0,
            legal_actions=["MOVE:earthquake", "SWITCH:Kingambit"],
            chosen_action="MOVE:earthquake",
            reasoning="Earthquake is 4x super effective.",
        )
    )

    telemetry = recorder.finalize(winner="P1_PokeChamp", total_turns=1, duration_sec=2.5)
    assert telemetry.winner == "P1_PokeChamp"
    assert len(telemetry.breadcrumbs) == 1

    out_file = tmp_path / "breadcrumbs.json"
    telemetry.save_json(out_file)
    assert out_file.exists()

    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert loaded["match_id"] == "test_match_001"
    assert loaded["breadcrumbs"][0]["chosen_action"] == "MOVE:earthquake"


def test_save_battle_replay_html(tmp_path):
    out_html = tmp_path / "replay.html"
    raw_logs = [
        "|gametype|singles",
        "|player|p1|P1_PokeChamp|1",
        "|player|p2|P2_DirectLLM|2",
        "|turn|1",
        "|move|p1a: Great Tusk|Earthquake|p2a: Heatran",
        "|-damage|p2a: Heatran|0 fnt",
        "|faint|p2a: Heatran",
        "|win|P1_PokeChamp",
    ]

    save_battle_replay_html(
        match_id="test_001",
        player_1="P1_PokeChamp",
        player_2="P2_DirectLLM",
        winner="P1_PokeChamp",
        total_turns=1,
        duration_seconds=1.5,
        raw_logs=raw_logs,
        output_path=out_html,
    )
    assert out_html.exists()
    content = out_html.read_text(encoding="utf-8")
    assert "RotomArena Battle Replay" in content
    assert "P1_PokeChamp" in content
    assert "Earthquake" in content


def test_generate_match_markdown_report(tmp_path):
    out_md = tmp_path / "report.md"
    telemetry = MatchTelemetry(
        match_id="match_test",
        format="gen9ou",
        player_1="PokeChamp_d1",
        player_2="Baseline_Heuristic",
        winner="PokeChamp_d1",
        total_turns=5,
        duration_seconds=8.2,
        breadcrumbs=[
            TurnBreadcrumb(
                turn=1,
                agent_name="PokeChamp_d1",
                agent_type="pokechamp",
                active_pokemon="Great Tusk",
                chosen_action="MOVE:earthquake",
                reasoning="Calculated highest EV score.",
            )
        ],
    )
    generate_match_markdown_report(telemetry, out_md)
    assert out_md.exists()
    report_text = out_md.read_text(encoding="utf-8")
    assert "RotomArena Match Report" in report_text
    assert "PokeChamp_d1" in report_text
    assert "MOVE:earthquake" in report_text
