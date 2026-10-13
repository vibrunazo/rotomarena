"""OpenRouter Batch API queue: requests of games playing at once share a batch; each gets its own answer and share
of the cost."""

import asyncio

import pytest

from rotomarena.llm import batch as batch_mod
from rotomarena.llm.batch import BatchFailed, BatchQueue


def _completion(text, prompt=1000, completion=200):
    return {"id": "gen", "object": "chat.completion", "created": 0, "model": "m", "service_tier": "batch",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}}


def test_requests_share_a_batch_and_get_their_own_answers(monkeypatch):
    sent = []

    async def run(self, payload):
        sent.append(payload)
        return {"status": "completed", "usage": {"cost": 0.03},
                "results": [{"custom_id": r["custom_id"], "response": {"status_code": 200,
                             "body": _completion(r["body"]["messages"][0]["content"].upper())}}
                            for r in payload["requests"]][:2]}  # the third goes unanswered

    monkeypatch.setattr(BatchQueue, "_run", run)
    monkeypatch.setattr(batch_mod.pricing, "estimate", lambda model, p, c: p * 1e-6 + c * 5e-6)
    queue = BatchQueue("key", flush_seconds=0.01)

    async def ask(text):
        return await queue.submit({"model": "anthropic/claude-sonnet-5.5", "messages": [{"role": "user", "content": text}],
                                   "temperature": 0.7,
                                   "extra_body": {"reasoning": {"effort": "medium"}, "provider": {"only": ["Anthropic"]}}})

    async def main():
        return await asyncio.gather(ask("one"), ask("two"), ask("three"), return_exceptions=True)

    one, two, three = asyncio.run(main())
    assert len(sent) == 1 and len(sent[0]["requests"]) == 3  # one batch for the three
    assert list(sent[0])[:4] == ["endpoint", "model", "provider", "completion_window"]  # before requests
    assert sent[0]["requests"][0]["body"]["reasoning"] == {"effort": "medium"}
    assert "temperature" not in sent[0]["requests"][0]["body"]  # Claude thinks only without it in a batch
    assert one.choices[0].message.content == "ONE" and two.choices[0].message.content == "TWO"
    assert abs(one.usage.model_extra["cost"] - 0.015) < 1e-9  # half the batch's cost each, by tokens
    assert isinstance(three, BatchFailed)
