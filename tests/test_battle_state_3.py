"""Battle state 3 (c5): the plainly stated prompt, notes as the model's memory, the cache-friendly order."""

from rotomarena.llm.client import parse_decision
from rotomarena.llm.prompts import format_battle_state, system_prompt_for, user_template_for

from .mocks import MockBattle

CHAMPIONS = "gen9championsrotomarenabssregmb"


def test_the_c5_system_prompt_states_the_task_and_the_answer_format():
    prompt = system_prompt_for(CHAMPIONS, pick=3, attempts=2, state=3)
    assert "singles" in prompt and "level 50" in prompt and "[MEGA]" in prompt
    assert "ANSWER IN EXACTLY THIS FORM" in prompt and "<notes>" in prompt
    assert "grandmaster" not in prompt  # no persona
    assert "<notes>" in user_template_for(3) and "<notes>" not in user_template_for(2)
    # earlier versions keep their prompt exactly
    assert "grandmaster" in system_prompt_for(CHAMPIONS, pick=3, attempts=2, state=2)


def test_notes_are_read_as_the_thought():
    decision = parse_decision("<notes>Plan: sweep with Garchomp.</notes>\n<decision>MOVE: earthquake</decision>")
    assert decision.reasoning == "Plan: sweep with Garchomp." and decision.target == "earthquake"


def test_the_state_goes_from_what_never_changes_to_this_turn_and_shows_the_latest_notes():
    battle = MockBattle()
    battle._replay_data = [["", "turn", "1"], ["", "move", "p1a: Great Tusk", "Earthquake", "p2a: Heatran"]]
    battle.player_role = "p1"
    battle.teampreview_opponent_team = []
    notes = {0: "lead plan", 1: "turn one", 2: "turn two", 3: "turn three"}
    state = format_battle_state(battle, None, None, 3, notes, notes_shown=3)
    order = [state.index(h) for h in ("YOUR POKÉMON IN THIS BATTLE", "BATTLE LOG", "YOUR NOTES FROM EARLIER TURNS",
                                      "YOUR POKÉMON NOW", "LEGAL ACTIONS THIS TURN")]
    assert order == sorted(order)
    assert "turn one" in state and "turn three" in state and "lead plan" not in state  # the latest 3
