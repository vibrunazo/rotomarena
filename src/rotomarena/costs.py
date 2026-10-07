"""Rough cost estimates for paid models, from OpenRouter's public price list."""

from __future__ import annotations

import json
import urllib.request
from functools import lru_cache
from typing import Dict, Optional

from rotomarena.config import AgentConfig, AppConfig

# A game is about 25 decisions; each sends about 2.2k prompt tokens. Completions are assumed to use half
# of the per-turn cap (medium reasoning rarely uses all of it).
DECISIONS_PER_GAME = 25
PROMPT_TOKENS_PER_DECISION = 2200


@lru_cache(maxsize=1)
def openrouter_prices() -> Dict[str, Dict[str, float]]:
    """{model id: {"prompt": $/token, "completion": $/token}} from openrouter.ai (no key needed)."""
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as r:
        data = json.load(r)["data"]
    return {
        m["id"]: {"prompt": float(m["pricing"].get("prompt") or 0), "completion": float(m["pricing"].get("completion") or 0)}
        for m in data if m.get("pricing")
    }


def is_free(cfg: AgentConfig) -> bool:
    """Bots, local models and :free API models cost nothing to run."""
    return cfg.type != "direct_llm" or cfg.provider == "local" or (cfg.model or "").endswith(":free")


def estimated_cost_per_game(cfg: AgentConfig, app_cfg: AppConfig) -> Optional[float]:
    """Dollars per game for one player, or None when the price is unknown (treated as expensive)."""
    if is_free(cfg):
        return 0.0
    if cfg.provider != "openrouter":
        return None
    try:
        price = openrouter_prices().get(cfg.model or "")
    except OSError:
        return None
    if price is None:
        return None
    completion = app_cfg.ruleset.max_output_tokens / 2
    return DECISIONS_PER_GAME * (PROMPT_TOKENS_PER_DECISION * price["prompt"] + completion * price["completion"])
