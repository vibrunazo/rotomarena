// RotomArena's own formats for the local Showdown server. server/manager.py copies this file to
// dist/config/custom-formats.js at every start, where Showdown merges it into its format list (no build needed).
'use strict';

exports.Formats = [
	{
		section: "RotomArena",
	},
	{
		// Pokémon Champions Battle Stadium Singles, Regulation M-B, with teams the players build: the same rules as
		// [Gen 9 Champions] BSS Reg M-B (Flat Rules: level 50, bring 6 pick 3, Item Clause, no Mythicals or Restricted
		// Legendaries) but one game instead of a best-of-three, and no VGC Timer.
		name: "[Gen 9 Champions] RotomArena BSS Reg M-B",
		mod: 'champions',
		ruleset: ['Flat Rules'],
	},
	{
		// Pokémon Champions singles, for testing the waters: every player is dealt a Champions Random Battle team
		// (levels around 50, balanced by strength; Megas included) and picks 3 of its 6 at team preview, as in
		// Battle Stadium Singles. Unlike [Gen 9 Champions] BSS Reg M-B it plays one game, not a best-of-three,
		// and has no VGC Timer: the models take as long as the ruleset allows.
		name: "[Gen 9 Champions] RotomArena Random BSS",
		mod: 'champions',
		team: 'random',
		ruleset: [
			'Obtainable', 'Species Clause', 'Cancel Mod', 'Sleep Clause Mod', 'Illusion Level Mod', 'Level Clause Mod',
			'Team Preview', 'Picked Team Size = 3',
		],
	},
];
