"""Laya's drafting lessons, step 2: how strong is each team? PokéChamp pilots both sides, so the teams are all that
differ. Every team in the pool (legal drafts by the models in sources.py: the ladder's, c1-c5, and data/laya/drafts;
plus test teams in data/laya/test_drafts/<name>/, rated beside them but never trained on) plays random others in rounds, one game from each side, in the simulator; the games stay in runs/laya-league/,
away from the ladder's. Results: data/laya/league_games.jsonl; each team's strength, a Bradley-Terry rating over
its games, goes to data/laya/team_ratings.json. Resumable: played games count, and teams drafted since join in.
Usage: uv run python scripts/laya/team_league.py [--games-per-team N] [--parallel N]"""
import argparse
import asyncio
import glob
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from sources import SOURCES  # noqa: E402

from rotomarena.agents.factory import create_players  # noqa: E402
from rotomarena.config import AppConfig  # noqa: E402
from rotomarena.matchmaker.runner import MatchRunner  # noqa: E402
from rotomarena.rulesets import current_rules, register  # noqa: E402
from rotomarena.server import engine  # noqa: E402
from rotomarena.teams.draft import validate_team  # noqa: E402
from rotomarena.teams.loader import parse_smogon_team  # noqa: E402

DATA = ROOT / "data" / "laya"
POOL, GAMES, RATINGS = DATA / "pool.json", DATA / "league_games.jsonl", DATA / "team_ratings.json"
GAME_MINUTES = 30  # a game past this is dropped (and played again on the next run)


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def team_id(text: str) -> str:
    return hashlib.sha1("\n".join(line.strip() for line in text.strip().splitlines()).encode()).hexdigest()[:12]


def drafted(app: AppConfig):
    """(config id, where, team text) for every legal draft by a source model."""
    for path in sorted(glob.glob(str(ROOT / "data" / "drafts" / app.ruleset.format / "*" / "*.json"))):
        config_id = Path(path).stem
        if config_id in SOURCES:
            record = json.loads(Path(path).read_text(encoding="utf-8"))
            for i, r in enumerate([record] + list(record.get("more") or [])):
                if r.get("legal") and not r.get("repaired") and r.get("team"):
                    yield config_id, f"ladder:{r.get('ruleset_version')}:{i + 1}", r["team"]
    for path in sorted(glob.glob(str(DATA / "drafts" / "*" / "*.json"))):
        r = json.loads(Path(path).read_text(encoding="utf-8"))
        if r.get("legal") and not r.get("repaired") and r.get("team"):
            yield r["config_id"], f"pool:{Path(path).stem}", r["team"]
    for path in sorted(glob.glob(str(DATA / "test_drafts" / "*" / "*.json"))):
        r = json.loads(Path(path).read_text(encoding="utf-8"))
        if r.get("team"):  # a test team is rated even when repaired: it is what the drafter would play
            yield f"test:{Path(path).parent.name}", f"test:{Path(path).stem}", r["team"]


