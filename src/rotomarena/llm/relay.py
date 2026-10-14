"""Relay: a person plays a model's turns through its chat app (Gemini 4 Argon in the Gemini app), by hand.

A relayed model's client doesn't call an API. Each request is written to runs/relay/<id>.json as one text to paste
(the system prompt, then the turn's message; a second try adds the first answer and what was wrong with it). The run
monitor shows it with a copy button and a box for the answer; the answer comes back as runs/relay/<id>.answer.txt and
is returned as the chat completion an API would return, so parsing, second tries and notes work as for every model.
Relayed games carry the tag relay:<channel>:<config id> (MatchTelemetry.tags): the app is not the API (its own
system prompt, thinking setting and tools), so they are kept apart and can be replaced by API games later.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

from openai.types.chat import ChatCompletion

RELAY_DIR = Path(__file__).resolve().parents[3] / "runs" / "relay"  # the run monitor reads it too
CHANNEL = "gemini-app"
relayed: Set[str] = set()  # config ids `ladder relay` plays by hand in this process
_ids = itertools.count(1)


def tag(config_id: str) -> str:
    return f"relay:{CHANNEL}:{config_id}"


def paste_text(messages: list) -> str:
    """The request as one text for a chat app: the instructions, the turn's message, and on a second try the first
    answer and the note on what was wrong."""
    parts = []
    for m in messages:
        content = m["content"] if isinstance(m["content"], str) else "".join(b.get("text", "") for b in m["content"])
        if m["role"] == "system":
            parts.append(content)
        elif m["role"] == "assistant":
            parts.append("YOUR PREVIOUS ANSWER:\n" + content)
        else:
            parts.append(content)
    return "\n\n---\n\n".join(parts)


class RelayQueue:
    """Requests written for a person to relay, and their answers read back."""

    def __init__(self, directory: Path = RELAY_DIR, poll_seconds: float = 2.0):
        self.dir = Path(directory)
        self.poll = poll_seconds

    async def submit(self, create_kwargs: Dict[str, Any]) -> ChatCompletion:
        self.dir.mkdir(parents=True, exist_ok=True)
        rid = f"{int(time.time())}-{next(_ids)}"
        messages = create_kwargs["messages"]
        text = paste_text(messages)
        turn = re.findall(r"### (Turn \d+|Team preview)", text)
        request = {"id": rid, "model": create_kwargs.get("model"), "created": time.time(),
                   "label": turn[-1] if turn else "", "retry": len(messages) > 2, "prompt": text}
        path, answer = self.dir / f"{rid}.json", self.dir / f"{rid}.answer.txt"
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        try:
            while not answer.exists():
                await asyncio.sleep(self.poll)
            text = answer.read_text(encoding="utf-8")
        finally:
            path.unlink(missing_ok=True)
            answer.unlink(missing_ok=True)
        return ChatCompletion.model_validate({
            "id": f"relay-{rid}", "object": "chat.completion", "created": int(time.time()),
            "model": f"{CHANNEL}:{create_kwargs.get('model')}",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0},
        })


def pending(directory: Path = RELAY_DIR) -> list:
    """Requests waiting for an answer, oldest first (for the run monitor)."""
    if not directory.exists():
        return []
    out = []
    for p in sorted(directory.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda r: r.get("created", 0))


def answer(request_id: str, text: str, directory: Path = RELAY_DIR) -> bool:
    """Hands an answer to the waiting request; False if it is no longer waiting."""
    if not re.fullmatch(r"[0-9]+-[0-9]+", request_id) or not (directory / f"{request_id}.json").exists():
        return False
    tmp = directory / f"{request_id}.answer.tmp"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(directory / f"{request_id}.answer.txt")  # whole, never half-written
    return True


_queue: Optional[RelayQueue] = None


def shared_queue() -> RelayQueue:
    global _queue
    if _queue is None:
        _queue = RelayQueue()
    return _queue
