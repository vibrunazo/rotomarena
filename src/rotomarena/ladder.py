"""The ladder: ratings per ruleset version, placement games for new models, and top-up games where ratings overlap."""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from rotomarena.agents.factory import create_players
from rotomarena import local_servers
from rotomarena.config import AgentConfig, AppConfig
from rotomarena.costs import estimated_cost_per_game, is_free
from rotomarena.matchmaker.runner import MatchRunner
from rotomarena.rating import Rating, compute_ratings
from rotomarena.rulesets import current_rules, same_rules, settings_current, stored_rules
from rotomarena.results import Outcome, autopilot_rate, games_between, load_matches, rated_outcomes, void_reason
from rotomarena.teams.draft import load_drafts, playable_team
from rotomarena.teams.loader import Team, parse_smogon_team
from rotomarena.teams.presets import load_preset_team
from rotomarena.telemetry.breadcrumbs import MatchTelemetry


class RunHalted(RuntimeError):
    """Something outside a single game is wrong (a provider limit, games that keep coming out void). The run
    stops rather than void the rest of its schedule; placement resumes where it stopped."""


def watchdog(app_cfg: AppConfig, minutes: float, poll: float = 60.0) -> threading.Thread:
    """A thread that ends the process (exit code 4, which the run monitor's driver restarts) when nothing has moved
    for `minutes`: no decision written to runs/live and no local server writing its log. It works when the event
    loop itself is wedged, which stall_guard can't: on 10 Oct a failed server start cancelled the other stream
    mid-game, poke-env's connection thread died (InvalidStateError) and the process hung for 97 minutes."""
    live = Path(app_cfg.telemetry.output_dir) / "live"
    server_logs = Path(app_cfg.local_llm.gen).parent / "tools" / "llm" / "llamacpp" / "logs"
    started = time.time()

    def last_activity() -> float:  # live/heartbeat: the round robin waiting for resting models on purpose
        files = [*live.glob("*.jsonl"), live / "heartbeat", *server_logs.glob("server_*.log")]
        return max([started] + [f.stat().st_mtime for f in files if f.exists()])

    def watch() -> None:
        while True:
            time.sleep(poll)
            idle = (time.time() - last_activity()) / 60
            if idle > minutes:
                print(f"{time.strftime('%Y-%m-%d %H:%M')} RUN STALLED: nothing moved for {idle:.0f} minutes; "
                      "exiting so the driver restarts the run", flush=True)
                os._exit(4)

    thread = threading.Thread(target=watch, name="watchdog", daemon=True)
    thread.start()
    return thread


class RunStalled(RunHalted):
    """No player has decided anything for ladder.stall_minutes: the games can't go on. Seen on 9 Oct, when
    poke-env's connection loop crashed on a Windows socket error ("I/O operation has been aborted") and every player
    waited for a message that never came. Only a new process recovers, so the run exits (code 4) and its driver
    restarts it; the stuck games are replayed."""


async def stall_guard(players: List, minutes: float, label: str, poll: float = 30.0) -> None:
    """Raises RunStalled once no player has recorded a decision for `minutes` (a new game counts as progress)."""
    last, since = None, time.monotonic()
    while True:
        await asyncio.sleep(poll)
        state = tuple((id(p.breadcrumbs_recorder), len(p.breadcrumbs_recorder.breadcrumbs) if p.breadcrumbs_recorder else 0)
                      for p in players)
        if state != last:
            last, since = state, time.monotonic()
        elif time.monotonic() - since > minutes * 60:
            raise RunStalled(f"{label}: no decision for {minutes:.0f} minutes; the connection to Showdown is dead")


@dataclass
class LadderState:
    matches: List[MatchTelemetry]
    outcomes: List[Outcome]
    ratings: Dict[str, Rating]
    pair_games: Dict[frozenset, int]
    rules_mismatch: int = 0  # games left out because their recorded rules differ from their version's
    superseded: int = 0  # games left out because a player's per-model rules changed since (replayed under the new)

    def games(self, a: str, b: str) -> int:
        return self.pair_games.get(frozenset((a, b)), 0)

    @property
    def void_count(self) -> int:
        return len(self.matches) - len(self.outcomes)


