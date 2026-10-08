"""The ladder: season ratings, placement games for new models, and top-up games where ratings overlap."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from rotomarena.agents.factory import create_players
from rotomarena import local_servers
from rotomarena.config import AgentConfig, AppConfig
from rotomarena.costs import estimated_cost_per_game, is_free
from rotomarena.matchmaker.runner import MatchRunner
from rotomarena.rating import Rating, compute_ratings
from rotomarena.results import Outcome, games_between, load_matches, rated_outcomes, void_reason
from rotomarena.teams.presets import load_preset_team
from rotomarena.telemetry.breadcrumbs import MatchTelemetry


class RunHalted(RuntimeError):
    """Something outside a single game is wrong (a provider limit, games that keep coming out void). The run
    stops rather than void the rest of its schedule; placement resumes where it stopped."""


@dataclass
class SeasonState:
    matches: List[MatchTelemetry]
    outcomes: List[Outcome]
    ratings: Dict[str, Rating]
    pair_games: Dict[frozenset, int]

    def games(self, a: str, b: str) -> int:
        return self.pair_games.get(frozenset((a, b)), 0)

    @property
    def void_count(self) -> int:
        return len(self.matches) - len(self.outcomes)


def season_state(app_cfg: AppConfig) -> SeasonState:
    """Every match of the current season, rated."""
    matches = load_matches(app_cfg.telemetry.output_dir, app_cfg.ruleset.version)
    outcomes = rated_outcomes(matches, app_cfg.ladder.max_autopilot)
    ratings = compute_ratings(
        outcomes,
        anchor=app_cfg.ladder.anchor,
        anchor_rating=app_cfg.ladder.anchor_rating,
        bootstrap_samples=app_cfg.ladder.bootstrap_samples,
    )
    return SeasonState(matches, outcomes, ratings, games_between(outcomes))


def control_opponents(config_id: str, app_cfg: AppConfig, force: bool = False,
                      log: Callable[[str], None] = print) -> List[str]:
    """Control bots (Random AI) a model meets first, unless it is estimated to be too expensive per game."""
    controls = [k for k, a in app_cfg.agents.items() if a.role == "control" and k != config_id]
    if not controls or force:
        return controls
    cost = estimated_cost_per_game(app_cfg.agents[config_id], app_cfg)
    limit = app_cfg.ladder.control_max_cost_per_game_usd
    if cost is None or cost > limit:
        shown = "unknown" if cost is None else f"${cost:.2f}"
        log(f"Skipping control games: estimated {shown} per game is over ${limit:.2f} (--with-control to play them)")
        return []
    return controls


def fixed_placement_opponents(config_id: str, agents: Dict[str, AgentConfig]) -> List[str]:
    """Every anchor plus one sparring partner (not the model itself)."""
    anchors = [k for k, a in agents.items() if a.role == "anchor" and k != config_id]
    sparring = [k for k, a in agents.items() if a.role == "sparring" and k != config_id]
    return anchors + sparring[:1]


def closest_rated_llm(
    config_id: str, agents: Dict[str, AgentConfig], ratings: Dict[str, Rating], exclude: List[str]
) -> Optional[str]:
    """The ranked LLM whose rating is nearest to this model's provisional rating."""
    me = ratings.get(config_id)
    if not me or not me.ranked:
        return None
    candidates = [
        k for k, a in agents.items()
        if a.type == "direct_llm" and k != config_id and k not in exclude and k in ratings and ratings[k].ranked
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda k: abs(ratings[k].rating - me.rating))


def fill_pairs(state: SeasonState, agents: Dict[str, AgentConfig], free_only: bool = True) -> List[Tuple[str, str]]:
    """Neighbouring models whose confidence intervals overlap, most overlap per game played first."""
    ranked = sorted(
        (r for r in state.ratings.values() if r.ranked and r.config_id in agents),
        key=lambda r: r.rating,
    )
    scored = []
    for low, high in zip(ranked, ranked[1:]):
        overlap = min(low.ci_high, high.ci_high) - max(low.ci_low, high.ci_low)
        if overlap <= 0:
            continue
        if free_only and not (is_free(agents[low.config_id]) and is_free(agents[high.config_id])):
            continue
        scored.append((overlap / (1 + state.games(low.config_id, high.config_id)), (high.config_id, low.config_id)))
    return [pair for _, pair in sorted(scored, reverse=True)]


def _pair_matches(app_cfg: AppConfig, id_a: str, id_b: str) -> List[MatchTelemetry]:
    """This season's matches between two registry entries, oldest first, void ones included."""
    pair = {id_a, id_b}
    return [
        m for m in load_matches(app_cfg.telemetry.output_dir, app_cfg.ruleset.version)
        if m.player("p1") and m.player("p2") and {m.player("p1").config_id, m.player("p2").config_id} == pair
    ]


def check_halt(label: str, players: List, new_matches: List[MatchTelemetry], max_autopilot: float) -> None:
    """Raises RunHalted when a player hit a provider limit or the last two games of this set were void."""
    for player in players:
        limit = getattr(player, "provider_limit", None)
        if limit:
            raise RunHalted(f"{label}: provider limit reached: {limit}")
    reasons = [void_reason(m, max_autopilot) for m in new_matches[-2:]]
    if len(reasons) == 2 and all(reasons):
        raise RunHalted(f"{label}: two void games in a row ({reasons[-1]})")


