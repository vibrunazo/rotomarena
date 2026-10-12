"""Base Benchmark Player class wrapping poke-env Player with telemetry hooks."""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Any, Dict, List, Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder, DefaultBattleOrder, Player
from poke_env.ps_client import AccountConfiguration, ServerConfiguration

from rotomarena.telemetry.breadcrumbs import (
    BreadcrumbsRecorder,
    DecisionSource,
    PlayerIdentity,
    TurnBreadcrumb,
)


class BaseBenchmarkPlayer(Player):
    """Base class for all RotomArena benchmark players with telemetry recording and a hang guard."""

    def __init__(
        self,
        player_name: str = "BenchmarkBot",
        agent_type: str = "base",
        battle_format: str = "gen9ou",
        team: Optional[str] = None,
        turn_timeout: float = 900.0,
        pick: Optional[int] = None,
        answer_attempts: int = 1,
        battle_state: int = 1,
        notes_shown: int = 3,
        identity: Optional[PlayerIdentity] = None,
        server_configuration: Optional[ServerConfiguration] = None,
        account_configuration: Optional[AccountConfiguration] = None,
        breadcrumbs_recorder: Optional[BreadcrumbsRecorder] = None,
        **kwargs,
    ):
        server_config = server_configuration or ServerConfiguration(
            "ws://127.0.0.1:8000/showdown/websocket",
            "https://play.pokemonshowdown.com/action.php?",
        )
        account_config = account_configuration or AccountConfiguration(player_name, None)

        super().__init__(
            account_configuration=account_config,
            server_configuration=server_config,
            battle_format=battle_format,
            team=team,
            start_timer_on_battle_start=False,
            **kwargs,
        )
        self.agent_name = player_name
        self.agent_type = agent_type
        self.turn_timeout = turn_timeout
        self.pick = pick  # Pokémon brought from team preview (bring-N formats); None: all of them
        self.brought: Dict[str, List[str]] = {}  # battle tag -> the species it brought (bring-N formats)
        self.answer_attempts = answer_attempts  # tries per decision (ruleset.answer_attempts)
        self.battle_state = battle_state  # which battle state the player reads (ruleset.battle_state)
        self.notes_shown = notes_shown  # battle state 3: its latest notes each turn shows (ruleset.notes_shown)
        self.notes: Dict[str, Dict[int, str]] = {}  # battle tag -> {turn: the notes it wrote then} (state 3)
        self.identity = identity or PlayerIdentity(
            config_id=player_name, display_name=player_name, agent_type=agent_type
        )
        self.breadcrumbs_recorder = breadcrumbs_recorder

    def set_recorder(self, recorder: BreadcrumbsRecorder) -> None:
        """Attach a telemetry breadcrumb recorder."""
        self.breadcrumbs_recorder = recorder

    async def send_room_message(self, battle: Battle, message: str) -> None:
        """Broadcasts a chat message to the Pokémon Showdown battle room for live spectators."""
        try:
            if hasattr(self, "ps_client") and self.ps_client:
                await self.ps_client.send_message(message, room=battle.battle_tag)
        except Exception:
            pass

    def record_turn_telemetry(
        self,
        battle: Battle,
        chosen_order: BattleOrder,
        reasoning: str = "",
        decision_source: DecisionSource = "model",
        hidden_reasoning: str = "",
        search_telemetry: Optional[Dict[str, Any]] = None,
        llm_metrics: Optional[Dict[str, Any]] = None,
        probabilities: Optional[Dict[str, float]] = None,
        attempts: int = 1,
        first_try: str = "",
        answer: str = "",
    ) -> None:
        """Records a structured breadcrumb entry for this turn."""
        if not self.breadcrumbs_recorder:
            return

        legal_acts = []
        if battle.available_moves:
            for m in battle.available_moves:
                legal_acts.append(f"MOVE:{m.id}")
                if getattr(battle, "can_mega_evolve", False):  # so missed Mega Evolutions can be counted
                    legal_acts.append(f"MOVE:{m.id} [MEGA]")
        if battle.available_switches:
            for s in battle.available_switches:
                legal_acts.append(f"SWITCH:{s.species}")

        active_name = battle.active_pokemon.species if battle.active_pokemon else "None"
        active_hp = round((battle.active_pokemon.current_hp_fraction if battle.active_pokemon else 0.0) * 100, 1)

        opp_name = battle.opponent_active_pokemon.species if battle.opponent_active_pokemon else "None"
        opp_hp = round((battle.opponent_active_pokemon.current_hp_fraction if battle.opponent_active_pokemon else 0.0) * 100, 1)

        crumb = TurnBreadcrumb(
            turn=battle.turn,
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            decision_source=decision_source,
            active_pokemon=active_name,
            active_hp_pct=active_hp,
            opponent_active=opp_name,
            opponent_hp_pct=opp_hp,
            legal_actions=legal_acts,
            chosen_action=str(chosen_order.message) if hasattr(chosen_order, "message") else str(chosen_order),
            reasoning=reasoning,
            hidden_reasoning=hidden_reasoning,
            search_telemetry=search_telemetry,
            llm_metrics=llm_metrics,
            probabilities=probabilities,
            attempts=attempts,
            first_try=first_try,
            answer=answer,
            timestamp=datetime.datetime.now().isoformat(),
        )
        self.breadcrumbs_recorder.record_turn(crumb, battle.battle_tag)

    def choose_default_order(self, battle: Battle) -> BattleOrder:
        """The fallback ("Autopilot") move: the first legal move, else the first legal switch."""
        if battle.available_moves:
            return self.create_order(battle.available_moves[0])
        elif battle.available_switches:
            return self.create_order(battle.available_switches[0])
        return DefaultBattleOrder()

    async def _choose_move_with_guard(self, battle: Battle) -> BattleOrder:
        """Runs the agent's decision under the hang guard; failures fall back to the default move."""
        start_time = time.perf_counter()
        try:
            order = await asyncio.wait_for(self._async_choose_move(battle), timeout=self.turn_timeout)
            elapsed = time.perf_counter() - start_time
            await self.send_room_message(battle, f"Turn {battle.turn}: move locked in after {elapsed:.1f}s.")
            return order

        except asyncio.TimeoutError:
            await self.send_room_message(
                battle,
                f"Turn {battle.turn}: no decision after {self.turn_timeout:.0f}s. Playing the default move.",
            )
            fallback_order = self.choose_default_order(battle)
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning=f"[TIMEOUT] No decision within {self.turn_timeout:.0f}s. Default move played.",
                decision_source="timeout",
            )
            return fallback_order

        except Exception as e:
            await self.send_room_message(battle, f"Turn {battle.turn}: agent error ({e}). Playing the default move.")
            fallback_order = self.choose_default_order(battle)
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning=f"[ERROR] Move selection error: {e}. Default move played.",
                decision_source="error",
            )
            return fallback_order

    def bring_order(self, battle: Battle, chosen: List[int]) -> str:
        """The /team message for these team indexes (0-based), in order; in a bring-N format only N are sent."""
        size = len(battle.team)
        rest = [i for i in range(size) if i not in chosen]
        order = (chosen + rest)[: self.pick if self.pick and self.pick < size else size]
        members = list(battle.team.values())
        if self.pick and self.pick < size:
            self.brought[battle.battle_tag] = [members[i].species for i in order]
        for mon in battle.team.values():
            mon._selected_in_teampreview = True
        return "/team " + "".join(str(i + 1) for i in order)

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        """Subclasses should override this method to compute moves."""
        return self.choose_default_order(battle)

    def choose_move(self, battle: Battle) -> BattleOrder:
        """poke-env entrypoint for move selection."""
        return self._choose_move_with_guard(battle)  # type: ignore
