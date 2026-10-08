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




SIX = ["Great Tusk", "Kingambit", "Gholdengo", "Dragapult", "Toxapex", "Corviknight"]
RULES = {"format": "[Gen 9] OU", "id": "gen9ou", "species": SIX + ["Ogerpon", "Ogerpon-Wellspring"],
         "base": {**{s: s for s in SIX}, "Ogerpon": "Ogerpon", "Ogerpon-Wellspring": "Ogerpon"},
         "clauses": ["Species Clause: Prevents teams from having more than one Pok&eacute;mon from the same species"],
         "banned": {"abilities": ["Moody"], "moves": ["Baton Pass"], "items": ["King's Rock"]}}


def test_draft_prompts_state_the_rules_not_strategy():
    from rotomarena.teams.draft import BUILD_PROMPT, PICK_PROMPT, options_text, system_prompt

    prompt = system_prompt(RULES)
    assert "Great Tusk, Kingambit" in prompt and "Baton Pass" in prompt and "King's Rock" in prompt
    assert "Pokémon from the same species" in prompt  # HTML entity decoded
    assert "Species @ Item" in BUILD_PROMPT and "<pokemon>" in PICK_PROMPT  # format examples name no real Pokémon
    options = options_text({"Kingambit": {"name": "Kingambit", "types": ["Dark", "Steel"],
                                          "abilities": ["Defiant", "Supreme Overlord"], "moves": ["Kowtow Cleave", "Sucker Punch"]}})
    assert "Kingambit (Dark/Steel)" in options and "Abilities: Defiant, Supreme Overlord" in options


def test_picks_are_checked_against_the_list_and_species_clause():
    from rotomarena.teams.draft import check_picks

    picks, problems = check_picks("1. Great Tusk\n- kingambit\nGholdengo @ Leftovers\nDragapult\nToxapex\nCorviknight", RULES)
    assert picks == SIX and problems == []  # list markers, case and stray items are tolerated
    picks, problems = check_picks("Great Tusk\nOgerpon\nOgerpon-Wellspring\nRoaring Moon\nToxapex", RULES)
    assert picks == ["Great Tusk", "Ogerpon", "Toxapex"]
    assert any("Roaring Moon is not a legal" in p for p in problems)
    assert any("same species" in p for p in problems) and any("listed 5" in p for p in problems)
    assert "cut off" in check_picks(None, RULES, cut_off=True)[1][0]


def test_draft_picks_six_then_builds_their_sets(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from rotomarena.config import AgentConfig, AppConfig
    from rotomarena.llm.client import Completion
    from rotomarena.llm.schemas import LLMUsageMetrics
    from rotomarena.teams import draft

    team = "\n\n".join(f"{s} @ Leftovers\nAbility: Pressure\n- Protect" for s in SIX)
    answers = [
        "<thought>Hazards.</thought><pokemon>Roaring Moon\n" + "\n".join(SIX[1:]) + "</pokemon>",  # a banned pick
        "<thought>Hazards.</thought><pokemon>" + "\n".join(SIX) + "</pokemon>",
        "<thought>Sets.</thought><team>" + team.replace("Corviknight", "Garchomp") + "</team>",  # not one of the six
        "<thought>Sets.</thought><team>" + team + "</team>",
    ]
    seen, replies = [], iter(answers)

    async def complete(messages, **kwargs):  # the conversation keeps growing: note what each call was asked
        seen.append(messages[-1]["content"])
        return Completion(next(replies), "", LLMUsageMetrics(total_tokens=100, finish_reason="stop"))

    client = SimpleNamespace(default_model="m", provider_name="openrouter", generate_completion=complete)
    monkeypatch.setattr(draft, "format_rules", lambda app_cfg: RULES)
    monkeypatch.setattr(draft, "llm_client_for", lambda agent, app_cfg: client)
    monkeypatch.setattr(draft, "species_options", lambda app_cfg, names: {n: {"name": n, "types": ["Normal"],
                        "abilities": ["Pressure"], "moves": ["Protect"]} for n in names})
    monkeypatch.setattr(draft, "validate_team", lambda app_cfg, text: [])

    record = asyncio.run(draft.draft_team(AgentConfig(name="x", type="direct_llm"), AppConfig(), log=lambda m: None))
    assert record["legal"] and not record["repaired"] and record["picks"]["species"] == SIX
    assert [len(a["problems"]) for a in record["picks"]["attempts"]] == [1, 0]
    assert [len(a["problems"]) for a in record["attempts"]] == [1, 0] and record["thought"] == "Sets."
    assert "Roaring Moon is not a legal" in seen[1]  # the problems go back to the model
    assert "Kingambit (Normal)" in seen[2]  # stage 2 lists each pick's options
    assert "Garchomp is not among the six" in seen[3]


def test_answers_filed_under_reasoning_are_recovered_and_stage_two_drops_the_list():
    from rotomarena.llm.client import recover_answer
    from rotomarena.teams.draft import system_prompt

    text, reasoning = recover_answer("", "Let me think.</ifm|think><pokemon>Kingambit</pokemon>", "<pokemon>")
    assert text == "<pokemon>Kingambit</pokemon>" and reasoning == "Let me think.</ifm|think>"
    assert recover_answer("<team>x</team>", "<team>y</team>", "<team>") == ("<team>x</team>", "<team>y</team>")
    assert "Ogerpon-Wellspring" in system_prompt(RULES)
    assert "Ogerpon-Wellspring" not in system_prompt(RULES, with_species=False)  # stage 2 keeps the context small
