"""Elo Rating System for Pokémon AI agent ranking."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class AgentEloStats(BaseModel):
    """Elo ranking and match statistics for an agent."""

    name: str
    elo: float = 1500.0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    total_games: int = 0

    @property
    def win_rate(self) -> float:
        if self.total_games == 0:
            return 0.0
        return round((self.wins / self.total_games) * 100, 2)


class EloRatingSystem:
    """Dynamic Elo rating manager for benchmark participants."""

    def __init__(self, initial_elo: float = 1500.0, k_factor: float = 32.0):
        self.initial_elo = initial_elo
        self.k_factor = k_factor
        self.ratings: Dict[str, AgentEloStats] = {}

    def get_or_create(self, agent_name: str) -> AgentEloStats:
        """Retrieve or initialize stats for an agent."""
        if agent_name not in self.ratings:
            self.ratings[agent_name] = AgentEloStats(
                name=agent_name, elo=self.initial_elo
            )
        return self.ratings[agent_name]

    def record_match(
        self,
        agent_a: str,
        agent_b: str,
        winner: Optional[str],
    ) -> Tuple[float, float]:
        """
        Updates Elo ratings for two agents following a match.
        
        Args:
            agent_a: Name of player 1
            agent_b: Name of player 2
            winner: Name of the winner, or None for a draw.
            
        Returns:
            Tuple of (new_elo_a, new_elo_b)
        """
        stats_a = self.get_or_create(agent_a)
        stats_b = self.get_or_create(agent_b)

        r_a = stats_a.elo
        r_b = stats_b.elo

        # Expected scores
        e_a = 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / 400.0))
        e_b = 1.0 / (1.0 + 10.0 ** ((r_a - r_b) / 400.0))

        # Actual scores
        if winner == agent_a:
            s_a = 1.0
            s_b = 0.0
            stats_a.wins += 1
            stats_b.losses += 1
        elif winner == agent_b:
            s_a = 0.0
            s_b = 1.0
            stats_a.losses += 1
            stats_b.wins += 1
        else:
            s_a = 0.5
            s_b = 0.5
            stats_a.draws += 1
            stats_b.draws += 1

        stats_a.total_games += 1
        stats_b.total_games += 1

        # New ratings
        stats_a.elo = round(r_a + self.k_factor * (s_a - e_a), 1)
        stats_b.elo = round(r_b + self.k_factor * (s_b - e_b), 1)

        return stats_a.elo, stats_b.elo

    def get_leaderboard(self) -> List[AgentEloStats]:
        """Returns sorted leaderboard list by Elo descending."""
        return sorted(self.ratings.values(), key=lambda s: s.elo, reverse=True)
