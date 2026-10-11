"""Random baseline player for sanity checking and calibration."""

from __future__ import annotations

import random
from types import SimpleNamespace
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

    def teampreview(self, battle: Battle) -> str:
        """A random order, as poke-env's default; recorded, so the site can show which ones it brought."""
        members = list(battle.team.values())
        order = list(range(len(members)))
        random.shuffle(order)
        message = self.bring_order(battle, order)
        picked = [members[int(c) - 1].species for c in message.split()[1]]
        bring_n = self.pick and self.pick < len(members)
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=SimpleNamespace(message=f"{message} bring={','.join(picked)}" if bring_n
                                         else f"{message} lead={picked[0]}"),
            reasoning="Randomly chosen team." if bring_n else "Randomly chosen lead.",
        )
        return message

    def choose_move(self, battle: Battle) -> BattleOrder:
        order = self.choose_random_move(battle)
        self.record_turn_telemetry(
            battle=battle,
            chosen_order=order,
            reasoning="Randomly sampled legal action.",
        )
        return order
