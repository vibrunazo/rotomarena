"""Mock classes and helpers for battle simulations and tests."""

from typing import Dict, List, Optional
from poke_env.battle import Move, MoveCategory, Pokemon, PokemonType


class MockType:
    def __init__(self, name: str):
        self.name = name


def create_test_move(move_id: str, power: Optional[int] = None) -> Move:
    """Helper to create a Move object for tests."""
    move = Move(move_id=move_id, gen=9)
    if power is not None:
        move._base_power = power
    return move


def create_test_pokemon(species: str, moves: Optional[List[str]] = None) -> Pokemon:
    """Helper to create a Pokemon object for tests."""
    # Normalize species name for poke-env (e.g. Great Tusk -> greattusk)
    clean_species = species.lower().replace(" ", "").replace("-", "")
    mon = Pokemon(gen=9, species=clean_species)
    mon._max_hp = 300
    mon._current_hp = 300
    mon.stats = {"hp": 300, "atk": 300, "def": 250, "spa": 300, "spd": 250, "spe": 250}
    if moves:
        for m_name in moves:
            m_obj = create_test_move(m_name)
            mon._moves[m_obj.id] = m_obj
    return mon


class MockBattle:
    """Mock Battle object adhering to poke-env Battle interface."""

    def __init__(self):
        self.battle_tag = "battle-gen9ou-1"
        self.turn = 1
        self.format = "gen9ou"
        self.weather = None
        self.fields = None
        self.side_conditions = {}
        self.opponent_side_conditions = {}
        self.can_tera = True
        self.can_mega_evolve = False
        self.opponent_used_tera = False

        m1 = create_test_move("earthquake")
        m2 = create_test_move("closecombat")
        m3 = create_test_move("rapidspin")

        self.active_pokemon = create_test_pokemon("greattusk", moves=["earthquake", "closecombat", "rapidspin"])
        self.bench_mon = create_test_pokemon("kingambit", moves=["kowtowcleave", "ironhead"])
        self.team = {
            self.active_pokemon.species: self.active_pokemon,
            self.bench_mon.species: self.bench_mon,
        }

        opp_m1 = create_test_move("flamethrower")
        self.opponent_active_pokemon = create_test_pokemon("heatran", moves=["flamethrower"])
        self.opponent_team = {
            self.opponent_active_pokemon.species: self.opponent_active_pokemon
        }

        self.available_moves = [m1, m2, m3]
        self.available_switches = [self.bench_mon]
