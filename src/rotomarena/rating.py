"""Bradley-Terry ratings on the Elo scale, anchored to one player, with bootstrap confidence intervals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set

import numpy as np

from rotomarena.results import Outcome


@dataclass
class Rating:
    config_id: str
    rating: Optional[float]  # None when the player's games don't connect to the anchor
    ci_low: Optional[float]
    ci_high: Optional[float]
    games: int
    wins: int
    losses: int
    draws: int

    @property
    def ranked(self) -> bool:
        return self.rating is not None


def connected_to(anchor: str, outcomes: Sequence[Outcome]) -> Set[str]:
    """Players linked to the anchor through a chain of games."""
    neighbours: Dict[str, Set[str]] = {}
    for o in outcomes:
        neighbours.setdefault(o.p1, set()).add(o.p2)
        neighbours.setdefault(o.p2, set()).add(o.p1)
    seen, frontier = {anchor}, [anchor]
    while frontier:
        for nxt in neighbours.get(frontier.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    return seen


def _fit_strengths(n: int, a: np.ndarray, b: np.ndarray, score_a: np.ndarray, prior_draws: float) -> np.ndarray:
    """Bradley-Terry maximum likelihood by Newton's method, as natural-log strengths. Each player also gets
    `prior_draws` virtual draws against a fixed opponent of strength 0, which keeps undefeated and winless
    players finite on small samples and makes the problem strictly concave."""
    wins = np.zeros((n, n))
    games = np.zeros((n, n))
    np.add.at(wins, (a, b), score_a)
    np.add.at(wins, (b, a), 1.0 - score_a)
    np.add.at(games, (a, b), 1.0)
    np.add.at(games, (b, a), 1.0)

    theta = np.zeros(n)
    for _ in range(100):
        p = 1.0 / (1.0 + np.exp(theta[None, :] - theta[:, None]))  # p[i, j] = P(i beats j)
        q = 1.0 / (1.0 + np.exp(-theta))  # P(i beats the prior opponent)
        gradient = (wins - games * p).sum(axis=1) + prior_draws * (0.5 - q)
        hessian = games * p * (1.0 - p)
        np.fill_diagonal(hessian, -hessian.sum(axis=1) - prior_draws * q * (1.0 - q))
        step = np.linalg.solve(hessian, gradient)
        theta -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return theta


def compute_ratings(
    outcomes: List[Outcome],
    anchor: str,
    anchor_rating: float = 1500.0,
    bootstrap_samples: int = 1000,
    prior_draws: float = 1.0,
    seed: int = 0,
) -> Dict[str, Rating]:
    """Ratings for everyone who played. Rating differences follow Elo: +400 means 10:1 expected odds."""
    players = sorted({o.p1 for o in outcomes} | {o.p2 for o in outcomes})
    record = {pid: [0, 0, 0] for pid in players}  # wins, losses, draws
    for o in outcomes:
        if o.score_p1 == 1.0:
            record[o.p1][0] += 1
            record[o.p2][1] += 1
        elif o.score_p1 == 0.0:
            record[o.p1][1] += 1
            record[o.p2][0] += 1
        else:
            record[o.p1][2] += 1
            record[o.p2][2] += 1

    ranked_ids = sorted(connected_to(anchor, outcomes)) if anchor in players else []
    ratings = {
        pid: Rating(pid, None, None, None, sum(record[pid]), *record[pid])
        for pid in players
    }
    if len(ranked_ids) < 2:
        return ratings

    index = {pid: i for i, pid in enumerate(ranked_ids)}
    rated = [o for o in outcomes if o.p1 in index and o.p2 in index]
    a = np.array([index[o.p1] for o in rated])
    b = np.array([index[o.p2] for o in rated])
    score = np.array([o.score_p1 for o in rated])
    anchor_i = index[anchor]

    def to_elo(theta: np.ndarray) -> np.ndarray:
        return anchor_rating + 400.0 / np.log(10.0) * (theta - theta[anchor_i])

    theta = _fit_strengths(len(ranked_ids), a, b, score, prior_draws)
    point = to_elo(theta)

    # Parametric bootstrap: replay every game with the fitted win probability and refit. Unlike resampling
    # the games themselves, this still gives a wide interval to a model that won all of its few games.
    win_prob = 1.0 / (1.0 + np.exp(theta[b] - theta[a]))
    rng = np.random.default_rng(seed)
    samples = np.empty((bootstrap_samples, len(ranked_ids)))
    for s in range(bootstrap_samples):
        simulated = (rng.random(len(rated)) < win_prob).astype(float)
        samples[s] = to_elo(_fit_strengths(len(ranked_ids), a, b, simulated, prior_draws))
    low, high = np.percentile(samples, [2.5, 97.5], axis=0)

    for pid, i in index.items():
        r = ratings[pid]
        r.rating, r.ci_low, r.ci_high = round(float(point[i]), 1), round(float(low[i]), 1), round(float(high[i]), 1)
    return ratings
