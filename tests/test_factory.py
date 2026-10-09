"""Tests for the agent factory and bot display names."""

from rotomarena.agents.factory import clean_llm_model_name, create_agent_instance
import pytest
from pydantic import ValidationError
from rotomarena.config import FREE_TEST_MODEL, AgentConfig, AppConfig


def test_create_agent_instances():
    app_cfg = AppConfig.default_config()

    # PokéChamp
    cfg_pokechamp = AgentConfig(name="pokechamp_test", type="pokechamp")
    agent_pc = create_agent_instance(cfg_pokechamp, app_cfg, start_listening=False)
    assert agent_pc.agent_name == "PokeChamp"
    assert agent_pc.agent_type == "pokechamp"
    assert agent_pc.identity.config_id == "pokechamp_test"
    assert agent_pc.identity.model is None

    # Direct LLM with various model versions (no random hashes)
    cfg_llm_37 = AgentConfig(name="llm_test", type="direct_llm", provider="gemini", model="gemini-3.7-flash")
    agent_llm_37 = create_agent_instance(cfg_llm_37, app_cfg, start_listening=False)
    assert agent_llm_37.agent_name == "Gemini 3.7 Flash"
    assert agent_llm_37.agent_type == "direct_llm"

    cfg_llm_38 = AgentConfig(name="llm_test2", type="direct_llm", provider="gemini", model="gemini-3.8-flash")
    agent_llm_38 = create_agent_instance(cfg_llm_38, app_cfg, start_listening=False)
    assert agent_llm_38.agent_name == "Gemini 3.8 Flash"

    cfg_llm_38_pro = AgentConfig(name="llm_test3", type="direct_llm", provider="gemini", model="gemini-3.8-pro")
    agent_llm_38_pro = create_agent_instance(cfg_llm_38_pro, app_cfg, start_listening=False)
    assert agent_llm_38_pro.agent_name == "Gemini 3.8 Pro"

    # Disambiguation tag (for mirror matches)
    agent_mirror_1 = create_agent_instance(cfg_llm_37, app_cfg, player_tag="1", start_listening=False)
    agent_mirror_2 = create_agent_instance(cfg_llm_37, app_cfg, player_tag="2", start_listening=False)
    assert agent_mirror_1.agent_name == "Gemini 3.7 Flash 1"
    assert agent_mirror_2.agent_name == "Gemini 3.7 Flash 2"
    assert len(agent_mirror_1.agent_name) <= 18
    assert len(agent_mirror_2.agent_name) <= 18
    assert agent_mirror_1.identity.display_name == "Gemini 3.7 Flash"  # tags are for Showdown only

    # Lanes of a parallel set: lane 1 keeps the plain name, the others add their number within 18 characters
    long_name = AgentConfig(name="nemotron", type="direct_llm", display_name="Nemotron 3 Ultra")
    lane_3 = create_agent_instance(long_name, app_cfg, lane=3, start_listening=False)
    assert lane_3.agent_name == "Nemotron 3 Ultra 3" and lane_3.identity.display_name == "Nemotron 3 Ultra"
    assert create_agent_instance(long_name, app_cfg, start_listening=False).agent_name == "Nemotron 3 Ultra"

    # Heuristic
    cfg_heur = AgentConfig(name="heur_test", type="heuristic")
    agent_heur = create_agent_instance(cfg_heur, app_cfg, start_listening=False)
    assert agent_heur.agent_name == "Heuristic AI"
    assert agent_heur.agent_type == "heuristic"


def test_llm_agent_identity_and_ruleset():
    app_cfg = AppConfig.default_config()
    agent = create_agent_instance(app_cfg.agents["bonsai_2_27b"], app_cfg, start_listening=False)
    assert agent.identity.config_id == "bonsai_2_27b"
    assert agent.identity.provider == "local"
    assert agent.identity.model == "bonsai"
    assert agent.identity.quantization == "PQ2_0"
    assert agent.max_output_tokens == app_cfg.ruleset.max_output_tokens
    assert agent.reasoning == "medium"  # ladder profile
    assert agent.turn_timeout == app_cfg.ruleset.turn_timeout


