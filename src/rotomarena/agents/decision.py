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
BRING_INSTRUCTIONS = ("You bring {pick} of your Pokémon to this battle and have already chosen {chosen}. Which of the "
                      "rest should you also bring, to give you the best chance to win?")
LEAD_INSTRUCTIONS = ("You are about to play a competitive Pokémon battle on Pokémon Showdown with YOUR TEAM against "
                     "the OPPONENT'S TEAM. Which of your Pokémon should lead, to give you the best chance to win?")


def turn_options(battle: Battle) -> Dict[str, tuple]:
    """{option key: (move or Pokémon, "tera" / "mega" / None)}: the same legal actions an LLM is shown, keyed the way
    it writes them."""
    options: Dict[str, tuple] = {}
    for m in battle.available_moves or []:
        options[f"MOVE: {m.id}"] = (m, None)
        if battle.can_tera:
            options[f"MOVE: {m.id} [TERA]"] = (m, "tera")
        if battle.can_mega_evolve:
            options[f"MOVE: {m.id} [MEGA]"] = (m, "mega")
    for s in battle.available_switches or []:
        options[f"SWITCH: {s.species}"] = (s, None)
    return options


def _describe(key: str, target, special) -> str:
    if key.startswith("SWITCH"):
        return f"Switch to {target.species} ({round(target.current_hp_fraction * 100)}% HP)."
    m_type = target.type.name.title() if target.type else "Normal"
    move = f"use {target.id} ({m_type}, base power {target.base_power or '-'}, accuracy {target.accuracy or '-'})"
    if special == "tera":
        return f"Terastallize, then {move}."
    if special == "mega":
        return f"Mega Evolve, then {move}."
    return f"{move[0].upper()}{move[1:]}."


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
            choice, usage = await self._ask(format_battle_state(battle, self.brought.get(battle.battle_tag), self.pick,
                                                                self.battle_state),
                                            TURN_INSTRUCTIONS,
                                            {k: _describe(k, t, tera) for k, (t, tera) in options.items()})
        except Exception as e:
            fallback = self.choose_default_order(battle)
            self.record_turn_telemetry(battle=battle, chosen_order=fallback,
                                       reasoning=f"[API ERROR] {e}. Default move played.", decision_source="api_error")
            return fallback
        target, special = options[choice.choice]
        order = self.create_order(target, terastallize=special == "tera", mega=special == "mega")
        self.record_turn_telemetry(battle=battle, chosen_order=order, reasoning=choice.summary(),
                                   llm_metrics=usage.metrics(self.client.provider_name).model_dump(),
                                   probabilities=choice.probabilities)
        return order

    async def teampreview(self, battle: Battle) -> str:
        members = list(battle.team.values())
        if self.pick and self.pick < len(members):
            return await self.bring_preview(battle, members)
        lead, source, note, choice, usage = 0, "model", "", None, None
        try:
            choice, usage = await asyncio.wait_for(self._ask(
                format_team_preview(battle, state=self.battle_state), LEAD_INSTRUCTIONS,
                {f"LEAD: {m.species}": f"Lead with {m.species}." for m in members}), timeout=self.turn_timeout)
            lead = next(i for i, m in enumerate(members) if f"LEAD: {m.species}" == choice.choice)
        except asyncio.TimeoutError:
            source, note = "timeout", f"[TIMEOUT] No lead chosen within {self.turn_timeout:.0f}s."
        except Exception as e:
            source, note = "api_error", f"[API ERROR] {e}."
        message = self.bring_order(battle, [lead])
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=SimpleNamespace(message=f"{message} lead={members[lead].species}"),
            reasoning=choice.summary() if source == "model" else f"{note} Leading with the first Pokémon.",
            decision_source=source,
            llm_metrics=usage.metrics(self.client.provider_name).model_dump() if usage else None,
            probabilities=choice.probabilities if choice else None,
        )
        return message

    async def bring_preview(self, battle: Battle, members: list) -> str:
        """Bring N of the team, one Choice question per slot: the leader, then each one after it from those left."""
        chosen, notes, usage, source, note = [], [], Usage(), "model", ""
        state = format_team_preview(battle, self.pick, self.battle_state)
        try:
            for slot in range(self.pick):
                left = {f"BRING: {m.species}": f"Bring {m.species}." for i, m in enumerate(members) if i not in chosen}
                instructions = LEAD_INSTRUCTIONS if not chosen else BRING_INSTRUCTIONS.format(
                    pick=self.pick, chosen=", ".join(members[i].species for i in chosen))
                choice, used = await asyncio.wait_for(self._ask(state, instructions, left), timeout=self.turn_timeout)
                usage.add(used)
                chosen.append(next(i for i, m in enumerate(members) if f"BRING: {m.species}" == choice.choice))
                notes.append(f"{'Lead' if slot == 0 else f'Pick {slot + 1}'}: {choice.summary()}")
        except asyncio.TimeoutError:
            source, note = "timeout", f"[TIMEOUT] No team chosen within {self.turn_timeout:.0f}s."
        except Exception as e:
            source, note = "api_error", f"[API ERROR] {e}."
        message = self.bring_order(battle, chosen)
        brought = [members[int(c) - 1].species for c in message.split()[1]]
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=SimpleNamespace(message=f"{message} bring={','.join(brought)}"),
            reasoning="\n".join(notes) if source == "model" else f"{note} Bringing {', '.join(brought)}.",
            decision_source=source,
            llm_metrics=usage.metrics(self.client.provider_name).model_dump() if usage.requests else None,
        )
        return message
