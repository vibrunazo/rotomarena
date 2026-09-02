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
    assert agent_pc.agent_name.startswith("PokeChamp D1")
    assert agent_pc.agent_type == "pokechamp"

    # Direct LLM with various model versions
    cfg_llm_37 = AgentConfig(name="llm_test", type="direct_llm", provider="gemini", model="gemini-3.7-flash")
    agent_llm_37 = create_agent_instance(cfg_llm_37, app_cfg)
    assert agent_llm_37.agent_name.startswith("Gemini 3.7")
    assert agent_llm_37.agent_type == "direct_llm"

    cfg_llm_38 = AgentConfig(name="llm_test2", type="direct_llm", provider="gemini", model="gemini-3.8-flash")
    agent_llm_38 = create_agent_instance(cfg_llm_38, app_cfg)
    assert agent_llm_38.agent_name.startswith("Gemini 3.8")

    cfg_llm_38_pro = AgentConfig(name="llm_test3", type="direct_llm", provider="gemini", model="gemini-3.8-pro")
    agent_llm_38_pro = create_agent_instance(cfg_llm_38_pro, app_cfg)
    assert agent_llm_38_pro.agent_name.startswith("Gemini 3.8 Pro")

    # Heuristic
    cfg_heur = AgentConfig(name="heur_test", type="heuristic")
    agent_heur = create_agent_instance(cfg_heur, app_cfg)
    assert agent_heur.agent_name.startswith("Heuristic AI")
    assert agent_heur.agent_type == "heuristic"


def test_clean_llm_model_name():
    from rotomarena.matchmaker.tournament import clean_llm_model_name

    assert clean_llm_model_name("gemini-3.7-flash") == "Gemini 3.7"
    assert clean_llm_model_name("gemini-3.8-flash") == "Gemini 3.8"
    assert clean_llm_model_name("gemini-3.8-pro") == "Gemini 3.8 Pro"
    assert clean_llm_model_name("anthropic/claude-3-7-sonnet-20250219") == "Claude 3.7 S"
    assert clean_llm_model_name("claude-3.5-haiku") == "Claude 3.5 H"
    assert clean_llm_model_name("openai/gpt-4o-mini") == "GPT-4o Mini"
    assert clean_llm_model_name("openai/gpt-4.5-preview") == "GPT-4.5"
    assert clean_llm_model_name("meta-llama/llama-3.3-70b-instruct") == "Llama 3.3 70B"
    assert clean_llm_model_name("qwen/qwen-2.5-72b-instruct") == "Qwen 2.5 72B"
    assert clean_llm_model_name("nvidia/nemotron-3-ultra-550b-a55b:free") == "Nemotron 3"
    assert clean_llm_model_name("nvidia/nemotron-3.5-lightning:free") == "Nemotron 3.5"
    assert clean_llm_model_name("deepseek/deepseek-r1:free") == "DeepSeek R1"
    assert clean_llm_model_name("deepseek/deepseek-v4") == "DeepSeek V4"
    assert clean_llm_model_name("minimax/minimax-m3:free") == "MiniMax M3"
    assert clean_llm_model_name("mistralai/mistral-large-2411") == "Mistral Large"
    assert clean_llm_model_name("x-ai/grok-2") == "Grok 2"