def version_state(app_cfg: AppConfig, rate: bool = True) -> LadderState:
    """Every match of the ruleset version being played, rated against its benchmark's anchor (rate=False: counted
    only, no ratings)."""
    return versions_state(app_cfg, [app_cfg.ruleset.version], rate, anchor=app_cfg.anchor_for())


def versions_state(app_cfg: AppConfig, versions: List[str], rate: bool = True,
                   anchor: Optional[str] = None) -> LadderState:
    """Every match of these ruleset versions, rated together (a leaderboard). A game whose recorded rules differ
    from its version's stored rules is left out and counted. rate=False skips the ratings (and their bootstrap,
    seconds of CPU) for callers that only count games."""
    matches, mismatch, superseded = [], 0, 0
    for version in versions:
        stored = stored_rules(version)
        for m in load_matches(app_cfg.telemetry.output_dir, version):
            if stored is not None and not same_rules(m.ruleset, stored):
                mismatch += 1
            elif not settings_current(m, app_cfg):
                superseded += 1
            else:
                matches.append(m)
    outcomes = rated_outcomes(matches, app_cfg.ladder.max_autopilot)
    ratings = compute_ratings(
        outcomes,
        anchor=anchor or app_cfg.ladder.anchor,
        anchor_rating=app_cfg.ladder.anchor_rating,
        bootstrap_samples=app_cfg.ladder.bootstrap_samples,
    ) if rate else {}
    return LadderState(matches, outcomes, ratings, games_between(outcomes), mismatch, superseded)


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
        if a.is_model and k != config_id and k not in exclude and k in ratings and ratings[k].ranked
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda k: abs(ratings[k].rating - me.rating))


def fill_pairs(state: LadderState, agents: Dict[str, AgentConfig], free_only: bool = True) -> List[Tuple[str, str]]:
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
    """This version's matches between two registry entries, oldest first, void ones included."""
    pair = {id_a, id_b}
    return [
        m for m in load_matches(app_cfg.telemetry.output_dir, app_cfg.ruleset.version)
        if m.player("p1") and m.player("p2") and {m.player("p1").config_id, m.player("p2").config_id} == pair
    ]


class ModelUnavailable(RunHalted):
    """Models that can't play now: a provider limit (credits, a daily quota, a rate limit that outlasted the backoff),
    games going void because a model keeps failing (its provider down), or a local server that won't start. The round
    robin rests them and tries their pairs again later (ladder.rest_minutes); placement and fill stop."""

    def __init__(self, message: str, config_ids: List[str]):
        super().__init__(message)
        self.config_ids = config_ids


def check_halt(label: str, players: List, new_matches: List[MatchTelemetry], max_autopilot: float) -> None:
    """Raises ModelUnavailable when a player hit a provider limit, or the last two games of this set were void
    because the same model was on autopilot in both; RunHalted when they were void for another reason."""
    for player in players:
        limit = getattr(player, "provider_limit", None)
        if limit:
            raise ModelUnavailable(f"{label}: provider limit reached: {limit}", [player.identity.config_id])
    last = new_matches[-2:]
    reasons = [void_reason(m, max_autopilot) for m in last]
    if len(reasons) == 2 and all(reasons):
        failing = [{p.config_id for p in m.players if autopilot_rate(m, p.role) > max_autopilot} for m in last]
        culprits = sorted(failing[0] & failing[1])
        if culprits:
            raise ModelUnavailable(f"{label}: two void games in a row ({reasons[-1]})", culprits)
        raise RunHalted(f"{label}: two void games in a row ({reasons[-1]})")


def lane_count(agent_a: AgentConfig, agent_b: AgentConfig, app_cfg: AppConfig, remaining: int) -> int:
    """Games of a set played at once: the ladder's setting, capped by either player's own limit."""
    limits = [app_cfg.ladder.parallel_games, remaining, agent_a.max_parallel_games, agent_b.max_parallel_games]
    return min(n for n in limits if n is not None)


