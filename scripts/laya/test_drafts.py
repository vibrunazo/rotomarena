"""Laya's drafting test: a Laya checkpoint drafts teams the way it does on the ladder (draft_decisions.py), saved to
data/laya/test_drafts/<name>/<n>.json; team_league.py then rates them beside the pool's teams, which shows whether
the lessons made its teams stronger. Its server is given by --port; --checkpoint names the checkpoint on it.
Usage: uv run python scripts/laya/test_drafts.py <name> --port 8191 [--checkpoint multilingual] [--count 12]"""
import argparse
import asyncio
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from rotomarena.config import AppConfig  # noqa: E402
from rotomarena.teams.draft_decisions import draft_team_by_decisions  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--checkpoint", default="multilingual")
    ap.add_argument("--count", type=int, default=12)
    args = ap.parse_args()
    app = AppConfig.load(str(ROOT / "config.yaml"))
    app.local_llm.manage = False
    base = app.agents["laya"]
    agent = base.model_copy(update={"port": args.port,
                                    "decision_request": {**(base.decision_request or {}), "model": args.checkpoint}})
    out = ROOT / "data" / "laya" / "test_drafts" / args.name
    out.mkdir(parents=True, exist_ok=True)
    for n in range(1, args.count + 1):
        path = out / f"{n}.json"
        if path.exists():
            continue
        record = await draft_team_by_decisions(agent, app, log=lambda msg: None)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{time.strftime('%H:%M:%S')} {args.name} #{n}: {'legal' if record['legal'] else 'repaired'}: "
              f"{', '.join(record['picks']['species'])}", flush=True)


asyncio.run(main())
