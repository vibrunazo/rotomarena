// Prints a Showdown format's rules as JSON, read from the local Showdown install (run with cwd = its directory):
// the legal species (each checked with the real validator), the clauses with their descriptions, and the banned
// abilities, moves and items, and the items, natures and Tera Types a set can use. Usage: node format_rules.js gen9ou
'use strict';
const path = require('path');
const {Dex, TeamValidator} = require(path.join(process.cwd(), 'dist', 'sim'));

const formatId = process.argv[2] || 'gen9ou';
const format = Dex.formats.get(formatId);
const dex = Dex.forFormat(format);
const validator = TeamValidator.get(formatId);
const ruleTable = Dex.formats.getRuleTable(format);

// A species is legal unless the validator bans it ("Roaring Moon is tagged Uber, which is banned"). The placeholder
// set's other problems (an unlearnable placeholder move, a banned first ability) are about the set, not the species.
// Formes that need an item (Arceus-Fire, Giratina-Origin) get it, so the validator judges the forme itself.
const BANNED = /is tagged .+ which is banned|is banned\.|does not exist|is unreleased|not obtainable|isn't available/;
const legal = [];
const base = {};
for (const species of dex.species.all()) {
  if (species.battleOnly || species.isNonstandard) continue;
  const set = {
    name: species.name, species: species.name, item: species.requiredItem || (species.requiredItems || [''])[0],
    ability: Object.values(species.abilities)[0], moves: ['protect'], nature: 'Serious', gender: '', level: 100,
    evs: {hp: 4, atk: 0, def: 0, spa: 0, spd: 0, spe: 0}, ivs: {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31},
  };
  const problems = validator.validateTeam([set]) || [];
  if (!problems.some((p) => BANNED.test(p) && !p.startsWith(`${species.name}'s`))) {
    legal.push(species.name);
    base[species.name] = species.baseSpecies;  // Species Clause counts base species (Ogerpon and Ogerpon-Wellspring)
  }
}

const clauses = [];
const banned = {abilities: [], moves: [], items: []};
for (const [rule] of ruleTable) {
  if (rule.startsWith('-')) {
    const [kind, id] = rule.slice(1).split(':');
    if (kind === 'ability') banned.abilities.push(dex.abilities.get(id).name);
    else if (kind === 'move') banned.moves.push(dex.moves.get(id).name);
    else if (kind === 'item') banned.items.push(dex.items.get(id).name);
    continue;
  }
  if (rule.startsWith('+') || rule.startsWith('*') || rule.startsWith('!')) continue;
  const r = Dex.formats.get(rule);
  if (r.exists && r.desc && !/^(Standard|Obtainable|Team Preview|Cancel Mod|HP Percentage Mod|Endless Battle Clause|Nickname Clause|Team Species Preview|Min Source Gen|Sketch Post-Gen 7 Moves|Illusion Level Mod|Overflow Stat Mod|Max Team Size|Default Level|Picked Team Size)/.test(r.name)) {
    clauses.push(`${r.name}: ${r.desc}`);
  }
}

// What a set can hold, for players that pick from lists (decision models): the format's items, natures and Tera Types.
const items = dex.items.all().filter((i) => !i.isNonstandard && !banned.items.includes(i.name)).map((i) => i.name).sort();
const STAT = {atk: 'Atk', def: 'Def', spa: 'SpA', spd: 'SpD', spe: 'Spe'};
const natures = dex.natures.all().map((n) => ({name: n.name, plus: STAT[n.plus] || null, minus: STAT[n.minus] || null}));
const types = dex.types.names();  // Stellar included

process.stdout.write(JSON.stringify({format: format.name, id: format.id, species: legal, base, clauses, banned, items, natures, types}));
