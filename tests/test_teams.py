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
