"""Claude's prompt cache breakpoints: the battle log cut into one block per turn, so each turn's cached prefix
reappears at a block boundary of the next turn's prompt."""

from rotomarena.llm.client import cache_marked


def _state(turns):
    log = "\n".join(["Leads:", "- Your Garchomp came in"] + [f"Turn {t}:\n- Garchomp used Earthquake" for t in
                                                             range(1, turns + 1)])
    return (f"#### YOUR POKÉMON AS BUILT:\n- Garchomp\n\n#### BATTLE LOG:\n{log}\n\n"
            f"#### YOUR NOTES FROM EARLIER TURNS (oldest first):\nTurn {turns}: keep attacking\n\n"
            f"### Turn {turns + 1} | Weather: None\n#### LEGAL ACTIONS:\nMOVE: earthquake")


def _marked(turns):
    return cache_marked([{"role": "system", "content": "rules"}, {"role": "user", "content": _state(turns)}])


def test_the_text_is_unchanged_and_the_system_prompt_and_log_are_breakpoints():
    system, user = _marked(3)
    assert system["content"] == [{"type": "text", "text": "rules", "cache_control": {"type": "ephemeral"}}]
    assert "".join(b["text"] for b in user["content"]) == _state(3)
    marked = [b for b in user["content"] if "cache_control" in b]
    assert len(marked) == 1 and marked[0]["text"].startswith("\nTurn 3:")  # the log's last turn
    assert user["content"][-1]["text"].startswith("\n\n#### YOUR NOTES")  # notes and this turn after it


def test_each_turns_cached_prefix_is_a_block_boundary_of_the_next_turn():
    now, later = _marked(3)[1]["content"], _marked(4)[1]["content"]
    cached = now[:next(i for i, b in enumerate(now) if "cache_control" in b) + 1]
    assert [b["text"] for b in later[:len(cached)]] == [b["text"] for b in cached]


def test_messages_without_a_battle_log_only_cache_the_system_prompt():
    system, user = cache_marked([{"role": "system", "content": "rules"}, {"role": "user", "content": "draft a team"}])
    assert user["content"] == "draft a team" and "cache_control" in system["content"][0]
