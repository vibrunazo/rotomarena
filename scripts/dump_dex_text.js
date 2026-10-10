// Writes the one-line descriptions Showdown's tooltips show (moves, abilities, items) and each move's priority, for
// one data mod, to data/dex/<mod>.json: what the battle state quotes from battle_state 2 on (c4). Texts come from
// Showdown's data/text, with the mod's own texts on top (the Champions mod rewrites the moves it changes).
//   node scripts/dump_dex_text.js <mod: gen9 | champions>     (run from the repo root; reads our Showdown install)
const path = require('path');
const fs = require('fs');

const mod = process.argv[2] || 'gen9';
const root = path.resolve('server/pokemon-showdown/dist');
const {Dex} = require(path.join(root, 'sim/dex'));
const text = {
  moves: require(path.join(root, 'data/text/moves')).MovesText,
  abilities: require(path.join(root, 'data/text/abilities')).AbilitiesText,
  items: require(path.join(root, 'data/text/items')).ItemsText,
};
const dex = Dex.mod(mod);
const out = {mod, moves: {}, abilities: {}, items: {}};
const describe = (entry, base) => entry.shortDesc || entry.desc || (base && (base.shortDesc || base.desc)) || '';
for (const m of dex.moves.all()) {
  const desc = describe(m, text.moves[m.id]);
  if (desc) out.moves[m.id] = {desc, priority: m.priority};
}
for (const kind of ['abilities', 'items']) {
  for (const x of dex[kind].all()) {
    const desc = describe(x, text[kind][x.id]);
    if (desc) out[kind][x.id] = {desc};
  }
}
fs.mkdirSync('data/dex', {recursive: true});
fs.writeFileSync(`data/dex/${mod}.json`, JSON.stringify(out, null, 1) + '\n');
console.log(`data/dex/${mod}.json: ${Object.keys(out.moves).length} moves, ${Object.keys(out.abilities).length} abilities, ` +
  `${Object.keys(out.items).length} items`);
