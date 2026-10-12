"""Direct LLM Agent with Single-Call Chain-of-Thought (CoT) Reasoning."""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Callable, List, Optional, Tuple

from poke_env.battle import Battle
from poke_env.player import BattleOrder

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.llm.client import LLMClient, ProviderLimitError, to_id
from rotomarena.llm.prompts import format_battle_state, format_team_preview, system_prompt_for, user_template_for
from rotomarena.llm.schemas import ActionDecision

# What a model hears when its answer can't be played and it has another try (ruleset.answer_attempts)
MAX_ANSWER = 6000  # characters of the visible answer kept in the breadcrumbs (its end, where the decision is)

RETRY_PROMPT = ("Your answer could not be played: {problem}. Answer again for the same turn: a short <thought>, then "
                "a <decision> holding exactly one action from LEGAL ACTIONS THIS TURN, written as it is listed.")


class DirectLLMPlayer(BaseBenchmarkPlayer):
    """
    Direct LLM Agent: one chat completion per turn, answered as <thought> + <decision>.
    The decision must name a legal action exactly. An answer that doesn't gets another try when the ruleset allows
    (answer_attempts), told what was wrong; the last failure plays the default move.
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

    async def _ask(self, battle_state_str: str, retry: Optional[Tuple[str, str]] = None) -> ActionDecision:
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
                system_prompt=system_prompt_for(self.format, self.pick, self.answer_attempts, self.battle_state),
                retry=retry,
                user_template=user_template_for(self.battle_state),
            )
        except ProviderLimitError as e:
            self.provider_limit = e
            raise

    async def _decide(self, state: str, play: Callable[[ActionDecision], Tuple[Optional[str], str, object]],
                      retry_prompt: str = RETRY_PROMPT):
        """Asks up to answer_attempts times. `play(decision)` -> (problem or None, decision source, result).
        Returns (decision, result, source, problem, metrics of every try, tries, first_try)."""
        decision, metrics, retry, first_try = None, None, None, ""
        for attempt in range(1, self.answer_attempts + 1):
            decision = await self._ask(state, retry)
            if decision.metrics:
                metrics = decision.metrics if metrics is None else metrics.add(decision.metrics)
            problem, source, result = play(decision)
            if problem is None or attempt == self.answer_attempts:
                return decision, result, source, problem, metrics, attempt, first_try
            first_try = first_try or f"{problem}\n{(decision.raw_response or '')[-1500:]}"
            if self.battle_state >= 3:  # the thought became the player's notes
                retry_prompt = retry_prompt.replace("a short <thought>", "your <notes>")
            retry = (decision.raw_response or "", retry_prompt.format(problem=problem))
        raise AssertionError("unreachable")

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        """Queries the LLM, then plays its action only if it exactly matches a legal one."""

        def play(decision: ActionDecision):
            if decision.parse_error:
                return decision.parse_error, "parse_error", None
            order = None
            if decision.action_type == "MOVE":
                move = next((m for m in battle.available_moves if m.id == decision.target), None)
                if move is not None:
                    order = self.create_order(move, terastallize=decision.terastallize and battle.can_tera,
                                              mega=decision.mega_evolve and battle.can_mega_evolve)
            elif decision.action_type == "SWITCH":
                mon = next((m for m in battle.available_switches if to_id(m.species) == decision.target), None)
                if mon is not None:
                    order = self.create_order(mon)
            if order is None:
                return f"'{decision.action_type}: {decision.target}' is not a legal action", "invalid", None
            return None, "model", order

        if self.battle_state >= 3:
            only = self._only_action(battle)
            if only is not None:  # nothing to choose: no tokens spent asking (7% of c4's decisions)
                self.record_turn_telemetry(battle=battle, chosen_order=only, decision_source="forced",
                                           reasoning="Only one legal action: played without asking.")
                return only
        state = format_battle_state(battle, self.brought.get(battle.battle_tag), self.pick, self.battle_state,
                                    self.notes.get(battle.battle_tag), self.notes_shown)
        try:
            decision, order, source, problem, metrics, attempts, first_try = await self._decide(state, play)
        except Exception as e:
            fallback_order = self.choose_default_order(battle)
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning=f"[API ERROR] {e}. Default move played.",
                decision_source="api_error",
            )
            return fallback_order

        llm_metrics = metrics.model_dump() if metrics else None
        self.remember(battle, decision)
        retried = dict(attempts=attempts, first_try=first_try, answer=(decision.raw_response or "")[-MAX_ANSWER:])
        if order is None:
            fallback_order = self.choose_default_order(battle)
            if source == "parse_error":
                reasoning = (f"[PARSE ERROR] {problem}. Default move played.\n"
                             f"Raw answer:\n{decision.raw_response[-2000:]}")
            else:
                reasoning = f"[INVALID] {problem}. Default move played.\nOriginal reasoning:\n{decision.reasoning}"
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning=reasoning,
                decision_source=source,
                llm_metrics=llm_metrics,
                hidden_reasoning=decision.hidden_reasoning,
                **retried,
            )
            return fallback_order

        self.record_turn_telemetry(
            battle=battle,
            chosen_order=order,
            reasoning=decision.reasoning,
            llm_metrics=llm_metrics,
            hidden_reasoning=decision.hidden_reasoning,
            **retried,
        )
        return order

    def _only_action(self, battle: Battle) -> Optional[BattleOrder]:
        """The one legal action, when there is exactly one (a Mega Evolution option counts as another)."""
        moves = battle.available_moves or []
        switches = battle.available_switches or []
        options = len(moves) * (2 if battle.can_mega_evolve or battle.can_tera else 1) + len(switches)
        if options != 1:
            return None
        return self.create_order(moves[0] if moves else switches[0])

    def remember(self, battle: Battle, decision: Optional[ActionDecision]) -> None:
        """Keeps the notes the model wrote this turn for its later turns (battle state 3: its memory)."""
        if self.battle_state >= 3 and decision is not None and decision.reasoning:
            words = decision.reasoning.split()
            text = " ".join(words[:120]) + (" ..." if len(words) > 120 else "")  # asked for 60 words at most
            self.notes.setdefault(battle.battle_tag, {})[battle.turn] = text

    async def teampreview(self, battle: Battle) -> str:
        """The model picks its lead; the rest of the team keeps its order. Failures lead with the first
        Pokémon, which is what Showdown itself does when a player doesn't choose. In a bring-N format it picks the
        N it brings instead (bring_preview)."""
        members = list(battle.team.values())
        if self.pick and self.pick < len(members):
            return await self.bring_preview(battle, members)

        def play(decision: ActionDecision):
            if decision.parse_error:
                return decision.parse_error, "parse_error", None
            # A lead is the only legal action here, so a team member's name counts whatever the keyword
            # (small models wrote "MOVE: dragonite"); only the Pokémon has to be right.
            match = next((i for i, m in enumerate(members) if to_id(m.species) == decision.target), None)
            if match is None:
                return f"'{decision.action_type}: {decision.target}' is not a legal lead", "invalid", None
            return None, "model", match

        lead, source, note, decision, metrics, retried = 0, "model", "", None, None, {}
        try:
            decision, match, source, problem, metrics, attempts, first_try = await asyncio.wait_for(
                self._decide(format_team_preview(battle, state=self.battle_state), play,
                             "Your answer could not be used: {problem}. Answer again: a short <thought>, then "
                             "<decision>LEAD: one species from YOUR TEAM</decision>."),
                timeout=self.turn_timeout)
            self.remember(battle, decision)
            retried = dict(attempts=attempts, first_try=first_try, answer=(decision.raw_response or "")[-MAX_ANSWER:])
            if match is None:
                note = f"[{'PARSE ERROR' if source == 'parse_error' else 'INVALID'}] {problem}."
            else:
                lead = match
        except asyncio.TimeoutError:
            source, note = "timeout", f"[TIMEOUT] No lead chosen within {self.turn_timeout:.0f}s."
        except Exception as e:
            source, note = "api_error", f"[API ERROR] {e}."

        message = self.bring_order(battle, [lead])
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=SimpleNamespace(message=f"{message} lead={members[lead].species}"),
            reasoning=decision.reasoning if source == "model" else f"{note} Leading with the first Pokémon.",
            decision_source=source,
            llm_metrics=metrics.model_dump() if metrics else None,
            hidden_reasoning=decision.hidden_reasoning if decision else "",
            **retried,
        )
        return message

    async def bring_preview(self, battle: Battle, members: list) -> str:
        """Bring N of the team: the model answers BRING: a, b, c (the first leads). Names it gets wrong or misses
        are filled from the team's order, and the turn is recorded as invalid; no usable answer brings the first N."""

        def play(decision: ActionDecision):
            text = decision.raw_response or ""
            block = re.search(r"<decision>(.*?)(?:</decision>|$)", text, re.S | re.I)
            line = re.search(r"BRING\s*:\s*(.+)", block.group(1) if block else text, re.I)
            if not line:
                return "No BRING: line", "parse_error", []
            ids = {to_id(m.species): i for i, m in enumerate(members)}
            chosen: List[int] = []
            for name in [n.strip(" *.`") for n in re.split(r"[,/]", line.group(1)) if n.strip(" *.`")]:
                i = ids.get(to_id(name))
                if i is not None and i not in chosen and len(chosen) < self.pick:
                    chosen.append(i)
            if len(chosen) < self.pick:
                return (f"'BRING: {line.group(1).strip()}' names {len(chosen)} of the {self.pick} Pokémon from YOUR "
                        f"TEAM it must bring", "invalid", chosen)
            return None, "model", chosen

        chosen, source, note, decision, metrics, retried = [], "model", "", None, None, {}
        try:
            decision, chosen, source, problem, metrics, attempts, first_try = await asyncio.wait_for(
                self._decide(format_team_preview(battle, self.pick, self.battle_state), play,
                             "Your answer could not be used: {problem}. Answer again: a short <thought>, then "
                             f"<decision>BRING: {self.pick} different species from YOUR TEAM, comma-separated, the "
                             "leader first</decision>."),
                timeout=self.turn_timeout)
            self.remember(battle, decision)
            retried = dict(attempts=attempts, first_try=first_try, answer=(decision.raw_response or "")[-MAX_ANSWER:])
            if source == "parse_error":
                note = f"[PARSE ERROR] {problem}."
            elif source == "invalid":
                note = f"[INVALID] {problem}; the rest come from the team's order."
        except asyncio.TimeoutError:
            source, note = "timeout", f"[TIMEOUT] No team chosen within {self.turn_timeout:.0f}s."
        except Exception as e:
            source, note = "api_error", f"[API ERROR] {e}."
        message = self.bring_order(battle, chosen or [])
        brought = [members[int(c) - 1].species for c in message.split()[1]]
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=SimpleNamespace(message=f"{message} bring={','.join(brought)}"),
            reasoning=decision.reasoning if source == "model" else
            f"{note} Bringing {', '.join(brought)}." + (f"\n{decision.reasoning}" if decision and decision.reasoning else ""),
            decision_source=source,
            llm_metrics=metrics.model_dump() if metrics else None,
            hidden_reasoning=decision.hidden_reasoning if decision else "",
            **retried,
        )
        return message
