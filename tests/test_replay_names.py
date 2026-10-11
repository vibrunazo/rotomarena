"""Replays show display names, not Showdown usernames with lane numbers."""

from rotomarena.config import AgentConfig, AppConfig
from rotomarena.replay_names import live_names, rename_players, shown_names


def test_lane_usernames_become_display_names():
    app_cfg = AppConfig(agents={
        "opus": AgentConfig(name="opus", type="direct_llm", display_name="Claude Opus 5.5", battle_name="Opus 5.5",
                            model="anthropic/claude-opus-5.5"),
        "luna": AgentConfig(name="luna", type="direct_llm", display_name="GPT-6 Luna", model="openai/gpt-6-luna"),
    })
    names = live_names(["Opus 5.5 2", "GPT-6 Luna 3"], app_cfg)
    assert names == {"Opus 5.5 2": "Claude Opus 5.5", "GPT-6 Luna 3": "GPT-6 Luna"}
    log = rename_players(["|player|p1|Opus 5.5 2|1|", "|j|☆GPT-6 Luna 3", "|move|p1a: Garchomp|Earthquake|p2a: Rotom",
                          "|-message|GPT-6 Luna 3 forfeited.", "|win|Opus 5.5 2"], names)
    assert log == ["|player|p1|Claude Opus 5.5|1|", "|j|☆GPT-6 Luna", "|move|p1a: Garchomp|Earthquake|p2a: Rotom",
                   "|-message|GPT-6 Luna forfeited.", "|win|Claude Opus 5.5"]


def test_a_mirror_match_keeps_its_numbered_usernames():
    assert shown_names({"Opus 5.5 1": "Claude Opus 5.5", "Opus 5.5 2": "Claude Opus 5.5"}) == {}
