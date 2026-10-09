"""Decision-model agent: one Choice question per turn over the legal actions, answered with probabilities."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Dict, Optional

from poke_env.battle import Battle
from poke_env.player import BattleOrder

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.llm.client import ProviderLimitError
from rotomarena.llm.decisions import Choice, DecisionClient, Question, Usage
from rotomarena.llm.prompts import format_battle_state, format_team_preview

TURN_INSTRUCTIONS = ("You are playing a competitive Pokémon battle on Pokémon Showdown as the side the state calls "
                     "YOUR. Which action this turn gives you the best chance to win the battle?")
LEAD_INSTRUCTIONS = ("You are about to play a competitive Pokémon battle on Pokémon Showdown with YOUR TEAM against "
                     "the OPPONENT'S TEAM. Which of your Pokémon should lead, to give you the best chance to win?")


def turn_options(battle: Battle) -> Dict[str, BattleOrder]:
    """{option key: order}: the same legal actions an LLM is shown, keyed the way it writes them."""
    options: Dict[str, tuple] = {}
    for m in battle.available_moves or []:
        options[f"MOVE: {m.id}"] = (m, False)
        if battle.can_tera:
            options[f"MOVE: {m.id} [TERA]"] = (m, True)
    for s in battle.available_switches or []:
        options[f"SWITCH: {s.species}"] = (s, False)
    return options


def _describe(key: str, target, tera: bool) -> str:
    if key.startswith("SWITCH"):
        return f"Switch to {target.species} ({round(target.current_hp_fraction * 100)}% HP)."
    m_type = target.type.name.title() if target.type else "Normal"
    move = f"use {target.id} ({m_type}, base power {target.base_power or '-'}, accuracy {target.accuracy or '-'})"
    return f"Terastallize, then {move}." if tera else f"{move[0].upper()}{move[1:]}."


class DecisionPlayer(BaseBenchmarkPlayer):
    """Shown the same battle state as the LLMs; answers with a probability for each legal action and plays the most
    likely one. It writes no thought: the breadcrumb's reasoning lists its top probabilities instead."""

    def __init__(self, client: DecisionClient, **kwargs):
        super().__init__(agent_type="decision", **kwargs)
        self.client = client
        self.provider_limit: Optional[ProviderLimitError] = None

    async def _ask(self, state: str, instructions: str, options: Dict[str, str]) -> tuple[Choice, Usage]:
        if self.provider_limit:
            raise self.provider_limit
        try:
            answers, usage = await self.client.choose(state, {"action": Question(instructions, options)})
        except ProviderLimitError as e:
            self.provider_limit = e
            raise
        return answers["action"], usage

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        options = turn_options(battle)
        if not options:
            return self.choose_default_order(battle)
        try:
            choice, usage = await self._ask(format_battle_state(battle), TURN_INSTRUCTIONS,
                                            {k: _describe(k, t, tera) for k, (t, tera) in options.items()})
        except Exception as e:
            fallback = self.choose_default_order(battle)
            self.record_turn_telemetry(battle=battle, chosen_order=fallback,
                                       reasoning=f"[API ERROR] {e}. Default move played.", decision_source="api_error")
            return fallback
        target, tera = options[choice.choice]
        order = self.create_order(target, terastallize=tera)
        self.record_turn_telemetry(battle=battle, chosen_order=order, reasoning=choice.summary(),
                                   llm_metrics=usage.metrics(self.client.provider_name).model_dump(),
                                   probabilities=choice.probabilities)
        return order

    async def teampreview(self, battle: Battle) -> str:
        members = list(battle.team.values())
        lead, source, note, choice, usage = 0, "model", "", None, None
        try:
            choice, usage = await asyncio.wait_for(self._ask(
                format_team_preview(battle), LEAD_INSTRUCTIONS,
                {f"LEAD: {m.species}": f"Lead with {m.species}." for m in members}), timeout=self.turn_timeout)
            lead = next(i for i, m in enumerate(members) if f"LEAD: {m.species}" == choice.choice)
        except asyncio.TimeoutError:
            source, note = "timeout", f"[TIMEOUT] No lead chosen within {self.turn_timeout:.0f}s."
        except Exception as e:
            source, note = "api_error", f"[API ERROR] {e}."
        order = [lead + 1] + [i + 1 for i in range(len(members)) if i != lead]
        for mon in members:
            mon._selected_in_teampreview = True
        message = "/team " + "".join(str(i) for i in order)
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=SimpleNamespace(message=f"{message} lead={members[lead].species}"),
            reasoning=choice.summary() if source == "model" else f"{note} Leading with the first Pokémon.",
            decision_source=source,
            llm_metrics=usage.metrics(self.client.provider_name).model_dump() if usage else None,
            probabilities=choice.probabilities if choice else None,
        )
        return message
