"""PokéChamp Minimax Agent Implementation."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.llm.client import LLMClient
from rotomarena.search.minimax import PokeChampSearchEngine, SearchTreeTelemetry


class PokeChampPlayer(BaseBenchmarkPlayer):
    """
    PokéChamp Agent utilizing Minimax tree search with configurable depth,
    Gen 9 type heuristics, and optional LLM state evaluation priors.
    """

    def __init__(
        self,
        player_name: str = "PokeChampBot",
        depth: int = 1,
        use_llm_prior: bool = False,
        llm_client: Optional[LLMClient] = None,
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
        self.depth = depth
        self.use_llm_prior = use_llm_prior
        self.llm_client = llm_client
        self.search_engine = PokeChampSearchEngine(
            depth=depth,
            use_llm_prior=use_llm_prior,
            llm_client=llm_client,
            evaluation_weights=evaluation_weights,
        )

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        """Asynchronously executes Minimax search and records telemetry."""
        order, telemetry = await self.search_engine.search(battle)

        reasoning = (
            f"PokéChamp (Depth {self.depth}) selected '{telemetry.best_action}' "
            f"with evaluation score {telemetry.best_score:.3f}. "
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

    def choose_move(self, battle: Battle) -> BattleOrder:
        """
        poke-env entrypoint for move selection.
        Returns coroutine or BattleOrder.
        """
        return self._async_choose_move(battle)  # type: ignore