def lane_count(agent_a: AgentConfig, agent_b: AgentConfig, app_cfg: AppConfig, remaining: int) -> int:
    """Games of a set played at once: the ladder's setting, capped by either player's own limit."""
    limits = [app_cfg.ladder.parallel_games, remaining, agent_a.max_parallel_games, agent_b.max_parallel_games]
    return min(n for n in limits if n is not None)


def rounds(first_game: int, n_games: int, parallel: int) -> List[List[int]]:
    """The games of a set (0-based, as in series_schedule) grouped into rounds played at once."""
    games = list(range(first_game, first_game + n_games))
    return [games[i:i + parallel] for i in range(0, len(games), parallel)]


async def play_set(id_a: str, id_b: str, app_cfg: AppConfig, already_played: int, games: Optional[int] = None) -> int:
    """Plays the rest of a set between two registry entries; returns how many games were played.
    Up to ladder.parallel_games games run at once, each by its own pair of players (a lane). Between rounds the
    run checks for halts and restarts crashed local servers, as it did between games when they ran one by one."""
    remaining = (games or app_cfg.ladder.games_per_set) - already_played
    if remaining <= 0:
        return 0
    agent_a, agent_b = app_cfg.agents[id_a], app_cfg.agents[id_b]
    lanes = [create_players(agent_a, agent_b, app_cfg, lane=k + 1)
             for k in range(lane_count(agent_a, agent_b, app_cfg, remaining))]
    players = [p for lane in lanes for p in lane]
    team_1, team_2 = (load_preset_team(t) for t in app_cfg.ruleset.teams)
    runner = MatchRunner(telemetry_config=app_cfg.telemetry, ruleset=app_cfg.ruleset)
    played_before = len(_pair_matches(app_cfg, id_a, id_b))

    def halt_check() -> None:
        new = _pair_matches(app_cfg, id_a, id_b)[played_before:]
        check_halt(f"{id_a} vs {id_b}", players, new, app_cfg.ladder.max_autopilot)

    try:
        for round_games in rounds(already_played, remaining, len(lanes)):
            halt_check()
            local_servers.prepare([agent_a, agent_b], app_cfg)
            try:
                async with asyncio.TaskGroup() as group:  # one failed game cancels the round; the set resumes later
                    for (player_a, player_b), game in zip(lanes, round_games):
                        group.create_task(runner.run_game(player_a, player_b, team_1, team_2, game))
            except ExceptionGroup as failed:
                raise failed.exceptions[0] from failed  # the run log shows the actual error
        halt_check()
    finally:
        for player in players:
            try:
                await player.ps_client.stop_listening()
            except Exception:
                pass
    return remaining


async def place(config_id: str, app_cfg: AppConfig, log: Callable[[str], None] = print,
                with_control: bool = False) -> SeasonState:
    """Placement: a short set against the control bot (cheap models only), a set against each anchor and a
    sparring partner, then one against the closest-rated LLM.
    Sets already played this season are skipped, so an interrupted placement resumes where it stopped."""
    agents = app_cfg.agents
    if config_id not in agents:
        raise ValueError(f"'{config_id}' is not in the agents registry ({', '.join(sorted(agents))})")

    state = season_state(app_cfg)
    for opponent in control_opponents(config_id, app_cfg, force=with_control, log=log):
        done = state.games(config_id, opponent)
        log(f"{config_id} vs {opponent} (control): {done}/{app_cfg.ladder.control_games} valid games so far")
        await play_set(config_id, opponent, app_cfg, done, games=app_cfg.ladder.control_games)
    for opponent in fixed_placement_opponents(config_id, agents):
        done = state.games(config_id, opponent)
        log(f"{config_id} vs {opponent}: {done}/{app_cfg.ladder.games_per_set} valid games so far")
        await play_set(config_id, opponent, app_cfg, done)

    state = season_state(app_cfg)
    rival = closest_rated_llm(config_id, agents, state.ratings, exclude=fixed_placement_opponents(config_id, agents))
    if rival is None:
        log("No other ranked LLM yet, so placement ends after the fixed opponents.")
        return state
    done = state.games(config_id, rival)
    log(f"Closest-rated LLM: {rival} ({state.ratings[rival].rating:.0f}). {done}/{app_cfg.ladder.games_per_set} played so far")
    await play_set(config_id, rival, app_cfg, done)
    return season_state(app_cfg)


async def fill(app_cfg: AppConfig, budget: int, free_only: bool = True, log: Callable[[str], None] = print) -> int:
    """Spends up to `budget` games on the pairs whose ratings are least separated. Returns games played."""
    played = 0
    while played < budget:
        state = season_state(app_cfg)
        pairs = fill_pairs(state, app_cfg.agents, free_only)
        if not pairs:
            log("No overlapping pairs to play.")
            break
        a, b = pairs[0]
        games = min(app_cfg.ladder.games_per_set, budget - played)
        log(f"Top-up: {a} vs {b} ({games} games)")
        played += await play_set(a, b, app_cfg, already_played=0, games=games)
    return played


def describe_void_matches(state: SeasonState, max_autopilot: float) -> List[Tuple[str, str]]:
    return [(m.match_id, reason) for m in state.matches if (reason := void_reason(m, max_autopilot))]
