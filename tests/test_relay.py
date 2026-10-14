"""Relay: a model's turns answered by hand through its chat app come back as ordinary chat completions."""

import asyncio

from rotomarena.llm import relay


def test_a_relayed_request_waits_for_its_answer_and_returns_it(tmp_path):
    queue = relay.RelayQueue(tmp_path, poll_seconds=0.01)
    messages = [{"role": "system", "content": "RULES"},
                {"role": "user", "content": "### Turn 3 | Weather: None\nLEGAL ACTIONS: MOVE: earthquake"}]

    async def main():
        task = asyncio.create_task(queue.submit({"model": "google/gemini-4-argon", "messages": messages}))
        while not relay.pending(tmp_path):
            await asyncio.sleep(0.01)
        (request,) = relay.pending(tmp_path)
        assert request["label"] == "Turn 3" and request["prompt"].startswith("RULES\n\n---\n\n### Turn 3")
        assert not relay.answer("999-1", "nope", tmp_path)  # not waiting
        assert relay.answer(request["id"], "<notes>n</notes><decision>MOVE: earthquake</decision>", tmp_path)
        return await task

    completion = asyncio.run(main())
    assert completion.choices[0].message.content.endswith("</decision>")
    assert completion.usage.model_extra["cost"] == 0.0 and not relay.pending(tmp_path)  # cleaned up


def test_a_second_try_carries_the_first_answer():
    text = relay.paste_text([{"role": "system", "content": "RULES"}, {"role": "user", "content": "turn"},
                             {"role": "assistant", "content": "bad"}, {"role": "user", "content": "try again"}])
    assert "YOUR PREVIOUS ANSWER:\nbad" in text and text.endswith("try again")
