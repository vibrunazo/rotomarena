"""Tests for telemetry breadcrumb recording, replay export, reports, and series scheduling."""

import json
from rotomarena.matchmaker.runner import series_schedule
from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder, MatchPlayer, MatchTelemetry, TurnBreadcrumb
from rotomarena.telemetry.replay_saver import save_battle_replay_html
from rotomarena.telemetry.reporter import generate_match_markdown_report

PLAYERS = [
    MatchPlayer(role="p2", config_id="nemotron_free", display_name="Nemotron 3 550B", username="Nemotron 3 550B",
                agent_type="direct_llm", provider="openrouter", model="nvidia/nemotron-3-ultra-550b-a55b:free",
                team="Gen9Ou Rain"),
    MatchPlayer(role="p1", config_id="pokechamp", display_name="PokeChamp", username="PokeChamp", agent_type="pokechamp",
                team="Gen9Ou Balance"),
]


def test_breadcrumbs_recorder(tmp_path):
    recorder = BreadcrumbsRecorder("test_match_001", ruleset={"version": "s1", "max_output_tokens": 1024})
    recorder.record_turn(
        TurnBreadcrumb(
            turn=1,
            agent_name="Nemotron 3 550B",
            agent_type="direct_llm",
            decision_source="parse_error",
            legal_actions=["MOVE:earthquake", "SWITCH:kingambit"],
            chosen_action="MOVE:earthquake",
            reasoning="[PARSE ERROR] missing <decision>...</decision> block. Default move played.",
        )
    )

    telemetry = recorder.finalize(players=PLAYERS, winner="PokeChamp", total_turns=1, duration_sec=2.5)
    assert [p.role for p in telemetry.players] == ["p1", "p2"]
    assert telemetry.player("p2").config_id == "nemotron_free"

    out_file = tmp_path / "breadcrumbs.json"
    telemetry.save_json(out_file)
    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert loaded["ruleset"]["version"] == "s1"
    assert loaded["players"][1]["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert loaded["breadcrumbs"][0]["decision_source"] == "parse_error"


def test_save_battle_replay_html_escapes_the_inlined_log(tmp_path):
    out_html = tmp_path / "replay.html"
    raw_logs = [
        "|player|p1|PokeChamp|1",
        "|player|p2|<b>Nemotron</b>|2",
        "|turn|1",
        "|move|p1a: Great Tusk|Earthquake|p2a: Heatran",
        "|c|PokeChamp|</script><script>alert(1)</script>",
        "|win|PokeChamp",
    ]
    save_battle_replay_html(
        match_id="test_001",
        player_1="PokeChamp",
        player_2="<b>Nemotron</b>",
        winner="PokeChamp",
        total_turns=1,
        duration_seconds=1.5,
        raw_logs=raw_logs,
        output_path=out_html,
    )
    content = out_html.read_text(encoding="utf-8")
    assert "RotomArena Battle Replay" in content
    assert "Earthquake" in content
    assert "<\\/script><script>alert(1)<\\/script>" in content  # Showdown's \/ escaping inside the log
    assert content.count("</script>") == 3  # only the template's own script blocks close
    assert "&lt;b&gt;Nemotron&lt;/b&gt;" in content  # names are HTML-escaped


def test_generate_match_markdown_report(tmp_path):
    out_md = tmp_path / "report.md"
    telemetry = MatchTelemetry(
        match_id="match_test",
        ruleset={"version": "s1"},
        players=PLAYERS[::-1],
        winner="PokeChamp",
        total_turns=5,
        duration_seconds=8.2,
        breadcrumbs=[
            TurnBreadcrumb(turn=1, agent_name="PokeChamp", agent_type="pokechamp", chosen_action="MOVE:earthquake"),
            TurnBreadcrumb(turn=1, agent_name="Nemotron 3 550B", agent_type="direct_llm",
                           decision_source="api_error", chosen_action="MOVE:surf"),
        ],
    )
    generate_match_markdown_report(telemetry, out_md)
    report_text = out_md.read_text(encoding="utf-8")
    assert "RotomArena Match Report" in report_text
    assert "[nemotron_free" in report_text
    assert "| **Autopilot Turns** (fallback picked the move) | 0 | 1 |" in report_text
    assert "AUTOPILOT (api_error)" in report_text


def test_series_schedule_covers_both_sides_and_both_team_assignments():
    assert series_schedule(4) == [(False, False), (False, True), (True, False), (True, True)]
    assert series_schedule(6)[4:] == series_schedule(2)


def test_each_decision_is_written_live_for_its_battle(tmp_path):
    import json

    from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder, TurnBreadcrumb

    live = tmp_path / "live"
    live.mkdir()
    (live / "battle-gen9ou-7.jsonl").write_text('{"stale": true}\n')  # an old battle with the same tag
    recorder = BreadcrumbsRecorder("m", live_dir=live)
    for turn, who in ((1, "A"), (1, "B")):
        recorder.record_turn(TurnBreadcrumb(turn=turn, agent_name=who, agent_type="direct_llm", reasoning=f"{who} thinks",
                                            chosen_action="/choose move tackle", timestamp="t",
                                            llm_metrics={"latency_ms": 2500, "reasoning_tokens": 300}), "battle-gen9ou-7")
    rows = [json.loads(l) for l in (live / "battle-gen9ou-7.jsonl").read_text().splitlines()]
    assert [r["player"] for r in rows] == ["A", "B"] and rows[0]["thought"] == "A thinks" and rows[0]["seconds"] == 2.5


def test_a_decision_models_probabilities_are_kept_and_written_live(tmp_path):
    import json

    from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder, TurnBreadcrumb

    recorder = BreadcrumbsRecorder("m", live_dir=tmp_path)
    probs = {"MOVE: earthquake": 0.62, "SWITCH: corviknight": 0.38}
    recorder.record_turn(TurnBreadcrumb(turn=3, agent_name="Jev", agent_type="decision", chosen_action="/choose move earthquake",
                                        timestamp="t", probabilities=probs), "battle-gen9ou-9")
    assert recorder.breadcrumbs[0].probabilities == probs
    assert json.loads((tmp_path / "battle-gen9ou-9.jsonl").read_text())["probabilities"] == probs
