"""PokéChamp search agent (no LLM): one-turn maximin over sampled opponent replies.

Implements the minimax design of PokéChamp by Seth Karten, Andy Luu Nguyen and Chi Jin (ICML 2025,
https://github.com/sethkarten/pokechamp) without its language model; no code from their repository. See CREDITS.md."""

from __future__ import annotations

from typing import Dict, Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.search.minimax import PokeChampSearchEngine


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
