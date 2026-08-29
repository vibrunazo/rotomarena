"""Smogon Gen 9 OU Team loader, parser, and Showdown packed format converter."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PokemonMember(BaseModel):
    """Structured representation of a single team member."""

    name: str
    species: str
    item: str = ""
    ability: str = ""
    tera_type: str = ""
    nature: str = "Serious"
    evs: Dict[str, int] = Field(
        default_factory=lambda: {
            "hp": 0,
            "atk": 0,
            "def": 0,
            "spa": 0,
            "spd": 0,
            "spe": 0,
        }
    )
    ivs: Dict[str, int] = Field(
        default_factory=lambda: {
            "hp": 31,
            "atk": 31,
            "def": 31,
            "spa": 31,
            "spd": 31,
            "spe": 31,
        }
    )
    moves: List[str] = Field(default_factory=list)
    gender: str = ""
    shiny: bool = False
    level: int = 100
    happiness: int = 255


class Team(BaseModel):
    """Structured representation of a 6-Pokémon team."""

    name: str = "Custom Team"
    members: List[PokemonMember] = Field(default_factory=list)
    raw_text: str = ""

    @property
    def is_valid(self) -> bool:
        return 1 <= len(self.members) <= 6

    def to_smogon_text(self) -> str:
        """Convert team back to standard Smogon export format."""
        blocks = []
        for mon in self.members:
            lines = []
            name_line = mon.species
            if mon.name and mon.name != mon.species:
                name_line = f"{mon.name} ({mon.species})"
            if mon.gender:
                name_line += f" ({mon.gender})"
            if mon.item:
                name_line += f" @ {mon.item}"
            lines.append(name_line)

            if mon.ability:
                lines.append(f"Ability: {mon.ability}")
            if mon.tera_type:
                lines.append(f"Tera Type: {mon.tera_type}")

            # EVs
            ev_parts = []
            ev_order = [("hp", "HP"), ("atk", "Atk"), ("def", "Def"), ("spa", "SpA"), ("spd", "SpD"), ("spe", "Spe")]
            for k, label in ev_order:
                val = mon.evs.get(k, 0)
                if val > 0:
                    ev_parts.append(f"{val} {label}")
            if ev_parts:
                lines.append(f"EVs: {' / '.join(ev_parts)}")

            if mon.nature:
                lines.append(f"{mon.nature} Nature")

            # IVs
            iv_parts = []
            for k, label in ev_order:
                val = mon.ivs.get(k, 31)
                if val < 31:
                    iv_parts.append(f"{val} {label}")
            if iv_parts:
                lines.append(f"IVs: {' / '.join(iv_parts)}")

            # Moves
            for move in mon.moves:
                lines.append(f"- {move}")

            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def to_showdown_packed(self) -> str:
        """Converts team to Showdown packed team string format."""
        packed_mons = []
        for mon in self.members:
            # Showdown packed format:
            # name|species|item|ability|moves|nature|evs|gender|ivs|shiny|level|misc
            name = mon.name if mon.name != mon.species else ""
            species = mon.species
            item = mon.item
            ability = mon.ability
            moves = ",".join(mon.moves)
            nature = mon.nature
            
            ev_list = [
                str(mon.evs.get("hp", 0)),
                str(mon.evs.get("atk", 0)),
                str(mon.evs.get("def", 0)),
                str(mon.evs.get("spa", 0)),
                str(mon.evs.get("spd", 0)),
                str(mon.evs.get("spe", 0)),
            ]
            evs = ",".join(ev_list) if any(v != "0" for v in ev_list) else ""
            
            gender = mon.gender
            iv_list = [
                str(mon.ivs.get("hp", 31)),
                str(mon.ivs.get("atk", 31)),
                str(mon.ivs.get("def", 31)),
                str(mon.ivs.get("spa", 31)),
                str(mon.ivs.get("spd", 31)),
                str(mon.ivs.get("spe", 31)),
            ]
            ivs = ",".join(iv_list) if any(v != "31" for v in iv_list) else ""
            shiny = "S" if mon.shiny else ""
            level = str(mon.level) if mon.level != 100 else ""
            
            # misc: happiness,pokeball,hiddenpowertype,gmax,dynamaxlevel,teratype
            misc = ""
            if mon.tera_type:
                misc = f",,,,,{mon.tera_type}"

            packed = f"{name}|{species}|{item}|{ability}|{moves}|{nature}|{evs}|{gender}|{ivs}|{shiny}|{level}|{misc}"
            packed_mons.append(packed)

        return "]".join(packed_mons)


def parse_smogon_team(text: str, name: str = "Custom Team") -> Team:
    """Parse a Smogon text export into a Team object."""
    cleaned = text.replace("\r\n", "\n").strip()
    raw_blocks = [b.strip() for b in cleaned.split("\n\n") if b.strip()]
    members: List[PokemonMember] = []

    stat_key_map = {
        "hp": "hp",
        "atk": "atk",
        "def": "def",
        "spa": "spa",
        "spd": "spd",
        "spe": "spe",
        "attack": "atk",
        "defense": "def",
        "spatk": "spa",
        "spdef": "spd",
        "speed": "spe",
        "special attack": "spa",
        "special defense": "spd",
    }

    for block in raw_blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        # First line: [Nickname (Species)] or [Species] [(Gender)] [@ Item]
        first_line = lines[0]
        item = ""
        if "@" in first_line:
            parts = first_line.split("@", 1)
            first_line = parts[0].strip()
            item = parts[1].strip()

        gender = ""
        gender_match = re.search(r"\((M|F)\)$", first_line)
        if gender_match:
            gender = gender_match.group(1)
            first_line = first_line[: gender_match.start()].strip()

        species_match = re.search(r"\((.*?)\)$", first_line)
        if species_match:
            species = species_match.group(1).strip()
            mon_name = first_line[: species_match.start()].strip()
        else:
            species = first_line.strip()
            mon_name = species

        ability = ""
        tera_type = ""
        nature = "Serious"
        evs = {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
        ivs = {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}
        moves: List[str] = []
        shiny = False
        level = 100

        for line in lines[1:]:
            if line.startswith("Ability:"):
                ability = line.replace("Ability:", "").strip()
            elif line.startswith("Tera Type:"):
                tera_type = line.replace("Tera Type:", "").strip()
            elif line.startswith("Shiny:"):
                shiny = line.replace("Shiny:", "").strip().lower() == "yes"
            elif line.startswith("Level:"):
                try:
                    level = int(line.replace("Level:", "").strip())
                except ValueError:
                    level = 100
            elif line.endswith("Nature") or "Nature" in line:
                nature = line.split()[0].strip()
            elif line.startswith("EVs:"):
                ev_str = line.replace("EVs:", "").strip()
                for part in ev_str.split("/"):
                    tokens = part.strip().split()
                    if len(tokens) >= 2:
                        val, stat = tokens[0], tokens[1].lower()
                        normalized_stat = stat_key_map.get(stat)
                        if normalized_stat and val.isdigit():
                            evs[normalized_stat] = int(val)
            elif line.startswith("IVs:"):
                iv_str = line.replace("IVs:", "").strip()
                for part in iv_str.split("/"):
                    tokens = part.strip().split()
                    if len(tokens) >= 2:
                        val, stat = tokens[0], tokens[1].lower()
                        normalized_stat = stat_key_map.get(stat)
                        if normalized_stat and val.isdigit():
                            ivs[normalized_stat] = int(val)
            elif line.startswith("-") or line.startswith("•"):
                move_name = line.lstrip("-• ").strip()
                if move_name:
                    moves.append(move_name)

        members.append(
            PokemonMember(
                name=mon_name,
                species=species,
                item=item,
                ability=ability,
                tera_type=tera_type,
                nature=nature,
                evs=evs,
                ivs=ivs,
                moves=moves,
                gender=gender,
                shiny=shiny,
                level=level,
            )
        )

    return Team(name=name, members=members, raw_text=text)


def load_team_file(file_path: str | Path) -> Team:
    """Load and parse a team from a .txt file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Team file not found at: {path}")
    content = path.read_text(encoding="utf-8")
    team_name = path.stem.replace("_", " ").title()
    return parse_smogon_team(content, name=team_name)
