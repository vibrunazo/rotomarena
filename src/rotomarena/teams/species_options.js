// Prints {species name: {name, types, abilities, moves}} as JSON: the abilities each Pokémon can have and the moves it
// can legally learn in the format, read from the local Showdown (run with cwd = its directory). Drafting stage 2
// gives these to the model for the six Pokémon it picked: the rules for those six, not advice.
// Usage: node species_options.js gen9ou "Great Tusk" "Kingambit" ...
'use strict';
const path = require('path');
const {Dex, TeamValidator} = require(path.join(process.cwd(), 'dist', 'sim'));

const formatId = process.argv[2] || 'gen9ou';
const format = Dex.formats.get(formatId);
const dex = Dex.forFormat(format);
const validator = TeamValidator.get(formatId);
const ruleTable = Dex.formats.getRuleTable(format);
const moves = dex.moves.all().filter((m) => !m.isNonstandard);

const out = {};
for (const name of process.argv.slice(3)) {
  const species = dex.species.get(name);
  if (!species.exists) { out[name] = null; continue; }
  out[name] = {
    name: species.name,
    types: species.types,
    abilities: Object.values(species.abilities).filter((a) => !ruleTable.has(`-ability:${dex.abilities.get(a).id}`)),
    moves: moves.filter((m) => !validator.checkCanLearn(m, species) && !ruleTable.has(`-move:${m.id}`))
      .map((m) => m.name).sort(),
  };
}
process.stdout.write(JSON.stringify(out));
