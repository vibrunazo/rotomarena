"""Agent factory: builds benchmark players from their configuration and names them for Showdown."""

from __future__ import annotations

import re
from typing import Optional, Tuple

from poke_env.ps_client import ServerConfiguration

from rotomarena.agents.base import BaseBenchmarkPlayer
from rotomarena.agents.decision import DecisionPlayer
from rotomarena.agents.direct_llm import DirectLLMPlayer
from rotomarena.agents.heuristic import HeuristicPlayer, MaxDamagePlayer
from rotomarena.agents.pokechamp import PokeChampPlayer
from rotomarena.agents.random import RandomBenchmarkPlayer
from rotomarena.config import AgentConfig, AppConfig
from rotomarena.llm.decisions import DecisionClient
from rotomarena.llm.client import LLMClient
from rotomarena.telemetry.breadcrumbs import PlayerIdentity


def clean_llm_model_name(model_str: str) -> str:
    """Extracts a concise, distinct model name (max ~13 chars) capturing family, version, and variant."""
    if not model_str:
        return "Direct LLM"

    # Strip provider prefix (e.g., 'google/', 'meta-llama/', 'nvidia/') and tag suffixes (':free', ':beta')
    raw = model_str.split(":")[0].strip()
    if "/" in raw:
        raw = raw.split("/")[-1]

    # Convert dashed version numbers (e.g. claude-3-7 -> claude-3.7, llama-3-3 -> llama-3.3)
    s = re.sub(r"(\d+)-(\d+)", r"\1.\2", raw)
    # Replace underscores/hyphens with spaces
    s = re.sub(r"[-_]+", " ", s).strip()
    lower_s = s.lower()

    # 1. Gemini (e.g., gemini-3.8-flash, gemini-3.7-pro, gemini-2.5, gemini-1.5-flash)
    if "gemini" in lower_s:
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        var = ""
        if "pro" in lower_s:
            var = " Pro"
        elif "ultra" in lower_s:
            var = " Ultra"
        elif "flash" in lower_s:
            var = " Flash"
        elif "exp" in lower_s:
            var = " Exp"
        res = f"Gemini{ver}{var}".strip()
        if len(res) <= 18:
            return res
        return f"Gem{ver}{var}"[:18].strip()

    # 2. Claude (e.g., claude-3.7-sonnet, claude-3.5-haiku, claude-opus)
    if "claude" in lower_s:
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        var = ""
        for opt in ["sonnet", "haiku", "opus"]:
            if opt in lower_s:
                var = f" {opt.title()}"
                break
        res = f"Claude{ver}{var}".strip()
        if len(res) <= 18:
            return res
        return f"Claude{ver} {var[1]}"[:18].strip()

    # 3. GPT / OpenAI (e.g., gpt-4o, gpt-4o-mini, gpt-4.5, o1, o3-mini, gpt-5)
    if "gpt" in lower_s or re.search(r"\b(o1|o3|o4)\b", lower_s):
        if "4o mini" in lower_s or "4o-mini" in lower_s:
            return "GPT-4o Mini"
        if "4o" in lower_s:
            return "GPT-4o"
        if "4.5" in lower_s:
            return "GPT-4.5"
        if "o1 mini" in lower_s or "o1-mini" in lower_s:
            return "OpenAI o1-mini"
        if "o1" in lower_s:
            return "OpenAI o1"
        if "o3 mini" in lower_s or "o3-mini" in lower_s:
            return "OpenAI o3-mini"
        if "o3" in lower_s:
            return "OpenAI o3"
        if "o4" in lower_s:
            return "OpenAI o4"
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        return f"GPT{ver}"[:18].strip()

    # 4. DeepSeek (e.g., deepseek-r1, deepseek-v4, deepseek-v3, deepseek-chat)
    if "deepseek" in lower_s:
        if "r1" in lower_s:
            return "DeepSeek R1"
        if "v4" in lower_s:
            return "DeepSeek V4"
        if "v3" in lower_s or "chat" in lower_s:
            return "DeepSeek V3"
        v_match = re.search(r"(v\d+|r\d+)", lower_s)
        if v_match:
            return f"DeepSeek {v_match.group(1).upper()}"[:18]
        return "DeepSeek"

    # 5. Llama (e.g., llama-3.3-70b, llama-3.1-8b, llama-3.2-3b)
    if "llama" in lower_s:
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        s_match = re.search(r"(\d+b)", lower_s)
        size = f" {s_match.group(1).upper()}" if s_match else ""
        return f"Llama{ver}{size}"[:18].strip()

    # 6. Nemotron (e.g., nemotron-3-ultra-550b, nemotron-3.5-lightning, nemotron-70b)
    if "nemotron" in lower_s:
        v_match = re.search(r"nemotron\s*(\d+(?:\.\d+)?)", lower_s)
        if not v_match:
            v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        s_match = re.search(r"(\d+b)", lower_s)
        size = f" {s_match.group(1).upper()}" if s_match else ""
        return f"Nemotron{ver}{size}"[:18].strip()

    # 7. Qwen / QwQ (e.g., qwen-2.5-72b, qwq-32b)
    if "qwen" in lower_s or "qwq" in lower_s:
        v_match = re.search(r"(\d+(?:\.\d+)?)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        s_match = re.search(r"(\d+b)", lower_s)
        size = f" {s_match.group(1).upper()}" if s_match else ""
        prefix = "QwQ" if "qwq" in lower_s else "Qwen"
        return f"{prefix}{ver}{size}"[:18].strip()

    # 8. MiniMax (e.g., minimax-m3, minimax-01)
    if "minimax" in lower_s:
        m_match = re.search(r"(m\d+|01)", lower_s)
        tag = f" {m_match.group(1).upper()}" if m_match else " M3"
        return f"MiniMax{tag}"[:18].strip()

    # 9. Mistral / Mixtral
    if "mixtral" in lower_s:
        s_match = re.search(r"(\d+x\d+b)", lower_s)
        size = f" {s_match.group(1)}" if s_match else ""
        return f"Mixtral{size}"[:18].strip()
    if "mistral" in lower_s:
        var = "Large" if "large" in lower_s else ("Small" if "small" in lower_s else ("Nemo" if "nemo" in lower_s else ""))
        v_str = f" {var}" if var else ""
        return f"Mistral{v_str}"[:18].strip()

    # 10. Grok
    if "grok" in lower_s:
        v_match = re.search(r"(\d+)", lower_s)
        ver = f" {v_match.group(1)}" if v_match else ""
        return f"Grok{ver}"[:18].strip()

    # Generic Fallback: Extract meaningful tokens
    tokens = s.split()
    words = [w.title() if not any(c.isdigit() for c in w) else w.upper() for w in tokens[:2]]
    cand = " ".join(words)
    return cand[:18].strip() or "Direct LLM"


def format_bot_display_name(
    agent_cfg: AgentConfig,
    resolved_model: Optional[str] = None,
    tag: Optional[str] = None,
) -> str:
    """Formats a clean, human-readable bot name (max 18 chars for Showdown)."""
    a_type = agent_cfg.type

    if agent_cfg.battle_name or agent_cfg.display_name:
        base = agent_cfg.battle_name or agent_cfg.display_name
    elif agent_cfg.is_model:
        model = resolved_model or agent_cfg.model or ""
        if model:
            base = clean_llm_model_name(model)
        elif agent_cfg.provider:
            base = f"{agent_cfg.provider.title()}"
        else:
            base = "Direct LLM"
    elif a_type == "pokechamp":
        base = "PokeChamp"
    elif a_type == "max_damage":
        base = "MaxDamage AI"
    elif a_type == "heuristic":
        base = "Heuristic AI"
    else:
        base = "Random AI"

    # Sanitize base for Showdown (only alphanumeric, dot, hyphen, and space)
    base = re.sub(r"[^a-zA-Z0-9. -]", "", base).strip()

    if tag:
        max_base_len = 18 - 1 - len(str(tag))
        return f"{base[:max_base_len].strip()} {tag}"

    return base[:18].strip()


def llm_client_for(agent_cfg: AgentConfig, app_config: AppConfig) -> LLMClient:
    """The LLM client a registry entry plays (or drafts) with; local models point at their own server's port."""
    providers = app_config.providers
    if agent_cfg.port:
        local = providers.get(agent_cfg.provider or "openrouter")
        providers = {**providers, agent_cfg.provider: local.model_copy(
            update={"base_url": f"http://127.0.0.1:{agent_cfg.port}/v1"})}
    client = LLMClient.from_provider_name(agent_cfg.provider or "openrouter", providers=providers,
                                          model_override=agent_cfg.model)
    client.only_providers = app_config.ruleset.provider_routing.get(agent_cfg.name)  # a rule of the version
    if agent_cfg.batch.get(app_config.ruleset.version):
        from rotomarena.llm.batch import shared_queue

        client.batch = shared_queue(providers[agent_cfg.provider or "openrouter"].get_api_key())
    from rotomarena.llm import relay

    if agent_cfg.name in relay.relayed:  # `ladder relay`: a person answers through the model's chat app
        client.relay = relay.shared_queue()
    return client


def create_agent_instance(
    agent_cfg: AgentConfig,
    app_config: AppConfig,
    player_tag: Optional[str] = None,
    lane: int = 1,
    start_listening: bool = True,
) -> BaseBenchmarkPlayer:
    """Builds a benchmark player from its configuration. Teams are assigned per game by the runner.
    Showdown names must be unique, so a mirror match tags both sides and lanes after the first (games of a set
    played at once) add their number; the display name stays the model's own.
    `start_listening=False` skips connecting to Showdown (for tests)."""
    from rotomarena.server import engine

    if engine.simulator() is not None:  # no logins: lanes need no numbers, and nobody listens to a server
        lane, start_listening = 1, False
    llm_client = llm_client_for(agent_cfg, app_config) if agent_cfg.type == "direct_llm" else None
    decision_client = DecisionClient.for_agent(agent_cfg, app_config) if agent_cfg.type == "decision" else None
    resolved_model = (llm_client.default_model if llm_client
                      else decision_client.model if decision_client else None)

    # The Showdown username is cut to 18 characters; the name recorded for the site isn't.
    display_name = agent_cfg.display_name or format_bot_display_name(agent_cfg, resolved_model=resolved_model)
    tag = " ".join(t for t in (player_tag, str(lane) if lane > 1 else None) if t)
    username = format_bot_display_name(agent_cfg, resolved_model=resolved_model, tag=tag or None)
    identity = PlayerIdentity(
        config_id=agent_cfg.name,
        display_name=display_name,
        agent_type=agent_cfg.type,
        provider=llm_client.provider_name if llm_client else decision_client.provider_name if decision_client else None,
        model=resolved_model,
        quantization=agent_cfg.quantization,
    )
    common = dict(
        player_name=username,
        identity=identity,
        # a batched model's turn waits for its batch: up to OpenRouter's 24-hour window
        turn_timeout=max(app_config.ruleset.turn_timeout, 26 * 3600) if agent_cfg.batch.get(app_config.ruleset.version)
        or agent_cfg.name in relayed_ids() else app_config.ruleset.turn_timeout,
        battle_format=app_config.ruleset.format,
        pick=app_config.ruleset.pick,
        answer_attempts=app_config.ruleset.answer_attempts or 1,
        battle_state=app_config.ruleset.battle_state or 1,
        notes_shown=app_config.ruleset.notes_shown if app_config.ruleset.notes_shown is not None else 3,
        start_listening=start_listening,
        server_configuration=ServerConfiguration(
            app_config.server.websocket_url,
            "https://play.pokemonshowdown.com/action.php?",
        ),
    )

    if agent_cfg.type == "direct_llm":
        player = DirectLLMPlayer(
            llm_client=llm_client,
            model=resolved_model,
            temperature=agent_cfg.temperature,
            max_output_tokens=app_config.ruleset.max_output_tokens,
            reasoning=agent_cfg.thinking(app_config.ruleset)[0],
            thinking_budget=agent_cfg.thinking(app_config.ruleset)[1],
            **common,
        )
        if agent_cfg.name in relayed_ids():
            from rotomarena.llm.relay import tag

            player.match_tags = [tag(agent_cfg.name)]
        elif agent_cfg.batch.get(app_config.ruleset.version):
            player.match_tags = [f"batch:{agent_cfg.name}"]  # about half price: kept out of its cost figures
        return player
    if agent_cfg.type == "decision":
        return DecisionPlayer(client=decision_client, **common)
    if agent_cfg.type == "pokechamp":
        return PokeChampPlayer(evaluation_weights=agent_cfg.evaluation_weights, **common)
    if agent_cfg.type == "max_damage":
        return MaxDamagePlayer(**common)
    if agent_cfg.type == "heuristic":
        return HeuristicPlayer(evaluation_weights=agent_cfg.evaluation_weights, **common)
    if agent_cfg.type == "random":
        return RandomBenchmarkPlayer(**common)
    raise ValueError(f"Unknown agent type '{agent_cfg.type}'")


def relayed_ids() -> set:
    from rotomarena.llm.relay import relayed

    return relayed


def resolved_model(agent_cfg: AgentConfig, app_config: AppConfig) -> Optional[str]:
    """The model an LLM agent will actually call: its own, else its provider's default."""
    if not agent_cfg.is_model:
        return None
    if agent_cfg.model:
        return agent_cfg.model
    provider = app_config.providers.get(agent_cfg.provider or "openrouter")
    return provider.default_model if provider else None


def create_players(
    cfg_a: AgentConfig, cfg_b: AgentConfig, app_config: AppConfig, lane: int = 1, lane_b: Optional[int] = None
) -> Tuple[BaseBenchmarkPlayer, BaseBenchmarkPlayer]:
    """Both players of a series (or of one lane of a parallel set; `lane_b` when B's lane number differs, see
    ladder.take_lane). Identical Showdown names would collide, so a mirror match gets numeric tags."""
    name_a = format_bot_display_name(cfg_a, resolved_model=resolved_model(cfg_a, app_config))
    name_b = format_bot_display_name(cfg_b, resolved_model=resolved_model(cfg_b, app_config))
    same = name_a.lower() == name_b.lower()
    a = create_agent_instance(cfg_a, app_config, player_tag="1" if same else None, lane=lane)
    b = create_agent_instance(cfg_b, app_config, player_tag="2" if same else None, lane=lane if lane_b is None else lane_b)
    # a control bot plays a copy of its opponent's team (ladder.set_teams): the opponent is told (battle state 3)
    if cfg_b.role == "control":
        a.mirror_of = cfg_b.display_name or cfg_b.name
    if cfg_a.role == "control":
        b.mirror_of = cfg_a.display_name or cfg_a.name
    return a, b
