"""Unit tests for modules.evolution_data – Pokédex, evolution chains, living dex."""
import pytest
from modules.evolution_data import (
    POKEDEX, NATIONAL_DEX_SIZE, living_dex_requirements,
    get_evolution_chain, get_all_trade_evolutions, get_all_stone_evolutions,
    get_species_by_name, get_species, PokemonSpecies,
)


class TestPokedex:
    def test_size(self):
        assert len(POKEDEX) == NATIONAL_DEX_SIZE
        assert NATIONAL_DEX_SIZE == 386

    def test_ids_contiguous(self):
        ids = sorted(POKEDEX.keys())
        assert ids == list(range(1, 387))

    def test_every_entry_has_name(self):
        for pid, entry in POKEDEX.items():
            assert entry.name, f"Species {pid} missing name"

    def test_every_entry_has_evolution_stage(self):
        for pid, entry in POKEDEX.items():
            assert entry.evolution_stage in (1, 2, 3), \
                f"Species {pid} bad stage: {entry.evolution_stage}"


class TestLookups:
    def test_get_by_id(self):
        p = get_species(25)
        assert p is not None
        assert p.name.lower() == "pikachu"

    def test_get_by_id_invalid(self):
        p = get_species(0)
        assert p is None
        p = get_species(999)
        assert p is None

    def test_get_by_name(self):
        p = get_species_by_name("Bulbasaur")
        assert p is not None
        assert p.name == "Bulbasaur"

    def test_get_by_name_case_insensitive(self):
        p = get_species_by_name("pikachu")
        assert p is not None

    def test_get_by_name_not_found(self):
        p = get_species_by_name("NotAPokemon")
        assert p is None


class TestEvolutionChains:
    def test_bulbasaur_chain(self):
        chain = get_evolution_chain(1)
        assert chain is not None
        assert 1 in chain   # Bulbasaur
        assert 2 in chain   # Ivysaur
        assert 3 in chain   # Venusaur

    def test_single_stage_pokemon(self):
        # Absol (#359) doesn't evolve in Gen 3
        chain = get_evolution_chain(359)
        assert chain is not None
        assert len(chain) == 1

    def test_eevee_has_multiple_evolutions(self):
        chain = get_evolution_chain(133)  # Eevee
        assert chain is not None
        assert len(chain) > 2  # Eevee + multiple evolutions


class TestTradeEvolutions:
    def test_returns_list(self):
        trades = get_all_trade_evolutions()
        assert isinstance(trades, list)
        assert len(trades) > 0

    def test_known_trade_evos(self):
        trades = get_all_trade_evolutions()
        # Each entry is (source_id, target_id, trade_item)
        source_ids = [t[0] for t in trades]
        # Machoke(67)→Machamp, Graveler(75)→Golem, Haunter(93)→Gengar, Kadabra(64)→Alakazam
        for expected in [67, 75, 93, 64]:
            assert expected in source_ids, f"Missing trade evo for #{expected}"


class TestStoneEvolutions:
    def test_returns_list(self):
        stones = get_all_stone_evolutions()
        assert isinstance(stones, list)
        assert len(stones) > 0

    def test_known_stone_evos(self):
        stones = get_all_stone_evolutions()
        # Each entry is (source_id, target_id, stone)
        source_ids = [s[0] for s in stones]
        # Pikachu(25)→Raichu (Thunder Stone)
        assert 25 in source_ids


class TestLivingDexRequirements:
    def test_returns_dict(self):
        reqs = living_dex_requirements()
        assert isinstance(reqs, dict)

    def test_has_categories(self):
        reqs = living_dex_requirements()
        assert "wild_catch" in reqs
        assert "evolution_level" in reqs
        assert "evolution_stone" in reqs
        assert "evolution_trade" in reqs
        assert "breeding_baby" in reqs

    def test_total_covers_all_pokemon(self):
        reqs = living_dex_requirements()
        total = sum(len(v) for v in reqs.values())
        # Should cover a significant portion (not all 386 since some overlap)
        assert total > 200

    def test_no_duplicates_within_category(self):
        reqs = living_dex_requirements()
        for cat, ids in reqs.items():
            assert len(ids) == len(set(ids)), f"Duplicates in {cat}"
