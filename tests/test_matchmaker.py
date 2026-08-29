"""Tests for Elo rating updates and matchmaker orchestration."""

import pytest
from rotomarena.matchmaker.elo import EloRatingSystem
from rotomarena.matchmaker.tournament import create_agent_instance
from rotomarena.config import AgentConfig, AppConfig


def test_elo_rating_updates():
    elo = EloRatingSystem(initial_elo=1500.0, k_factor=32.0)
    
    # Win for agent A
    new_a, new_b = elo.record_match("AgentA", "AgentB", winner="AgentA")
    assert new_a > 1500.0
    assert new_b < 1500.0
    assert round(new_a + new_b, 1) == 3000.0

    # Leaderboard
    leaderboard = elo.get_leaderboard()
    assert len(leaderboard) == 2
    assert leaderboard[0].name == "AgentA"
    assert leaderboard[0].wins == 1
    assert leaderboard[0].win_rate == 100.0


def test_create_agent_instances():
    app_cfg = AppConfig.default_config()

    # PokéChamp
    cfg_pokechamp = AgentConfig(name="pokechamp_test", type="pokechamp", depth=1)
    agent_pc = create_agent_instance(cfg_pokechamp, app_cfg)
    assert agent_pc.agent_name == "pokechamp_test"
    assert agent_pc.agent_type == "pokechamp"

    # Direct LLM
    cfg_llm = AgentConfig(name="llm_test", type="direct_llm", provider="gemini")
    agent_llm = create_agent_instance(cfg_llm, app_cfg)
    assert agent_llm.agent_name == "llm_test"
    assert agent_llm.agent_type == "direct_llm"

    # Heuristic
    cfg_heur = AgentConfig(name="heur_test", type="heuristic")
    agent_heur = create_agent_instance(cfg_heur, app_cfg)
    assert agent_heur.agent_name == "heur_test"
    assert agent_heur.agent_type == "heuristic"
