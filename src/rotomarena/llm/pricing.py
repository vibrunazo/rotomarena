"""OpenRouter's list prices, for requests whose cost OpenRouter leaves out of its usage report (Google's Gemini 3.8
Flash on 10 Oct): their cost is the tokens times the model's prices, and is marked as estimated."""

from __future__ import annotations

import json
import urllib.request
from typing import Dict, Optional, Tuple

PRICES_URL = "https://openrouter.ai/api/v1/models"
_prices: Optional[Dict[str, Tuple[float, float]]] = None


def prices() -> Dict[str, Tuple[float, float]]:
    """{model id: (USD per prompt token, USD per completion token)}, fetched once per process ({} when offline)."""
    global _prices
    if _prices is None:
        try:
            with urllib.request.urlopen(PRICES_URL, timeout=20) as r:
                models = json.load(r)["data"]
            _prices = {m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"])) for m in models}
        except Exception:
            return {}  # try again next time
    return _prices


def estimate(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    """The list-price cost of one request (completion tokens include the thinking), or None for an unknown model."""
    price = prices().get(model)
    if price is None:
        return None
    return prompt_tokens * price[0] + completion_tokens * price[1]
