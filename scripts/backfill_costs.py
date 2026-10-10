"""Fills in the cost of recorded OpenRouter turns whose usage report had none (Gemini 3.8 Flash until 10 Oct):
tokens x OpenRouter's list prices, marked cost_estimated. Turns with a reported cost are left alone.
    uv run python scripts/backfill_costs.py [runs dir]"""

import json
import sys
from collections import Counter
from pathlib import Path

from rotomarena.llm import pricing

runs = Path(sys.argv[1] if len(sys.argv) > 1 else "runs")
filled, dollars = Counter(), Counter()
for path in sorted(runs.glob("match_*/breadcrumbs.json")):
    match = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for crumb in match.get("breadcrumbs", []):
        m = crumb.get("llm_metrics") or {}
        tokens = (m.get("prompt_tokens") or 0, m.get("completion_tokens") or 0)
        if m.get("provider") != "openrouter" or m.get("cost_usd") or not any(tokens):
            continue
        cost = pricing.estimate(m.get("model", ""), *tokens)
        if cost is None:
            continue
        m["cost_usd"], m["cost_estimated"] = cost, True
        filled[m["model"]] += 1
        dollars[m["model"]] += cost
        changed = True
    if changed:
        path.write_text(json.dumps(match, indent=2, ensure_ascii=False), encoding="utf-8")
for model, n in filled.most_common():
    print(f"{model}: {n} turns, ${dollars[model]:.3f}")
