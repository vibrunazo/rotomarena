"""Base Benchmark Player class wrapping poke-env Player with telemetry hooks."""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Any, Dict, Optional
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
        search_telemetry: Optional[Dict[str, Any]] = None,
        llm_metrics: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Records a structured breadcrumb entry for this turn."""
        if not self.breadcrumbs_recorder:
            return

        legal_acts = []
        if battle.available_moves:
            for m in battle.available_moves:
                legal_acts.append(f"MOVE:{m.id}")
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
            search_telemetry=search_telemetry,
            llm_metrics=llm_metrics,
            timestamp=datetime.datetime.now().isoformat(),
        )
        self.breadcrumbs_recorder.record_turn(crumb)

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

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        """Subclasses should override this method to compute moves."""
        return self.choose_default_order(battle)

    def choose_move(self, battle: Battle) -> BattleOrder:
        """poke-env entrypoint for move selection."""
        return self._choose_move_with_guard(battle)  # type: ignore
