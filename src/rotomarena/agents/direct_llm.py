"""Direct LLM Agent with Single-Call Chain-of-Thought (CoT) Reasoning."""

from __future__ import annotations

from typing import Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.llm.client import LLMClient, to_id
from rotomarena.llm.prompts import format_battle_state


class DirectLLMPlayer(BaseBenchmarkPlayer):
    """
    Direct LLM Agent: one chat completion per turn, answered as <thought> + <decision>.
    The decision must name a legal action exactly; anything else plays the default move.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        player_name: str = "DirectLLMBot",
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        reasoning: str = "off",
        battle_format: str = "gen9ou",
        team: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            player_name=player_name,
            agent_type="direct_llm",
            battle_format=battle_format,
            team=team,
            **kwargs,
        )
        self.llm_client = llm_client
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.reasoning = reasoning

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        """Queries the LLM, then plays its action only if it exactly matches a legal one."""
        try:
            decision = await self.llm_client.generate_cot_decision(
                battle_state_str=format_battle_state(battle),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_output_tokens,
                reasoning=self.reasoning,
            )
        except Exception as e:
            fallback_order = self.choose_default_order(battle)
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning=f"[API ERROR] {e}. Default move played.",
                decision_source="api_error",
            )
            return fallback_order

        llm_metrics = decision.metrics.model_dump() if decision.metrics else None

        if decision.parse_error:
            fallback_order = self.choose_default_order(battle)
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning=f"[PARSE ERROR] {decision.parse_error}. Default move played.\n"
                f"Raw answer:\n{decision.raw_response[-2000:]}",
                decision_source="parse_error",
                llm_metrics=llm_metrics,
                hidden_reasoning=decision.hidden_reasoning,
            )
            return fallback_order

        chosen_order: Optional[BattleOrder] = None
        if decision.action_type == "MOVE":
            move = next((m for m in battle.available_moves if m.id == decision.target), None)
            if move is not None:
                chosen_order = self.create_order(move, terastallize=decision.terastallize and battle.can_tera)
        else:
            mon = next((m for m in battle.available_switches if to_id(m.species) == decision.target), None)
            if mon is not None:
                chosen_order = self.create_order(mon)

        if chosen_order is None:
            fallback_order = self.choose_default_order(battle)
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning=f"[INVALID] '{decision.action_type}: {decision.target}' is not a legal action. "
                f"Default move played.\nOriginal reasoning:\n{decision.reasoning}",
                decision_source="invalid",
                llm_metrics=llm_metrics,
                hidden_reasoning=decision.hidden_reasoning,
            )
            return fallback_order

        self.record_turn_telemetry(
            battle=battle,
            chosen_order=chosen_order,
            reasoning=decision.reasoning,
            llm_metrics=llm_metrics,
            hidden_reasoning=decision.hidden_reasoning,
        )
        return chosen_order
