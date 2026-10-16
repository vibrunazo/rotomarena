"""Laya's drafting lessons, step 1: the models in sources.py draft extra teams under the version being played (its
prompts, rules and thinking budget), saved apart from the ladder's drafts: data/laya/drafts/<config id>/<n>.json.
Resumable: drafts already saved are skipped. API models only (local ones would need the run's GPU servers).
Usage: uv run python scripts/laya/draft_pool.py [--per-model N] [--parallel N] [config id ...]"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from sources import SOURCES  # noqa: E402

from rotomarena.config import AgentConfig, AppConfig  # noqa: E402
from rotomarena.teams.draft import DraftUnavailable, draft_team  # noqa: E402

OUT = ROOT / "data" / "laya" / "drafts"


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def agent_for(config_id: str, app: AppConfig) -> AgentConfig:
    if config_id in app.agents:
        return app.agents[config_id]
    name, _, model, _ = SOURCES[config_id]
    return AgentConfig(name=config_id, type="direct_llm", provider="openrouter", model=model, display_name=name)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--per-model", type=int, default=8)
    ap.add_argument("--parallel", type=int, default=12)
    args = ap.parse_args()
    app = AppConfig.load(str(ROOT / "config.yaml"))
    ids = args.ids or [k for k in SOURCES if SOURCES[k][2] or app.agents[k].provider == "openrouter"]
    gate = asyncio.Semaphore(args.parallel)
    spent = {"usd": 0.0}

    async def one(config_id: str, n: int) -> None:
        path = OUT / config_id / f"{n}.json"
        if path.exists():
            return
        async with gate:
            try:
                record = await draft_team(agent_for(config_id, app), app, log=lambda msg: None)
            except DraftUnavailable as e:
                log(f"{config_id} #{n}: no draft ({str(e)[:200]})")
                return
            except Exception as e:  # one model's failure leaves the others drafting
                log(f"{config_id} #{n}: error {type(e).__name__}: {str(e)[:200]}")
                return
        cost = sum(a.get("cost_usd") or 0 for a in record["picks"]["attempts"] + record["attempts"])
        spent["usd"] += cost
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log(f"{config_id} #{n}: {'legal' if record['legal'] else 'repaired'}, ${cost:.4f} (run total ${spent['usd']:.2f})")

    await asyncio.gather(*(one(c, n) for n in range(1, args.per_model + 1) for c in ids))
    log(f"done: ${spent['usd']:.2f}")


asyncio.run(main())