def games_played(app_cfg: AppConfig, config_id: str) -> int:
    """Every game this registry entry has played in the version being played, voided ones included (each one cost
    tokens). The cap counts per version, so a new benchmark gets its own budget."""
    return sum(1 for m in load_matches(app_cfg.telemetry.output_dir, app_cfg.ruleset.version)
               if any(p.config_id == config_id for p in m.players) and settings_current(m, app_cfg))


def cap_exempt(app_cfg: AppConfig, a: str, b: str) -> bool:
    """Whether this pair plays even past a player's game cap (ladder.cap_exempt_pairs, ladder.best_of_three)."""
    return any({a, b} == set(pair) for pair in app_cfg.ladder.cap_exempt_pairs + best_of_three(app_cfg))


def best_of_three(app_cfg: AppConfig) -> List[List[str]]:
    """The pairs playing a best of three in the version being played."""
    return app_cfg.ladder.best_of_three.get(app_cfg.ruleset.version, [])


def pair_target(app_cfg: AppConfig, state: LadderState, a: str, b: str, games_per_pair: int) -> int:
    """How many valid games this pair plays in the round robin: games_per_pair, or for a best of three
    (ladder.best_of_three) a deciding third game once its first two stand level."""
    if not any({a, b} == set(pair) for pair in best_of_three(app_cfg)):
        return games_per_pair
    games = [o for o in state.outcomes if {o.p1, o.p2} == {a, b}]
    score_a = sum(o.score_p1 if o.p1 == a else 1 - o.score_p1 for o in games)
    return max(games_per_pair, 3 if len(games) >= 2 and score_a == len(games) / 2 else 2)


def games_left(app_cfg: AppConfig, agent: AgentConfig) -> int:
    cap = agent.cap(app_cfg.ruleset.version)
    return max(cap - games_played(app_cfg, agent.name), 0) if cap is not None else 10**9


def own_team(agent: AgentConfig, app_cfg: AppConfig) -> Team:
    """The team a model built itself (draft mode) under this ruleset version: its legal team, or the repaired one."""
    record = load_drafts(version=app_cfg.ruleset.version, fmt=app_cfg.ruleset.format).get(agent.name)
    text = playable_team(record) if record else None
    if not text:
        raise ValueError(f"{agent.name} has no team of its own yet: run `rotomarena teams draft {agent.name}`")
    return parse_smogon_team(text, name=f"{agent.display_name or agent.name}'s team")


def set_teams(agent_a: AgentConfig, agent_b: AgentConfig, app_cfg: AppConfig) -> Tuple[Team, Team]:
    """The two teams of a set. Draft mode: each model's own team, except that a control bot (which can't build one)
    plays its opponent's, so only the play differs between them. Fixed mode: the ruleset's two teams."""
    if app_cfg.ruleset.team_mode == "random":
        return None, None  # the format deals every player a random team
    if app_cfg.ruleset.team_mode != "draft":
        return tuple(load_preset_team(t) for t in app_cfg.ruleset.teams)
    if agent_a.role == "control":
        team = own_team(agent_b, app_cfg)
        return team, team
    if agent_b.role == "control":
        team = own_team(agent_a, app_cfg)
        return team, team
    return own_team(agent_a, app_cfg), own_team(agent_b, app_cfg)


def round_robin_ids(app_cfg: AppConfig, log: Callable[[str], None] = lambda msg: None) -> List[str]:
    """Who plays the round robin: every active model with a team of its own under this version (a model without one
    yet, say its provider was down, joins later), and the active control bots, which borrow their opponent's."""
    ids = [k for k, a in app_cfg.agents.items() if a.is_model and a.active]
    if app_cfg.ruleset.team_mode == "draft":
        drafts = load_drafts(version=app_cfg.ruleset.version, fmt=app_cfg.ruleset.format)
        for k in [k for k in ids if not playable_team(drafts.get(k) or {})]:
            log(f"{k} sits out: no team of its own under {app_cfg.ruleset.version} yet (rotomarena teams draft {k})")
            ids.remove(k)
    return ids + [k for k, a in app_cfg.agents.items() if a.role == "control" and a.active]


