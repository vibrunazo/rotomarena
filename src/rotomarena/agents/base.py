"""Base Benchmark Player class wrapping poke-env Player with telemetry hooks."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder, DefaultBattleOrder, Player
from poke_env.ps_client import (
    AccountConfiguration,
    LocalhostServerConfiguration,
    ServerConfiguration,
)

from rotomarena.telemetry.breadcrumbs import BreadcrumbsRecorder, TurnBreadcrumb


class BaseBenchmarkPlayer(Player):
    """Base class for all RotomArena benchmark players with telemetry recording."""

    def __init__(
        self,
        player_name: str = "BenchmarkBot",
        agent_type: str = "base",
        battle_format: str = "gen9ou",
        team: Optional[str] = None,
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
        self.breadcrumbs_recorder = breadcrumbs_recorder

    def set_recorder(self, recorder: BreadcrumbsRecorder) -> None:
        """Attach a telemetry breadcrumb recorder."""
        self.breadcrumbs_recorder = recorder

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
