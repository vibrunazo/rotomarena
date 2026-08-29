"""Tests for Gen 9 type chart, damage estimator, and heuristic evaluation."""

from poke_env.battle import MoveCategory, Status
from rotomarena.search.heuristics import TYPE_CHART, get_type_effectiveness
from rotomarena.search.simulator import estimate_damage_fraction


def test_type_effectiveness():
    # Water vs Fire -> 2.0x
    assert get_type_effectiveness("WATER", ["FIRE"]) == 2.0
    # Electric vs Water/Flying (e.g. Pelipper) -> 4.0x
    assert get_type_effectiveness("ELECTRIC", ["WATER", "FLYING"]) == 4.0
    # Ground vs Flying -> 0.0x
    assert get_type_effectiveness("GROUND", ["FLYING"]) == 0.0
    # Ghost vs Normal -> 0.0x
    assert get_type_effectiveness("GHOST", ["NORMAL"]) == 0.0
    # Fairy vs Dragon/Dark -> 4.0x
    assert get_type_effectiveness("FAIRY", ["DRAGON", "DARK"]) == 4.0
    # Fire vs Water/Dragon -> 0.25x
    assert get_type_effectiveness("FIRE", ["WATER", "DRAGON"]) == 0.25


def test_estimate_damage_fraction_mock():
    # Create lightweight mock objects
    class MockType:
        def __init__(self, name):
            self.name = name

    class MockMove:
        def __init__(self, name, power, move_type, category=MoveCategory.PHYSICAL):
            self.id = name
            self.base_power = power
            self.type = MockType(move_type)
            self.category = category

    class MockPokemon:
        def __init__(self, species, types, stats=None, status=None, boosts=None, max_hp=300):
            self.species = species
            self.types = [MockType(t) for t in types]
            self.stats = stats or {"atk": 300, "def": 250, "spa": 300, "spd": 250, "spe": 250}
            self.status = status
            self.boosts = boosts or {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
            self.max_hp = max_hp
            self.current_hp_fraction = 1.0
            self.tera_type = None
            self.ability = ""

    attacker = MockPokemon("Great Tusk", ["GROUND", "FIGHTING"])
    defender = MockPokemon("Heatran", ["FIRE", "STEEL"])

    # Headlong Rush (Ground vs Fire/Steel is 4.0x super effective)
    move_ground = MockMove("headlongrush", 120, "GROUND", MoveCategory.PHYSICAL)
    dmg_frac = estimate_damage_fraction(move_ground, attacker, defender)
    assert dmg_frac > 0.8  # Should be near KO or OHKO

    # Weak not very effective move
    move_not_eff = MockMove("firespin", 35, "FIRE", MoveCategory.SPECIAL)
    dmg_weak = estimate_damage_fraction(move_not_eff, attacker, defender)
    assert dmg_weak < 0.2