def round_robin_pairs(ids: List[str]) -> List[Tuple[str, str]]:
    """Every pair once, in rounds where each model plays at most one game (the circle method), so a run stopped
    halfway has given every model about the same number of games."""
    players: List[Optional[str]] = list(ids) + ([None] if len(ids) % 2 else [])
    n, pairs = len(players), []
    for r in range(n - 1):
        for i in range(n // 2):
            a, b = players[i], players[n - 1 - i]
            if a and b:
                pairs.append((a, b) if r % 2 == 0 else (b, a))
        players = [players[0], players[-1], *players[1:-1]]
    return pairs


def quick_pairs_first(pairs: List[Tuple[str, str]], app_cfg: AppConfig) -> List[Tuple[str, str]]:
    """The quickest pairs first, so most models are rated early: a local model's game takes tens of minutes, an API
    model's a few. A model is rated once its games connect it to the anchor, so the anchor's pairs with API models
    open, then API models among themselves, then pairs with one local model, the anchor's with local models, and
    local against local last. Within a tier the balanced rounds keep their order. Pairs with a model in
    ladder.play_last (slow local models) come after all of those, fewest such models first."""
    anchor = app_cfg.anchor_for()

    def tier(pair: Tuple[str, str]) -> int:
        local = [x for x in pair if app_cfg.agents[x].provider == "local"]
        others = [x for x in local if x != anchor]
        if anchor in pair:
            return 0 if not others else 3
        return {0: 1, 1: 2}.get(len(local), 4)

    last = set(app_cfg.ladder.play_last)
    return sorted(pairs, key=lambda pair: (sum(x in last for x in pair), tier(pair)))


def strongest_opponents(pairs: List[Tuple[str, str]], app_cfg: AppConfig, state: LadderState,
                         games_per_pair: int, log: Callable[[str], None] = print) -> List[Tuple[str, str]]:
    """A model whose game cap can't cover all its pairs spends it on its strongest opponents: the highest rated,
    down the ladder while the cap lasts (models not rated yet last); its pairs with the rest are dropped. Sonnet and
    Opus play only the top 5 in c4; without this the order of the rounds decided whom a capped model met. Games
    already played count against the cap wherever they were played."""
    version = app_cfg.ruleset.version
    drop: set = set()
    for x, agent in app_cfg.agents.items():
        cap = agent.cap(version)
        mine = [p for p in pairs if x in p]
        if cap is None or not mine:
            continue
        exempt = [p for p in mine if cap_exempt(app_cfg, *p)]
        budget = cap - sum(max(pair_target(app_cfg, state, *p, games_per_pair), state.games(*p)) for p in exempt)
        ranked = [p for p in mine if p not in exempt]

        def strength(pair: Tuple[str, str]) -> float:
            other = state.ratings.get(pair[0] if pair[1] == x else pair[1])
            return float("-inf") if other is None or other.rating is None else other.rating

        ranked.sort(key=strength, reverse=True)
        kept_cost, dropped = 0, []
        for i, p in enumerate(ranked):
            cost = max(games_per_pair, state.games(*p))
            # keeping it must leave room for the games already played in every pair after it, should those be dropped
            if kept_cost + cost + sum(state.games(*q) for q in ranked[i + 1:]) <= budget:
                kept_cost += cost
            else:
                dropped.append(p)
        if dropped:
            drop.update(dropped)
            names = [q[0] if q[1] == x else q[1] for q in dropped]
            log(f"{x}: its cap of {cap} games covers its {len(ranked) - len(dropped)} strongest opponents; "
                f"it skips {', '.join(names)}")
    return [p for p in pairs if p not in drop]


def split_streams(pairs: List[Tuple[str, str]], app_cfg: AppConfig) -> Tuple[list, list]:
    """(pairs with a local model, the rest), each keeping its order: the first need the GPU, the second only APIs,
    so the two play side by side."""
    indexed = list(enumerate(pairs, 1))
    gpu = [(i, p) for i, p in indexed if local_servers.local_agents([app_cfg.agents[x] for x in p])]
    return gpu, [(i, p) for i, p in indexed if (i, p) not in gpu]


async def round_robin(app_cfg: AppConfig, games_per_pair: int, log: Callable[[str], None] = print) -> None:
    """Every model plays every other one (and the control bot), pair by pair in balanced rounds, so coverage grows evenly.
    A pair's games (one from each side) run at once: each model's requests are then batched by its server, which
    for two local models costs about one game's time instead of two. Pairs with a local model and pairs without
    one play in two streams at once (the second never touches the GPU). Resumable."""
    pairs = quick_pairs_first(round_robin_pairs(round_robin_ids(app_cfg, log)), app_cfg)
    pairs = strongest_opponents(pairs, app_cfg, version_state(app_cfg), games_per_pair, log)
    gpu, api = split_streams(pairs, app_cfg)
    playing: Dict[Tuple[str, str], int] = {}  # sets now playing -> the game count each stops at

    def promised(x: str) -> int:
        """Games of model x the sets now playing will still add, so the other stream leaves them out of its cap."""
        state = version_state(app_cfg, rate=False)
        return sum(max(stop - state.games(*pair), 0) for pair, stop in playing.items() if x in pair)

    rest_until: Dict[str, float] = {}  # models resting (ModelUnavailable) -> when to try them again
    rests: Dict[str, int] = {}  # how often each has rested this run
    gave_up: set = set()  # models that rested ladder.max_rests times: their pairs wait for the next run
    heartbeat = Path(app_cfg.telemetry.output_dir) / "live" / "heartbeat"  # the watchdog: waiting, not hung

    def rest(config_ids: List[str], why: str) -> None:
        for x in config_ids:
            rests[x] = rests.get(x, 0) + 1
            if rests[x] > app_cfg.ladder.max_rests:
                gave_up.add(x)
                log(f"{time.strftime('%Y-%m-%d %H:%M')} {x} still unavailable after {app_cfg.ladder.max_rests} rests: "
                    f"its pairs wait for the next run ({why[:200]})")
                continue
            minutes = min(app_cfg.ladder.rest_minutes * 2 ** (rests[x] - 1), 240)
            rest_until[x] = time.time() + minutes * 60
            log(f"{time.strftime('%Y-%m-%d %H:%M')} {x} sits out for {minutes:.0f} min, then its pairs are tried "
                f"again: {why[:300]}")

    def unavailable(pair: Tuple[str, str]) -> set:
        return {x for x in pair if x in gave_up or rest_until.get(x, 0) > time.time()}
    # A model limited to one game at a time (Gemma, for its provider's rate limit) plays in one stream at a time
    single = {k: asyncio.Lock() for k, a in app_cfg.agents.items() if a.max_parallel_games == 1}

    async def stream(items: list) -> None:
        queue = list(items)  # pairs still to play; a resting model's pairs wait at the back
        while queue:
            queue = [item for item in queue if not set(item[1]) & gave_up]
            ready = [item for item in queue if not unavailable(item[1])]
            if not ready:
                if not queue:
                    break
                wake = min(rest_until[x] for _, pair in queue for x in pair if rest_until.get(x, 0) > time.time())
                log(f"{time.strftime('%Y-%m-%d %H:%M')} only resting models' pairs are left in this stream: waiting "
                    f"{(wake - time.time()) / 60:.0f} min")
                while time.time() < wake:
                    heartbeat.parent.mkdir(parents=True, exist_ok=True)
                    heartbeat.touch()
                    await asyncio.sleep(min(60, max(wake - time.time(), 1)))
                continue
            item = ready[0]
            queue.remove(item)
            i, (a, b) = item
            async with contextlib.AsyncExitStack() as held:
                for x in sorted({a, b} & set(single)):  # always in the same order: no deadlock
                    await held.enter_async_context(single[x])
                while True:  # once more for a best of three's deciding game
                    state = version_state(app_cfg, rate=False)  # counting only: every pair asks
                    done, target = state.games(a, b), pair_target(app_cfg, state, a, b, games_per_pair)
                    if done >= target:
                        break
                    stop = target
                    if not cap_exempt(app_cfg, a, b):
                        for x in (a, b):
                            if app_cfg.agents[x].max_games is not None:
                                stop = min(stop, done + games_left(app_cfg, app_cfg.agents[x]) - promised(x))
                    if stop <= done:
                        log(f"pair {i}/{len(pairs)}: {a} vs {b} skipped: a model reached its game cap")
                        break
                    log(f"pair {i}/{len(pairs)}: {a} vs {b} ({done}/{target} valid games so far)")
                    playing[(a, b)] = stop
                    try:
                        await play_set(a, b, app_cfg, done, games=stop)
                    except ModelUnavailable as e:  # it sits out; the others play on, its pairs come back later
                        rest(e.config_ids, str(e))
                        queue.append(item)
                        break
                    except local_servers.ServerStartFailed as e:  # its local model sits out like an unreachable one
                        rest([x.name for x in local_servers.local_agents([app_cfg.agents[a], app_cfg.agents[b]])],
                             f"its local server didn't start ({str(e).splitlines()[0]})")
                        queue.append(item)
                        break
                    finally:
                        del playing[(a, b)]

    try:
        async with asyncio.TaskGroup() as group:  # a halt in either stream stops both
            group.create_task(stream(gpu))
            group.create_task(stream(api))
    except ExceptionGroup as failed:
        raise failed.exceptions[0] from failed  # callers catch RunHalted itself


# {config id: the lane numbers its players use right now}. Showdown names must be unique, so a model playing two
# games at once (lanes of a set, or both streams) numbers all but one; a model playing one game keeps a clean name.
_lanes_in_use: Dict[str, set] = {}


def take_lane(config_id: str) -> int:
    """The lowest lane number this model isn't using (1: its plain name)."""
    used = _lanes_in_use.setdefault(config_id, set())
    lane = next(n for n in range(1, len(used) + 2) if n not in used)
    used.add(lane)
    return lane


def release_lane(config_id: str, lane: int) -> None:
    _lanes_in_use.get(config_id, set()).discard(lane)


def rounds(first_game: int, n_games: int, parallel: int) -> List[List[int]]:
    """The games of a set (0-based, as in series_schedule) grouped into rounds played at once."""
    games = list(range(first_game, first_game + n_games))
    return [games[i:i + parallel] for i in range(0, len(games), parallel)]


async def play_set(id_a: str, id_b: str, app_cfg: AppConfig, already_played: int, games: Optional[int] = None) -> int:
    """Plays the rest of a set between two registry entries; returns how many games were played.
    Up to ladder.parallel_games games run at once, each by its own pair of players (a lane). Between rounds the
    run checks for halts and restarts crashed local servers, as it did between games when they ran one by one."""
    remaining = (games or app_cfg.ladder.games_per_set) - already_played
    agent_a, agent_b = app_cfg.agents[id_a], app_cfg.agents[id_b]
    if not cap_exempt(app_cfg, id_a, id_b):
        remaining = min([remaining] + [games_left(app_cfg, a) for a in (agent_a, agent_b) if a.max_games is not None])
    if remaining <= 0:
        return 0
    taken: List[Tuple[str, int]] = []  # (config id, lane number) this set holds, released when it ends
    lane_numbers = []
    for _ in range(lane_count(agent_a, agent_b, app_cfg, remaining)):
        lane_a = take_lane(id_a)
        lane_b = lane_a if id_b == id_a else take_lane(id_b)  # a mirror match tags its two sides itself
        taken += [(id_a, lane_a)] + ([] if id_b == id_a else [(id_b, lane_b)])
        lane_numbers.append((lane_a, lane_b))
    lanes = [create_players(agent_a, agent_b, app_cfg, lane=a, lane_b=b) for a, b in lane_numbers]
    players = [p for lane in lanes for p in lane]
    own = app_cfg.ruleset.team_mode == "draft"
    team_1, team_2 = set_teams(agent_a, agent_b, app_cfg)
    runner = MatchRunner(telemetry_config=app_cfg.telemetry, rules=current_rules(app_cfg))
    played_before = len(_pair_matches(app_cfg, id_a, id_b))

    def halt_check() -> None:
        new = _pair_matches(app_cfg, id_a, id_b)[played_before:]
        check_halt(f"{id_a} vs {id_b}", players, new, app_cfg.ladder.max_autopilot)

    try:
        for round_games in rounds(already_played, remaining, len(lanes)):
            halt_check()
            if local_servers.local_agents([agent_a, agent_b]):  # an API pair leaves the GPU stream's servers alone
                local_servers.prepare([agent_a, agent_b], app_cfg)
            try:
                async with asyncio.TaskGroup() as group:  # one failed game cancels the round; the set resumes later
                    games = [group.create_task(runner.run_game(player_a, player_b, team_1, team_2, game, own_teams=own))
                             for (player_a, player_b), game in zip(lanes, round_games)]
                    guard = group.create_task(stall_guard(players, app_cfg.ladder.stall_minutes, f"{id_a} vs {id_b}"))
                    await asyncio.gather(*games)
                    guard.cancel()
            except ExceptionGroup as failed:
                raise failed.exceptions[0] from failed  # the run log shows the actual error
        halt_check()
    finally:
        for player in players:
            try:  # bounded: after a stall the connection loop is dead and would never answer
                await asyncio.wait_for(player.ps_client.stop_listening(), timeout=10)
            except Exception:
                pass
        for config_id, lane in taken:
            release_lane(config_id, lane)
    return remaining


async def place(config_id: str, app_cfg: AppConfig, log: Callable[[str], None] = print,
                with_control: bool = False) -> LadderState:
    """Placement: a short set against the control bot (cheap models only), a set against each anchor and a
    sparring partner, then one against the closest-rated LLM.
    Sets already played under this version are skipped, so an interrupted placement resumes where it stopped."""
    agents = app_cfg.agents
    if config_id not in agents:
        raise ValueError(f"'{config_id}' is not in the agents registry ({', '.join(sorted(agents))})")

    state = version_state(app_cfg)
    for opponent in control_opponents(config_id, app_cfg, force=with_control, log=log):
        done = state.games(config_id, opponent)
        log(f"{config_id} vs {opponent} (control): {done}/{app_cfg.ladder.control_games} valid games so far")
        await play_set(config_id, opponent, app_cfg, done, games=app_cfg.ladder.control_games)
    for opponent in fixed_placement_opponents(config_id, agents):
        done = state.games(config_id, opponent)
        log(f"{config_id} vs {opponent}: {done}/{app_cfg.ladder.games_per_set} valid games so far")
        await play_set(config_id, opponent, app_cfg, done)

    state = version_state(app_cfg)
    rival = closest_rated_llm(config_id, agents, state.ratings, exclude=fixed_placement_opponents(config_id, agents))
    if rival is None:
        log("No other ranked LLM yet, so placement ends after the fixed opponents.")
        return state
    done = state.games(config_id, rival)
    log(f"Closest-rated LLM: {rival} ({state.ratings[rival].rating:.0f}). {done}/{app_cfg.ladder.games_per_set} played so far")
    await play_set(config_id, rival, app_cfg, done)
    return version_state(app_cfg)


async def fill(app_cfg: AppConfig, budget: int, free_only: bool = True, log: Callable[[str], None] = print) -> int:
    """Spends up to `budget` games on the pairs whose ratings are least separated. Returns games played."""
    played = 0
    while played < budget:
        state = version_state(app_cfg)
        pairs = fill_pairs(state, app_cfg.agents, free_only)
        if not pairs:
            log("No overlapping pairs to play.")
            break
        a, b = pairs[0]
        games = min(app_cfg.ladder.games_per_set, budget - played)
        log(f"Top-up: {a} vs {b} ({games} games)")
        played += await play_set(a, b, app_cfg, already_played=0, games=games)
    return played


def describe_void_matches(state: LadderState, max_autopilot: float) -> List[Tuple[str, str]]:
    return [(m.match_id, reason) for m in state.matches if (reason := void_reason(m, max_autopilot))]
