"""OpenRouter's Batch API for expensive models: about half price, results within 24 hours.

A model that plays batched (AgentConfig.batch) sends each turn's request here instead of straight to the API. The
requests of every game playing at once wait a moment, go to OpenRouter together as one batch per model, and each
game gets its answer back when the batch completes, as the same chat completion a direct request returns, so the
client and the players don't know the difference. Many games at once make it pay: one round trip carries a turn of
each. Each request's cost is its share of the batch's (by list price at the batch rate), since the batch reports one
total; through our own key (BYOK) that total is the provider's price.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp
from openai.types.chat import ChatCompletion

from rotomarena.llm import pricing

BATCHES_URL = "https://openrouter.ai/api/v1/batches"
TERMINAL = {"completed", "failed", "expired", "cancelled"}
_ids = itertools.count(1)


class BatchFailed(RuntimeError):
    """A batched request came back with an error (or its batch failed): the turn falls back like an API error."""


class BatchQueue:
    """Collects requests per (model, provider pinning) and sends them as batches."""

    def __init__(self, api_key: str, flush_seconds: float = 15.0, max_requests: int = 500,
                 poll_seconds: float = 30.0, log: Callable[[str], None] = print):
        self.api_key = api_key
        self.flush_seconds = flush_seconds  # how long the first request waits for others to join its batch
        self.max_requests = max_requests
        self.poll_seconds = poll_seconds
        self.log = log
        self._pending: Dict[Tuple[str, str], List[Tuple[str, Dict[str, Any], asyncio.Future]]] = {}
        self._flushers: Dict[Tuple[str, str], asyncio.Task] = {}

    async def submit(self, create_kwargs: Dict[str, Any]) -> ChatCompletion:
        """One chat completion request (the kwargs a direct call would take), answered when its batch completes."""
        body = {k: v for k, v in create_kwargs.items() if k != "extra_body"}
        body.update(create_kwargs.get("extra_body") or {})
        model = body.pop("model")
        provider = body.pop("provider", None)
        key = (model, json.dumps(provider, sort_keys=True) if provider else "")
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending.setdefault(key, []).append((f"r{next(_ids)}", body, future))
        if len(self._pending[key]) >= self.max_requests and key in self._flushers:
            self._flushers.pop(key).cancel()
            asyncio.create_task(self._send(key))
        elif key not in self._flushers:
            self._flushers[key] = asyncio.create_task(self._flush_later(key))
        return await future

    async def _flush_later(self, key: Tuple[str, str]) -> None:
        await asyncio.sleep(self.flush_seconds)
        self._flushers.pop(key, None)
        await self._send(key)

    async def _send(self, key: Tuple[str, str]) -> None:
        items = self._pending.pop(key, [])
        if not items:
            return
        model, provider = key
        # endpoint, model, provider and completion_window must come before requests (OpenRouter stream-parses)
        payload: Dict[str, Any] = {"endpoint": "/v1/chat/completions", "model": model}
        if provider:
            payload["provider"] = json.loads(provider)
        payload["completion_window"] = "24h"
        payload["requests"] = [{"custom_id": cid, "body": body} for cid, body, _ in items]
        futures = {cid: future for cid, _, future in items}
        try:
            batch = await self._run(payload)
            self._resolve(model, batch, futures)
        except Exception as e:  # the whole batch: every waiting turn falls back
            for future in futures.values():
                if not future.done():
                    future.set_exception(BatchFailed(f"batch of {len(items)} for {model}: {e}"))

    async def _run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(BATCHES_URL, data=json.dumps(payload), headers=headers) as r:
                created = await r.json(content_type=None)
                if r.status >= 300:
                    raise BatchFailed(f"submit {r.status}: {str(created)[:400]}")
            batch_id = created["id"]
            started = time.time()
            self.log(f"batch {batch_id}: {len(payload['requests'])} requests for {payload['model']}")
            wait = self.poll_seconds
            while True:
                await asyncio.sleep(wait)
                async with session.get(f"{BATCHES_URL}/{batch_id}", headers=headers) as r:
                    batch = await r.json(content_type=None)
                if r.status >= 300:
                    continue  # a failed poll: try again
                if batch.get("status") in TERMINAL:
                    self.log(f"batch {batch_id}: {batch['status']} after {(time.time() - started) / 60:.1f} min")
                    return batch
                wait = min(wait * 1.5, 300)  # back off to every 5 minutes while it waits its turn

    def _resolve(self, model: str, batch: Dict[str, Any], futures: Dict[str, asyncio.Future]) -> None:
        results = batch.get("results") or []
        usage = batch.get("usage") or {}
        details = usage.get("cost_details") or {}
        total = (details.get("upstream_inference_cost") if usage.get("is_byok") else None) or usage.get("cost")
        # each request's share of the batch's cost, by its tokens at the batch's list prices
        shares = {}
        for item in results:
            body = (item.get("response") or {}).get("body") or {}
            u = body.get("usage") or {}
            shares[item.get("custom_id")] = (pricing.estimate(f"{model}:batch", u.get("prompt_tokens") or 0,
                                                              u.get("completion_tokens") or 0) or 0.0)
        if total and not sum(shares.values()) and shares:  # batch prices unknown: an even split
            shares = {cid: 1.0 for cid in shares}
        scale = (total / sum(shares.values())) if total and sum(shares.values()) else 1.0
        for item in results:
            future = futures.pop(item.get("custom_id"), None)
            if future is None or future.done():
                continue
            response = item.get("response") or {}
            body = response.get("body")
            if item.get("error") or not body or (response.get("status_code") or 200) >= 300:
                future.set_exception(BatchFailed(f"{item.get('error') or response.get('status_code')}"))
                continue
            body.setdefault("usage", {})
            body["usage"]["cost"] = round(shares.get(item.get("custom_id"), 0.0) * scale, 8)
            body["usage"]["batched"] = True
            try:
                future.set_result(ChatCompletion.model_validate(body))
            except Exception as e:
                future.set_exception(BatchFailed(f"unreadable result: {e}"))
        for future in futures.values():  # requests the batch didn't answer
            if not future.done():
                future.set_exception(BatchFailed(f"no result (batch {batch.get('status')})"))


_queue: Optional[BatchQueue] = None


def shared_queue(api_key: str) -> BatchQueue:
    """One queue for the whole process, so every game's requests for a model share its batches."""
    global _queue
    if _queue is None:
        _queue = BatchQueue(api_key)
    return _queue