def test_default_llm_is_the_free_test_model():
    app_cfg = AppConfig.default_config()
    agent = create_agent_instance(AgentConfig(name="llm", type="direct_llm"), app_cfg, start_listening=False)
    assert agent.identity.provider == "openrouter"
    assert agent.identity.model == FREE_TEST_MODEL


def test_unknown_agent_type_is_rejected():
    with pytest.raises(ValidationError):
        AgentConfig(name="typo", type="direct-llm")


def test_clean_llm_model_name():
    assert clean_llm_model_name("gemini-3.7-flash") == "Gemini 3.7 Flash"
    assert clean_llm_model_name("gemini-3.8-flash") == "Gemini 3.8 Flash"
    assert clean_llm_model_name("gemini-3.8-pro") == "Gemini 3.8 Pro"
    assert clean_llm_model_name("anthropic/claude-3-7-sonnet-20250219") == "Claude 3.7 Sonnet"
    assert clean_llm_model_name("claude-3.5-haiku") == "Claude 3.5 Haiku"
    assert clean_llm_model_name("openai/gpt-4o-mini") == "GPT-4o Mini"
    assert clean_llm_model_name("openai/gpt-4.5-preview") == "GPT-4.5"
    assert clean_llm_model_name("meta-llama/llama-3.3-70b-instruct") == "Llama 3.3 70B"
    assert clean_llm_model_name("qwen/qwen-2.5-72b-instruct") == "Qwen 2.5 72B"
    assert clean_llm_model_name("nvidia/nemotron-3-ultra-550b-a55b:free") == "Nemotron 3 550B"
    assert clean_llm_model_name("nvidia/nemotron-3.5-lightning:free") == "Nemotron 3.5"
    assert clean_llm_model_name("deepseek/deepseek-r1:free") == "DeepSeek R1"
    assert clean_llm_model_name("deepseek/deepseek-v4") == "DeepSeek V4"
    assert clean_llm_model_name("minimax/minimax-m3:free") == "MiniMax M3"
    assert clean_llm_model_name("mistralai/mistral-large-2411") == "Mistral Large"
    assert clean_llm_model_name("x-ai/grok-2") == "Grok 2"


def test_every_registry_llm_has_a_cross_game_model_key():
    agents = AppConfig.load("config.yaml").agents
    keys = {cid: a.canonical_model_key() for cid, a in agents.items() if a.type == "direct_llm"}
    assert all(keys.values()), [cid for cid, k in keys.items() if not k]
    assert keys["nemotron_3_ultra"] == "nvidia/nemotron-3-ultra-550b-a55b"  # the OpenRouter slug without ':free'
    assert len(set(keys.values())) == len(keys)
    assert agents["pokechamp"].canonical_model_key() is None


def test_a_thinking_exception_sends_its_effort_instead_of_the_budget():
    from rotomarena.config import AgentConfig, RulesetConfig

    ruleset = RulesetConfig(thinking_budget=1024, max_output_tokens=2048)
    assert AgentConfig(name="x", type="direct_llm").thinking(ruleset) == ("medium", 1024)
    assert AgentConfig(name="muse", type="direct_llm", thinking_effort="minimal").thinking(ruleset) == ("minimal", None)


def test_a_voided_game_is_not_rated():
    from rotomarena.results import void_reason
    from rotomarena.telemetry.breadcrumbs import MatchPlayer, MatchTelemetry

    players = [MatchPlayer(role=r, config_id=c, display_name=c, agent_type="direct_llm", username=c)
               for r, c in (("p1", "a"), ("p2", "b"))]
    m = MatchTelemetry(match_id="m", players=players, total_turns=10, voided="played before its thinking exception")
    assert void_reason(m, 0.5) == "played before its thinking exception"


def test_a_battle_name_is_the_showdown_username_and_the_display_name_stays_whole():
    from rotomarena.agents.factory import format_bot_display_name
    from rotomarena.config import AgentConfig

    luna = AgentConfig(name="luna_dec", type="decision", display_name="GPT-6 Luna Decisions", battle_name="Luna Decisions")
    assert format_bot_display_name(luna) == "Luna Decisions"
    assert format_bot_display_name(luna, tag="2") == "Luna Decisions 2"  # a set's second game: still whole
    assert luna.display_name == "GPT-6 Luna Decisions"