def update_pool(app: AppConfig) -> dict:
    """Every source team, checked by Showdown's validator under the version played now (older versions' drafts
    may break its rules); duplicates count once."""
    pool = json.loads(POOL.read_text(encoding="utf-8")) if POOL.exists() else {}
    for config_id, where, text in drafted(app):
        tid = team_id(text)
        if tid in pool:
            if where not in pool[tid]["drafts"]:
                pool[tid]["drafts"].append(where)
                pool[tid]["sources"] = sorted(set(pool[tid]["sources"]) | {config_id})
            continue
        problems = validate_team(app, text.strip() + "\n")
        pool[tid] = {"team": text.strip(), "sources": [config_id], "drafts": [where], "valid": not problems,
                     "problems": problems[:3]}
    POOL.parent.mkdir(parents=True, exist_ok=True)
    POOL.write_text(json.dumps(pool, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return pool


def bradley_terry(games: list, teams: list, prior: float = 1.0) -> dict:
    """Elo-scaled ratings (mean 1500): MM iterations, each team also drawing `prior` games against an average
    team so a few games don't give extreme ratings."""
    strength = {t: 1.0 for t in teams}
    wins = Counter(g["winner"] for g in games if g["winner"])
    opponents = {t: [] for t in teams}
    for g in games:
        if g["winner"]:
            opponents[g["a"]].append(g["b"])
            opponents[g["b"]].append(g["a"])
    for _ in range(200):
        new = {}
        for t in teams:
            denom = sum(1 / (strength[t] + strength[o]) for o in opponents[t]) + prior * 2 / (strength[t] + 1)
            new[t] = (wins[t] + prior) / denom
        mean = math.exp(sum(math.log(v) for v in new.values()) / len(new))
        strength = {t: v / mean for t, v in new.items()}
    return {t: 1500 + 400 * math.log10(strength[t]) for t in teams}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games-per-team", type=int, default=40)
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--teams", type=int, default=0, help="only the first N teams (a test)")
    args = ap.parse_args()
    app = AppConfig.load(str(ROOT / "config.yaml"))
    register(app)
    app.local_llm.manage = False
    app.telemetry.output_dir = str(ROOT / "runs" / "laya-league")
    pool = update_pool(app)
    valid = sorted(t for t, v in pool.items() if v["valid"])
    log(f"pool: {len(valid)} valid teams ({len(pool) - len(valid)} broken under {app.ruleset.version}'s rules)")
    teams = valid[:args.teams or None]
    games = [json.loads(line) for line in GAMES.open(encoding="utf-8")] if GAMES.exists() else []
    played = Counter(t for g in games for t in (g["a"], g["b"]))

    pokechamp = app.agents["pokechamp"]
    runner = MatchRunner(telemetry_config=app.telemetry, rules=current_rules(app))
    lanes: asyncio.Queue = asyncio.Queue()
    for lane in range(1, args.parallel + 1):
        lanes.put_nowait(create_players(pokechamp, pokechamp, app, lane=lane))

    async def play(a: str, b: str, game: int) -> None:
        pa, pb = await lanes.get()
        try:
            team_a = parse_smogon_team(pool[a]["team"], name=f"team {a}")
            team_b = parse_smogon_team(pool[b]["team"], name=f"team {b}")
            result = await asyncio.wait_for(runner.run_game(pa, pb, team_a, team_b, game, own_teams=True),
                                            GAME_MINUTES * 60)
        except Exception as e:
            log(f"{a} vs {b}: dropped ({type(e).__name__}: {str(e)[:150]})")
            return
        finally:
            lanes.put_nowait((pa, pb))
        winner = {pa.agent_name: a, pb.agent_name: b}.get(result.winner)
        record = {"a": a, "b": b, "game": game, "winner": winner, "turns": result.total_turns, "match_id": result.match_id}
        with GAMES.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        games.append(record)

    rng = random.Random(len(games))
    async with engine.battles(app):
        while True:
            short = [t for t in teams if played[t] < args.games_per_team]
            if not short:
                break
            # a round: each team still short of games against a random partner from the whole pool, so teams that
            # join later are rated on the same scale as the rest
            pairs = [(t, rng.choice([o for o in teams if o != t])) for t in short]
            log(f"round: {len(pairs)} pairs, {len(games)} games so far")
            await asyncio.gather(*(play(a, b, g) for a, b in pairs for g in (0, 1)))
            played = Counter(t for g in games for t in (g["a"], g["b"]))
            ratings = bradley_terry(games, teams)
            RATINGS.write_text(json.dumps({t: {"rating": round(ratings[t], 1), "games": played[t],
                                               "wins": sum(g["winner"] == t for g in games),
                                               "sources": pool[t]["sources"]} for t in teams}, indent=1) + "\n",
                               encoding="utf-8")
    log("done")


asyncio.run(main())
