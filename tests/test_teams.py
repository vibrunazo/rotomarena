"""Tests for team loading, parsing, and Showdown packing."""

import pytest
from pathlib import Path
from rotomarena.teams.loader import parse_smogon_team, load_team_file, PokemonMember, Team
from rotomarena.teams.presets import list_available_teams, load_preset_team


SAMPLE_SMOGON_TEXT = """
Great Tusk @ Booster Energy
Ability: Protosynthesis
Tera Type: Ice
EVs: 252 Atk / 4 Def / 252 Spe
Jolly Nature
- Headlong Rush
- Close Combat
- Ice Spinner
- Rapid Spin

Kingambit @ Leftovers
Ability: Supreme Overlord
Tera Type: Flying
EVs: 212 HP / 252 Atk / 44 Spe
Adamant Nature
- Kowtow Cleave
- Sucker Punch
- Iron Head
- Swords Dance
"""


def test_parse_smogon_team():
    team = parse_smogon_team(SAMPLE_SMOGON_TEXT, name="Test Team")
    assert team.name == "Test Team"
    assert len(team.members) == 2

    # Check Great Tusk
    tusk = team.members[0]
    assert tusk.species == "Great Tusk"
    assert tusk.item == "Booster Energy"
    assert tusk.ability == "Protosynthesis"
    assert tusk.tera_type == "Ice"
    assert tusk.nature == "Jolly"
    assert tusk.evs["atk"] == 252
    assert tusk.evs["spe"] == 252
    assert "Headlong Rush" in tusk.moves
    assert "Rapid Spin" in tusk.moves

    # Check Kingambit
    gambit = team.members[1]
    assert gambit.species == "Kingambit"
    assert gambit.item == "Leftovers"
    assert gambit.tera_type == "Flying"
    assert gambit.nature == "Adamant"
    assert gambit.evs["hp"] == 212


def test_to_showdown_packed():
    team = parse_smogon_team(SAMPLE_SMOGON_TEXT)
    packed = team.to_showdown_packed()
    assert isinstance(packed, str)
    assert len(packed) > 0
    # Must contain both pokemon separated by ']'
    parts = packed.split("]")
    assert len(parts) == 2
    assert "Great Tusk" in parts[0]
    assert "Kingambit" in parts[1]


def test_to_smogon_text():
    team = parse_smogon_team(SAMPLE_SMOGON_TEXT)
    reconstructed = team.to_smogon_text()
    assert "Great Tusk @ Booster Energy" in reconstructed
    assert "Tera Type: Ice" in reconstructed
    assert "- Headlong Rush" in reconstructed


def test_load_all_preset_teams():
    team_files = list_available_teams(Path("data/teams"))
    assert len(team_files) >= 4

    for tf in team_files:
        team = load_team_file(tf)
        assert team.is_valid
        assert len(team.members) == 6
        packed = team.to_showdown_packed()
        assert len(packed.split("]")) == 6


def test_load_preset_team_by_name():
    team = load_preset_team("balance")
    assert len(team.members) == 6
    assert any(m.species == "Great Tusk" for m in team.members)


RULES = {"format": "[Gen 9] OU", "id": "gen9ou", "species": ["Great Tusk", "Kingambit"],
         "clauses": ["Species Clause: Prevents teams from having more than one Pok&eacute;mon from the same species"],
         "banned": {"abilities": ["Moody"], "moves": ["Baton Pass"], "items": ["King's Rock"]}}


def test_draft_prompt_states_the_rules_not_strategy():
    from rotomarena.teams.draft import system_prompt

    prompt = system_prompt(RULES)
    assert "Great Tusk, Kingambit" in prompt and "Baton Pass" in prompt and "King's Rock" in prompt
    assert "Pokémon from the same species" in prompt  # HTML entity decoded
    assert "Species @ Item" in prompt  # the format example names no real Pokémon


def test_draft_feeds_back_the_validator_until_the_team_is_legal(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from rotomarena.config import AgentConfig, AppConfig
    from rotomarena.llm.client import Completion
    from rotomarena.llm.schemas import LLMUsageMetrics
    from rotomarena.teams import draft

    answers = ["<thought>Too long, never finished", "<thought>Hazards.</thought><team>Roaring Moon @ Leftovers</team>",
               "<thought>Hazards.</thought><team>Great Tusk @ Leftovers</team>"]
    client = SimpleNamespace(default_model="m", provider_name="openrouter", generate_completion=AsyncMock(side_effect=[
        Completion(a, "", LLMUsageMetrics(total_tokens=100, finish_reason="length" if i == 0 else "stop"))
        for i, a in enumerate(answers)]))
    monkeypatch.setattr(draft, "format_rules", lambda app_cfg: RULES)
    monkeypatch.setattr(draft, "llm_client_for", lambda agent, app_cfg: client)
    monkeypatch.setattr(draft, "validate_team", lambda app_cfg, text: ["Roaring Moon is tagged Uber, which is banned."]
                        if "Roaring Moon" in text else [])

    record = asyncio.run(draft.draft_team(AgentConfig(name="x", type="direct_llm"), AppConfig(), log=lambda m: None))
    assert record["legal"] and record["team"] == "Great Tusk @ Leftovers" and record["thought"] == "Hazards."
    assert [len(a["problems"]) for a in record["attempts"]] == [1, 1, 0]
    assert "cut off at the token budget" in record["attempts"][0]["problems"][0]
    retry = client.generate_completion.await_args_list[2].args[0][-1]["content"]
    assert "Roaring Moon is tagged Uber" in retry  # the validator's own words go back to the model
