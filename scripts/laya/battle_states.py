"""Laya's lessons, battle rows: base Laya plays PokéChamp with teams from the pool, every request and answer logged
(ROTOMARENA_DECISION_LOG) to data/laya/battle_decisions.jsonl. Trained on next to the drafting rows, Laya's own
answers keep its battling as it was. Laya answers from a server of its own (--port: say a CPU one beside a run that
holds the GPU); games stay in runs/laya-battles/.
Usage: uv run python scripts/laya/battle_states.py [--games N] [--parallel N] [--port 8191]"""
import argparse
import asyncio
import json
import os
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "laya"
os.environ["ROTOMARENA_DECISION_LOG"] = str(DATA / "battle_decisions.jsonl")

from rotomarena.agents.factory import create_players  # noqa: E402
from rotomarena.config import AppConfig  # noqa: E402
from rotomarena.matchmaker.runner import MatchRunner  # noqa: E402
from rotomarena.rulesets import current_rules, register  # noqa: E402
from rotomarena.server import engine  # noqa: E402
from rotomarena.teams.loader import parse_smogon_team  # noqa: E402


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=150)
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--port", type=int, default=8191)
    args = ap.parse_args()
    app = AppConfig.load(str(ROOT / "config.yaml"))
    register(app)
    app.local_llm.manage = False
    app.telemetry.output_dir = str(ROOT / "runs" / "laya-battles")
    laya = app.agents["laya"].model_copy(update={"port": args.port})
    pool = json.loads((DATA / "pool.json").read_text(encoding="utf-8"))
    teams = [v["team"] for v in pool.values() if v["valid"]]
    rng = random.Random(8191)
    runner = MatchRunner(telemetry_config=app.telemetry, rules=current_rules(app))
    lanes: asyncio.Queue = asyncio.Queue()
    for lane in range(1, args.parallel + 1):
        lanes.put_nowait(create_players(laya, app.agents["pokechamp"], app, lane=lane))
    done = {"games": 0}

    async def play(game: int) -> None:
        pa, pb = await lanes.get()
        try:
            a, b = rng.sample(teams, 2)
            await asyncio.wait_for(runner.run_game(pa, pb, parse_smogon_team(a), parse_smogon_team(b), game,
                                                   own_teams=True), 30 * 60)
            done["games"] += 1
            log(f"game {game + 1}: done ({done['games']} so far)")
        except Exception as e:
            log(f"game {game + 1}: dropped ({type(e).__name__}: {str(e)[:150]})")
        finally:
            lanes.put_nowait((pa, pb))

    async with engine.battles(app):
        await asyncio.gather(*(play(g) for g in range(args.games)))


asyncio.run(main())
