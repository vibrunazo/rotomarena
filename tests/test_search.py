"""Tests for the PokéChamp search engine, opponent modeling, and the turn simulator."""

import pytest
from poke_env.battle import Pokemon, SideCondition
from rotomarena.search.minimax import PokeChampSearchEngine
from rotomarena.search.opponent_model import sample_opponent_actions
from rotomarena.search.simulator import entry_hazard_damage, estimate_damage_fraction, simulate_turn_outcome

from .mocks import MockBattle, create_test_move, create_test_pokemon


@pytest.mark.asyncio
async def test_sample_opponent_actions():
    battle = MockBattle()
    actions = sample_opponent_actions(battle, top_k=3)
    assert len(actions) > 0
    assert any("flamethrower" in tgt for _, tgt, _ in actions)


@pytest.mark.asyncio
async def test_pokechamp_search_prefers_earthquake_into_heatran():
    battle = MockBattle()
    order, telemetry = await PokeChampSearchEngine().search(battle)
    assert telemetry.nodes_evaluated > 0
    assert len(telemetry.candidate_scores) > 0
    assert "earthquake" in telemetry.best_action.lower()


def test_damage_against_an_opponent_uses_estimated_hp_not_the_percentage():
    # poke-env reports opposing HP out of 100 and leaves their stats unknown
    attacker = create_test_pokemon("greattusk")
    defender = Pokemon(gen=9, species="heatran")
    defender._max_hp = 100
    defender._current_hp = 100
    rapid_spin = create_test_move("rapidspin")  # 50 BP Normal, resisted by Steel

    damage = estimate_damage_fraction(rapid_spin, attacker, defender)
    assert 0.03 < damage < 0.15  # dividing by 100 HP instead would claim ~25%


def test_stealth_rock_hurts_by_rock_effectiveness():
    battle = MockBattle()
    battle.side_conditions = {SideCondition.STEALTH_ROCK: 1}
    charizard = Pokemon(gen=9, species="charizard")  # Fire/Flying: 4x weak to Rock
    kingambit = battle.bench_mon  # Dark/Steel: resists Rock
    assert entry_hazard_damage(battle, charizard) == pytest.approx(0.5)
    assert entry_hazard_damage(battle, kingambit) == pytest.approx(0.0625)


def test_switches_are_scored_per_target():
    battle = MockBattle()
    corviknight = create_test_pokemon("corviknight", moves=["bravebird"])
    battle.team[corviknight.species] = corviknight
    battle.available_switches = [battle.bench_mon, corviknight]
    scores = {
        # a Ground attack: Corviknight (Flying) takes nothing and holds; Kingambit (weak to it) only delays the loss
        mon.species: simulate_turn_outcome(battle, "SWITCH", mon.species, False, "MOVE", "attack_ground",
                                            weights={"switch_cost": 0.0})
        for mon in battle.available_switches
    }
    assert scores["corviknight"] > scores["kingambit"]


def test_a_known_immunity_ability_means_no_damage():
    from rotomarena.search.simulator import estimate_damage_fraction

    battle = MockBattle()
    target = create_test_pokemon("rotomwash")
    target._ability = "levitate"
    assert estimate_damage_fraction(battle.available_moves[0], battle.active_pokemon, target) == 0.0  # Earthquake


@pytest.mark.asyncio
async def test_a_status_move_beats_an_attack_the_target_is_immune_to():
    battle = MockBattle()
    great_tusk = create_test_pokemon("greattusk", moves=["earthquake", "swordsdance", "stealthrock"])
    battle.active_pokemon = great_tusk
    battle.available_moves = list(great_tusk.moves.values())
    rotom = create_test_pokemon("rotomwash", moves=["voltswitch"])
    rotom._ability = "levitate"
    battle.opponent_active_pokemon = rotom
    _, telemetry = await PokeChampSearchEngine().search(battle)
    assert "stealthrock" in telemetry.best_action.lower()  # Swords Dance only boosts the Earthquake


def test_protect_used_again_straight_away_is_worth_less():
    battle = MockBattle()
    great_tusk = create_test_pokemon("greattusk", moves=["protect"])
    battle.active_pokemon = great_tusk
    fresh = simulate_turn_outcome(battle, "MOVE", "protect", False, "MOVE", "flamethrower")
    great_tusk._protect_counter = 1
    again = simulate_turn_outcome(battle, "MOVE", "protect", False, "MOVE", "flamethrower")
    assert again < fresh
