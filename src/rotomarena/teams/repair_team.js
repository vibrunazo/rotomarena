// Makes a team legal for a format by replacing only what the validator rejects, with deliberately middling choices:
// a handicap for the mistake, not a punishment and not an upgrade. Reads the team (Showdown export format) on stdin,
// prints {team, changes} as JSON. Usage (cwd = the Showdown install): node repair_team.js gen9ou <seed>
//
// - A rejected Pokémon (banned, unknown, a duplicate) becomes a fallback Pokémon: one from the middle of Showdown's
//   Random Battles pool (levels 84-88, where the balancing puts solid but unexceptional Pokémon), with its first
//   Random Battles set's moves, ability and Tera Type, Leftovers, an even 84 EVs in every stat and a neutral nature.
// - A rejected move is replaced by a legal move from that Pokémon's Random Battles move pool (else dropped); a
//   rejected ability, item, Tera Type, nature or EV spread by the first legal ability, Leftovers, its own type,
//   a neutral nature, or the even spread.
// - Missing slots are filled with fallback Pokémon, so the team always has six.
'use strict';
const path = require('path');
const fs = require('fs');
const {Dex, Teams, TeamValidator} = require(path.join(process.cwd(), 'dist', 'sim'));
const randomSets = require(path.join(process.cwd(), 'dist', 'data', 'random-battles', 'gen9', 'sets.json'));

const formatId = process.argv[2] || 'gen9ou';
const seed = process.argv[3] || 'seed';
const dex = Dex.forFormat(Dex.formats.get(formatId));
const validator = TeamValidator.get(formatId);
const changes = [];

const EVEN_EVS = {hp: 84, atk: 84, def: 84, spa: 84, spd: 84, spe: 84};
const IVS = {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31};
const problemsOf = (set) => validator.validateSet(set, {}) || [];
const hash = (text) => [...text].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);

function fallbackSet(usedSpecies, slot) {
  const pool = Object.entries(randomSets)
    .filter(([, data]) => data.level >= 84 && data.level <= 88)
    .map(([id, data]) => [dex.species.get(id), data.sets[0]])
    .filter(([species]) => species.exists && !usedSpecies.has(species.baseSpecies))
    .sort((a, b) => a[0].name.localeCompare(b[0].name));
  const start = hash(`${seed}:${slot}`) % pool.length;
  for (let i = 0; i < pool.length; i++) {
    const [species, rset] = pool[(start + i) % pool.length];
    const set = {
      name: species.name, species: species.name, item: 'Leftovers', ability: rset.abilities[0],
      moves: rset.movepool.slice(0, 4), nature: 'Serious', gender: '', level: 100, evs: {...EVEN_EVS}, ivs: {...IVS},
      teraType: (rset.teraTypes || species.types)[0],
    };
    if (!problemsOf(set).length) return set;
  }
  throw new Error('no legal fallback Pokémon');
}

function fixSet(set) {
  const species = dex.species.get(set.species);
  set.level = 100;
  set.ivs = {...IVS, ...(set.ivs || {})};
  const has = (text) => problemsOf(set).some((p) => p.toLowerCase().includes(text.toLowerCase()));
  const note = (what) => changes.push(`${species.name}: ${what}`);

  const evs = Object.values(set.evs || {});
  if (!set.evs || evs.some((v) => v > 252) || evs.reduce((a, b) => a + b, 0) > 510) {
    set.evs = {...EVEN_EVS}; note('EV spread replaced by an even 84 in every stat');
  }
  if (!dex.natures.get(set.nature || '').exists) { set.nature = 'Serious'; note('nature set to Serious'); }
  const abilities = Object.values(species.abilities);
  if (!abilities.map((a) => a.toLowerCase()).includes((set.ability || '').toLowerCase()) || has('ability')) {
    const legal = abilities.find((a) => { set.ability = a; return !has('ability'); });
    note(`ability replaced by ${legal}`); set.ability = legal;
  }
  if (has("'s item") || has('item') && !dex.items.get(set.item).exists) { note(`item ${set.item} replaced by Leftovers`); set.item = 'Leftovers'; }
  if (has('Terastal') || has('Tera Type')) { note(`Tera Type replaced by ${species.types[0]}`); set.teraType = species.types[0]; }

  const pool = (randomSets[species.id] || randomSets[toId(species.baseSpecies)] || {sets: []}).sets.flatMap((s) => s.movepool);
  const moves = [...new Set((set.moves || []).filter((m) => dex.moves.get(m).exists))];
  set.moves = moves;
  for (const move of moves) {
    if (!problemsOf(set).some((p) => p.includes(dex.moves.get(move).name))) continue;
    const others = set.moves.filter((m) => m !== move);
    const swap = pool.find((m) => !others.includes(m) && !problemsOf({...set, moves: [...others, m]}).some((p) => p.includes(m)));
    set.moves = swap ? [...others, swap] : others;
    note(swap ? `move ${dex.moves.get(move).name} replaced by ${swap}` : `move ${dex.moves.get(move).name} removed`);
  }
  if (!set.moves.length && pool.length) { set.moves = pool.slice(0, 1); note(`given ${pool[0]}, having no legal move`); }
  return set;
}

function toId(text) { return (text || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }

let sets = [];
try { sets = Teams.import(fs.readFileSync(0, 'utf8')) || []; } catch (e) { sets = []; }
const team = [];
const used = new Set();
for (const set of sets.slice(0, 6)) {
  const species = dex.species.get(set.species);
  const legalSpecies = species.exists && !used.has(species.baseSpecies) &&
    !problemsOf({...set, ability: Object.values(species.abilities)[0], moves: [], item: '', evs: {...EVEN_EVS}})
      .some((p) => /is tagged .+ which is banned|does not exist|is unreleased|not obtainable/.test(p));
  if (!legalSpecies) {
    const fallback = fallbackSet(used, team.length);
    changes.push(`${set.species || 'An unreadable Pokémon'} replaced by ${fallback.species} (` +
      (species.exists ? (used.has(species.baseSpecies) ? 'a second one of the same species' : 'not legal in the format') : 'not a Pokémon') + ')');
    team.push(fallback);
  } else {
    let fixed = fixSet(set);
    if (problemsOf(fixed).length) {
      const fallback = fallbackSet(used, team.length);
      changes.push(`${species.name} replaced by ${fallback.species} (could not be made legal: ${problemsOf(fixed)[0]})`);
      fixed = fallback;
    }
    team.push(fixed);
  }
  used.add(dex.species.get(team[team.length - 1].species).baseSpecies);
}
while (team.length < 6) {
  const fallback = fallbackSet(used, team.length);
  changes.push(`empty slot filled with ${fallback.species}`);
  team.push(fallback); used.add(dex.species.get(fallback.species).baseSpecies);
}
const remaining = validator.validateTeam(team) || [];
process.stdout.write(JSON.stringify({team: Teams.export(team).trim(), changes, problems: remaining}));
