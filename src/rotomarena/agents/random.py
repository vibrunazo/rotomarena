"""Random baseline player for sanity checking and calibration."""

from __future__ import annotations

from typing import Optional
from poke_env.battle import Battle
from poke_env.player import BattleOrder

from rotomarena.agents.base import BaseBenchmarkPlayer


class RandomBenchmarkPlayer(BaseBenchmarkPlayer):
    """Random baseline player wrapping poke-env random move choice with telemetry."""

    def __init__(
        self,
        player_name: str = "RandomBot",
        battle_format: str = "gen9ou",
        team: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            player_name=player_name,
            agent_type="random",
            battle_format=battle_format,
            team=team,
            **kwargs,
        )

    def choose_move(self, battle: Battle) -> BattleOrder:
        order = self.choose_random_move(battle)
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=order,
            reasoning="Randomly sampled legal action.",
        )
        return order
