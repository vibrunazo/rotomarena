"""How each draft does on the ladder in its own model's hands, against a league's ratings of the same teams.
A model plays its drafts in turn against the same opponents, so within one model the team is the only difference:
a league that measures good drafts should rank a model's drafts the way its ladder games do. Counts c5 games
against non-control opponents (a control bot plays a copy of its opponent's team), finds which draft played from
the six Pokémon shown at team preview, and writes data/laya/draft_ladder.json.
Usage: uv run python scripts/laya/draft_ladder.py [--ratings data/laya/team_ratings.json] [--min-games 8]"""
import argparse
import collections
import glob
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "laya"

from rotomarena.config import AppConfig  # noqa: E402


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def team_id(text: str) -> str:  # as team_league.py
    return hashlib.sha1("\n".join(line.strip() for line in text.strip().splitlines()).encode()).hexdigest()[:12]


def drafts(app: AppConfig) -> dict:
    """config id -> [(species set, team id)] for its drafts in the version played."""
    out = {}
    for path in glob.glob(str(ROOT / "data" / "drafts" / app.ruleset.format / app.ruleset.version / "*.json")):
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        out[record["config_id"]] = [
            ({norm(re.split(r"\s*[@(]", b.strip().splitlines()[0])[0]) for b in r["team"].strip().split("\n\n")},
             team_id(r["team"]))
            for r in [record] + list(record.get("more") or []) if r.get("team")]
    return out


def ladder_records(app: AppConfig) -> dict:
    """(config id, team id) -> [wins, losses] in rated games against opponents playing their own teams."""
    controls = {k for k, a in app.agents.items() if a.role == "control"}
    teams = drafts(app)
    out = collections.defaultdict(lambda: [0, 0])
    for path in glob.glob(str(ROOT / "runs" / "match_*" / "battle_log.json")):
        log = json.loads(Path(path).read_text(encoding="utf-8"))
        meta = log["metadata"]
        if (meta.get("ruleset") or {}).get("version") != app.ruleset.version:
            continue
        crumbs = Path(path).with_name("breadcrumbs.json")
        if not crumbs.exists() or json.loads(crumbs.read_text(encoding="utf-8")).get("voided"):
            continue
        if any(p["config_id"] in controls for p in meta["players"]) or not meta.get("winner"):
            continue
        entries = [x for x in log["raw_logs"] if isinstance(x, list) and len(x) > 3]
        side = {x[3]: x[2] for x in entries if x[1] == "player"}
        game = int(re.search(r"_g(\d+)$", log["match_id"]).group(1))  # game g of a set plays draft (g - 1) mod n
        for p in meta["players"]:
            own = teams.get(p["config_id"])
            if not own:
                continue
            species, tid = own[(game - 1) % len(own)]
            shown = {norm(x[3].split(",")[0]) for x in entries if x[1] == "poke" and x[2] == side.get(p["username"])}
            if shown != species:  # a draft redone since (or a forme named differently): leave the game out
                CHECKS["mismatch"] += 1
                continue
            CHECKS["matched"] += 1
            out[(p["config_id"], tid)][0 if meta["winner"] == p["username"] else 1] += 1
    return out


CHECKS = collections.Counter()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", default=str(DATA / "team_ratings.json"))
    ap.add_argument("--min-games", type=int, default=8)
    args = ap.parse_args()
    app = AppConfig.load(str(ROOT / "config.yaml"))
    ratings = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
    by_model = collections.defaultdict(list)
    for (cid, tid), (w, l) in ladder_records(app).items():
        if w + l >= args.min_games:
            by_model[cid].append({"team": tid, "wins": w, "losses": l, "league": (ratings.get(tid) or {}).get("rating")})
    agree = disagree = 0
    xs, ys = [], []
    for cid, rows in sorted(by_model.items()):
        rated = [r for r in rows if r["league"] is not None]
        if len(rated) < 2:
            continue
        print(f"{cid:24}", "  ".join(f"{r['league']:.0f} -> {r['wins'] / (r['wins'] + r['losses']):.0%} ({r['wins'] + r['losses']})"
                                     for r in sorted(rated, key=lambda r: r["league"])))
        rate = [r["wins"] / (r["wins"] + r["losses"]) for r in rated]
        mean_l, mean_w = sum(r["league"] for r in rated) / len(rated), sum(rate) / len(rate)
        xs += [r["league"] - mean_l for r in rated]
        ys += [w - mean_w for w in rate]
        for i in range(len(rated)):
            for j in range(i + 1, len(rated)):
                dl, dw = rated[i]["league"] - rated[j]["league"], rate[i] - rate[j]
                if dl and dw:
                    agree += (dl > 0) == (dw > 0)
                    disagree += (dl > 0) != (dw > 0)
    r = (sum(x * y for x, y in zip(xs, ys)) / math.sqrt(sum(x * x for x in xs) * sum(y * y for y in ys))) if xs else None
    summary = {"ratings": Path(args.ratings).name, "drafts": len(xs), "pairs_agree": agree, "pairs_disagree": disagree,
               "within_model_r": round(r, 3) if r is not None else None, "by_model": by_model}
    (DATA / "draft_ladder.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"team preview matched the draft by game number on {CHECKS['matched']} sides, not on {CHECKS['mismatch']}")
    print(f"\n{Path(args.ratings).name}: within-model pairs agree {agree}, disagree {disagree}; r = "
          f"{r:.2f} over {len(xs)} drafts" if r is not None else "not enough drafts yet")


if __name__ == "__main__":
    main()
