// Prints {species name: Showdown sprite id} as JSON for the names given (run with cwd = the Showdown install).
// Sprite ids aren't derivable from names ("Ting-Lu" is tinglu, "Ogerpon-Wellspring" is ogerpon-wellspring).
'use strict';
const path = require('path');
const {Dex} = require(path.join(process.cwd(), 'dist', 'sim'));

const out = {};
for (const name of process.argv.slice(2)) {
  const species = Dex.species.get(name);
  out[name] = species.exists ? species.spriteid : null;
}
process.stdout.write(JSON.stringify(out));
