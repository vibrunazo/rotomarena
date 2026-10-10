"""Direct LLM Agent with Single-Call Chain-of-Thought (CoT) Reasoning."""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.llm.client import LLMClient, ProviderLimitError, to_id
from rotomarena.llm.prompts import format_battle_state, format_team_preview, system_prompt_for


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
        thinking_budget: Optional[int] = None,
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
        self.thinking_budget = thinking_budget
        # Set when the provider stops answering (credits, quota, sustained rate limit); the ladder stops on it.
        self.provider_limit: Optional[ProviderLimitError] = None

    async def _ask(self, battle_state_str: str):
        """One decision from the model. After a provider limit, the rest of the game skips the API: every later
        turn would fail the same way, only slower."""
        if self.provider_limit:
            raise self.provider_limit
        try:
            return await self.llm_client.generate_cot_decision(
                battle_state_str=battle_state_str,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_output_tokens,
                reasoning=self.reasoning,
                thinking_budget=self.thinking_budget,
                system_prompt=system_prompt_for(self.format, self.pick),
            )
        except ProviderLimitError as e:
            self.provider_limit = e
            raise

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        """Queries the LLM, then plays its action only if it exactly matches a legal one."""
        try:
            decision = await self._ask(format_battle_state(battle, self.brought.get(battle.battle_tag), self.pick))
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
                chosen_order = self.create_order(move, terastallize=decision.terastallize and battle.can_tera,
                                                 mega=decision.mega_evolve and battle.can_mega_evolve)
        elif decision.action_type == "SWITCH":
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

    async def teampreview(self, battle: Battle) -> str:
        """The model picks its lead; the rest of the team keeps its order. Failures lead with the first
        Pokémon, which is what Showdown itself does when a player doesn't choose. In a bring-N format it picks the
        N it brings instead (bring_preview)."""
        members = list(battle.team.values())
        if self.pick and self.pick < len(members):
            return await self.bring_preview(battle, members)
        lead, source, note, decision = 0, "model", "", None
        try:
            decision = await asyncio.wait_for(self._ask(format_team_preview(battle)), timeout=self.turn_timeout)
        except asyncio.TimeoutError:
            source, note = "timeout", f"[TIMEOUT] No lead chosen within {self.turn_timeout:.0f}s."
        except Exception as e:
            source, note = "api_error", f"[API ERROR] {e}."
        if decision is not None:
            if decision.parse_error:
                source, note = "parse_error", f"[PARSE ERROR] {decision.parse_error}."
            else:
                # A lead is the only legal action here, so a team member's name counts whatever the keyword
                # (small models wrote "MOVE: dragonite"); only the Pokémon has to be right.
                match = next((i for i, m in enumerate(members) if to_id(m.species) == decision.target), None)
                if match is None:
                    source, note = "invalid", f"[INVALID] '{decision.action_type}: {decision.target}' is not a legal lead."
                else:
                    lead = match

        message = self.bring_order(battle, [lead])
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=SimpleNamespace(message=f"{message} lead={members[lead].species}"),
            reasoning=decision.reasoning if source == "model" else f"{note} Leading with the first Pokémon.",
            decision_source=source,
            llm_metrics=decision.metrics.model_dump() if decision and decision.metrics else None,
            hidden_reasoning=decision.hidden_reasoning if decision else "",
        )
        return message

    async def bring_preview(self, battle: Battle, members: list) -> str:
        """Bring N of the team: the model answers BRING: a, b, c (the first leads). Names it gets wrong or misses
        are filled from the team's order, and the turn is recorded as invalid; no usable answer brings the first N."""
        chosen, source, note, decision = [], "model", "", None
        try:
            decision = await asyncio.wait_for(self._ask(format_team_preview(battle, self.pick)), timeout=self.turn_timeout)
        except asyncio.TimeoutError:
            source, note = "timeout", f"[TIMEOUT] No team chosen within {self.turn_timeout:.0f}s."
        except Exception as e:
            source, note = "api_error", f"[API ERROR] {e}."
        if decision is not None:
            text = decision.raw_response or ""
            block = re.search(r"<decision>(.*?)(?:</decision>|$)", text, re.S | re.I)
            line = re.search(r"BRING\s*:\s*(.+)", block.group(1) if block else text, re.I)
            if not line:
                source, note = "parse_error", "[PARSE ERROR] No BRING: line."
            else:
                ids = {to_id(m.species): i for i, m in enumerate(members)}
                names = [n.strip(" *.`") for n in re.split(r"[,/]", line.group(1)) if n.strip(" *.`")]
                for name in names:
                    i = ids.get(to_id(name))
                    if i is not None and i not in chosen and len(chosen) < self.pick:
                        chosen.append(i)
                if len(chosen) < self.pick:
                    source, note = "invalid", (f"[INVALID] 'BRING: {line.group(1).strip()}' names {len(chosen)} of the "
                                               f"{self.pick} Pokémon it brings; the rest come from the team's order.")
        message = self.bring_order(battle, chosen)
        brought = [members[int(c) - 1].species for c in message.split()[1]]
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=SimpleNamespace(message=f"{message} bring={','.join(brought)}"),
            reasoning=decision.reasoning if source == "model" else
            f"{note} Bringing {', '.join(brought)}." + (f"\n{decision.reasoning}" if decision and decision.reasoning else ""),
            decision_source=source,
            llm_metrics=decision.metrics.model_dump() if decision and decision.metrics else None,
            hidden_reasoning=decision.hidden_reasoning if decision else "",
        )
        return message
