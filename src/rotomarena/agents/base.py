"""Base Benchmark Player class wrapping poke-env Player with telemetry hooks."""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Any, Dict, List, Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder, DefaultBattleOrder, Player
from poke_env.ps_client import (
    AccountConfiguration,
    LocalhostServerConfiguration,
    ServerConfiguration,
)

from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder, TurnBreadcrumb


def _format_time_bank(seconds: float) -> str:
    """Format seconds into M:SS representation."""
    s = int(max(0, seconds))
    mins = s // 60
    secs = s % 60
    return f"{mins}:{secs:02d}"


class BaseBenchmarkPlayer(Player):
    """Base class for all RotomArena benchmark players with telemetry recording, turn timer, and chess-clock bank."""

    def __init__(
        self,
        player_name: str = "BenchmarkBot",
        agent_type: str = "base",
        battle_format: str = "gen9ou",
        team: Optional[str] = None,
        turn_timeout: float = 100.0,
        bank_timeout: float = 600.0,
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
        self.bank_timeout = bank_timeout
        self.time_bank_remaining = bank_timeout
        self._current_battle_tag: Optional[str] = None
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
        """Safely picks any available move or switch as fallback."""
        if battle.available_moves:
            return self.create_order(battle.available_moves[0])
        elif battle.available_switches:
            return self.create_order(battle.available_switches[0])
        return DefaultBattleOrder()

    async def _async_choose_move_with_timer(self, battle: Battle) -> BattleOrder:
        """Wraps move computation with a 45s turn timer and 7min total bank timer."""
        # Reset bank on new match
        b_tag = getattr(battle, "battle_tag", "battle-unknown")
        if self._current_battle_tag != b_tag:
            self._current_battle_tag = b_tag
            self.time_bank_remaining = self.bank_timeout

        # Check total time bank
        if self.time_bank_remaining <= 0.0:
            await self.send_room_message(
                battle,
                "⏰ Match time bank exhausted (0:00)! Auto-selecting fallback move.",
            )
            fallback_order = self.choose_default_order(battle)
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning="[TIME BANK EXHAUSTED] Match time bank depleted. Automated move executed.",
            )
            return fallback_order

        start_time = time.perf_counter()
        effective_timeout = min(self.turn_timeout, max(0.1, self.time_bank_remaining))
        bank_display = _format_time_bank(self.time_bank_remaining)

        await self.send_room_message(
            battle,
            f"⏳ Deciding turn {battle.turn} (Turn limit: {self.turn_timeout:.0f}s | Bank: {bank_display} remaining)...",
        )

        try:
            coro_or_order = self._async_choose_move(battle)
            if asyncio.iscoroutine(coro_or_order):
                order = await asyncio.wait_for(coro_or_order, timeout=effective_timeout)
            else:
                order = coro_or_order

            elapsed = time.perf_counter() - start_time
            self.time_bank_remaining = max(0.0, self.time_bank_remaining - elapsed)
            new_bank_display = _format_time_bank(self.time_bank_remaining)

            await self.send_room_message(
                battle,
                f"✅ Move locked in ({elapsed:.2f}s)! Bank: {new_bank_display}. Waiting for opponent...",
            )
            return order

        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - start_time
            self.time_bank_remaining = max(0.0, self.time_bank_remaining - elapsed)
            new_bank_display = _format_time_bank(self.time_bank_remaining)

            await self.send_room_message(
                battle,
                f"⏰ Turn timed out ({effective_timeout:.1f}s)! Bank: {new_bank_display}. Auto-selecting legal fallback move.",
            )
            fallback_order = self.choose_default_order(battle)
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning=f"[TIMEOUT] Turn calculation exceeded limit ({effective_timeout:.1f}s). Automated move executed.",
            )
            return fallback_order

        except Exception as e:
            elapsed = time.perf_counter() - start_time
            self.time_bank_remaining = max(0.0, self.time_bank_remaining - elapsed)
            await self.send_room_message(
                battle,
                f"⚠️ Calculation error: {e}. Auto-selecting legal fallback move.",
            )
            fallback_order = self.choose_default_order(battle)
            self.record_turn_telemetry(
                battle=battle,
                chosen_order=fallback_order,
                reasoning=f"[ERROR] Move selection error: {e}. Automated move executed.",
            )
            return fallback_order

    async def _async_choose_move(self, battle: Battle) -> BattleOrder:
        """Subclasses should override this method to compute moves."""
        return self.choose_default_order(battle)

    def choose_move(self, battle: Battle) -> BattleOrder:
        """poke-env entrypoint for move selection."""
        return self._async_choose_move_with_timer(battle)  # type: ignore
