"""Matchmaker, series runner, and tournament orchestration package."""

from rotomarena.matchmaker.elo import AgentEloStats, EloRatingSystem
from rotomarena.matchmaker.runner import MatchResult, MatchRunner, SeriesResult
from rotomarena.matchmaker.tournament import (
    TournamentOrchestrator,
    TournamentSummary,
    create_agent_instance,
)

__all__ = [
    "AgentEloStats",
    "EloRatingSystem",
    "MatchResult",
    "MatchRunner",
    "SeriesResult",
    "TournamentOrchestrator",
    "TournamentSummary",
    "create_agent_instance",
]
