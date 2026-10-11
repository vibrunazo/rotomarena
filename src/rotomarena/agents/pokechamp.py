"""PokéChamp search agent (no LLM): one-turn maximin over sampled opponent replies.

Implements the minimax design of PokéChamp by Seth Karten, Andy Luu Nguyen and Chi Jin (ICML 2025,
https://github.com/sethkarten/pokechamp) without its language model; no code from their repository. See CREDITS.md."""

from __future__ import annotations

import statistics
from types import SimpleNamespace
from typing import Dict, Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.search.minimax import PokeChampSearchEngine
from rotomarena.search.simulator import estimate_best_hit


class PokeChampPlayer(BaseBenchmarkPlayer):
    """
    PokéChamp-style search agent: scores every legal action against the opponent's
    likeliest replies with Gen 9 heuristics. Free and deterministic, so it serves as a ladder anchor.
    """

    def __init__(
        self,
        player_name: str = "PokeChampBot",
        evaluation_weights: Optional[Dict[str, float]] = None,
        battle_format: str = "gen9ou",
        team: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            player_name=player_name,
            agent_type="pokechamp",
            battle_format=battle_format,
            team=team,
            **kwargs,
        )
        self.search_engine = PokeChampSearchEngine(evaluation_weights=evaluation_weights)

    def teampreview(self, battle: Battle) -> str:
        """Brings the Pokémon with the best matchups against the opponent's whole team (the damage each would deal
        minus what it would take, averaged over their six), a Mega Stone holder slightly preferred; the best one
        leads. Formats where all six play only choose the lead, the same way."""
        members = list(battle.team.values())
        opponents = list(getattr(battle, "teampreview_opponent_team", None) or [])

        def score(mon) -> float:
            if not opponents:
                return 0.0
            dealt = statistics.mean(estimate_best_hit(mon, o) for o in opponents)
            taken = statistics.mean(estimate_best_hit(o, mon) for o in opponents)
            mega = 0.1 if (mon.item or "").endswith("ite") and mon.item not in ("eviolite",) else 0.0
            return dealt - 0.7 * taken + mega

        scores = {i: score(m) for i, m in enumerate(members)}
        order = sorted(scores, key=lambda i: -scores[i])
        message = self.bring_order(battle, order)
        picked = [members[int(c) - 1].species for c in message.split()[1]]
        bring_n = self.pick and self.pick < len(members)
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=SimpleNamespace(message=f"{message} bring={','.join(picked)}" if bring_n
                                         else f"{message} lead={picked[0]}"),
            reasoning="Matchup scores (damage dealt minus taken, against their team): "
            + ", ".join(f"{members[i].species} {scores[i]:+.2f}" for i in order),
        )
        return message

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        """Runs the search and records its telemetry."""
        order, telemetry = await self.search_engine.search(battle)

        reasoning = (
            f"PokéChamp selected '{telemetry.best_action}' with evaluation score {telemetry.best_score:.3f}. "
            f"Evaluated {telemetry.nodes_evaluated} nodes ({telemetry.alpha_beta_cutoffs} cutoffs) "
            f"in {telemetry.search_duration_ms:.1f}ms."
        )
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=order,
            reasoning=reasoning,
            search_telemetry=telemetry.model_dump(),
        )
        return order
