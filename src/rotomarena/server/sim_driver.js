// RotomArena's battle driver: Pokémon Showdown's simulator, without its chat server. One Node process runs any
// number of battles at once; Python talks to it in JSON lines over stdin and stdout (rotomarena/server/sim.py).
//   node sim_driver.js <pokemon-showdown checkout>
// In:  {"id": tag, "start": {"formatid": ..., "seed": ...?}, "players": {"p1": {"name", "team"}, "p2": {...}}}
//      {"id": tag, "side": "p1", "choice": "move 1"}      a player's choice, as Showdown's /choose takes it
//      {"id": tag, "close": true}                        abandon a battle (its players failed)
// Out: {"id": tag, "to": "p1" | "p2", "data": ...}        what that player's client would receive
//      {"id": tag, "to": "spectator" | "omniscient", "data": ...}
//      {"id": tag, "end": {...}}                          the simulator's summary: winner, seed, input log...
//      {"id": tag, "error": ...}
'use strict';

const path = require('path');
const readline = require('readline');

const root = path.resolve(process.argv[2] || '.');
const {BattleStream} = require(path.join(root, 'dist', 'sim', 'battle-stream.js'));
const {extractChannelMessages} = require(path.join(root, 'dist', 'sim', 'battle.js'));
const {TeamValidator} = require(path.join(root, 'dist', 'sim', 'team-validator.js'));
const {Teams} = require(path.join(root, 'dist', 'sim', 'teams.js'));

const battles = new Map();

// A team as the server hands it to the simulator: validated for the format, which also applies the format's rules
// to the sets (Champions' "Adjust Level = 50": unvalidated, every Pokémon fights at level 100). Throws on an illegal
// team, as the server refuses one. Random-team formats have no team: the simulator deals one.
function validated(formatid, team) {
	if (!team) return team;
	const sets = Teams.unpack(team);
	const problems = TeamValidator.get(formatid).validateTeam(sets);
	if (problems && problems.length) throw new Error(`illegal team for ${formatid}: ${problems.join('; ')}`);
	return Teams.pack(sets);
}
const emit = (message) => process.stdout.write(JSON.stringify(message) + '\n');

async function pump(id, stream) {
	try {
		for await (const chunk of stream) {
			const cut = chunk.indexOf('\n');
			const type = cut < 0 ? chunk : chunk.slice(0, cut);
			const data = cut < 0 ? '' : chunk.slice(cut + 1);
			if (type === 'update') {
				// Lines after |split|pN come as a private (that side's) and a public version: hand each its own
				const channels = extractChannelMessages(data, [-1, 0, 1, 2]);
				emit({id, to: 'omniscient', data: channels[-1].join('\n')});
				emit({id, to: 'spectator', data: channels[0].join('\n')});
				emit({id, to: 'p1', data: channels[1].join('\n')});
				emit({id, to: 'p2', data: channels[2].join('\n')});
			} else if (type === 'sideupdate') {
				const side = data.slice(0, data.indexOf('\n'));
				emit({id, to: side, data: data.slice(side.length + 1)});
			} else if (type === 'end') {
				emit({id, end: JSON.parse(data)});
			}
		}
	} catch (err) {
		emit({id, error: String((err && err.stack) || err)});
	}
	battles.delete(id);
}

readline.createInterface({input: process.stdin}).on('line', (line) => {
	if (!line.trim()) return;
	let message;
	try {
		message = JSON.parse(line);
	} catch (err) {
		emit({id: null, error: `unreadable command: ${line.slice(0, 200)}`});
		return;
	}
	const {id} = message;
	if (message.start) {
		const players = {};
		try {
			for (const side of ['p1', 'p2']) {
				players[side] = {...message.players[side], team: validated(message.start.formatid, message.players[side].team)};
			}
		} catch (err) {
			emit({id, error: String(err.message || err)});
			return;
		}
		const stream = new BattleStream();
		battles.set(id, stream);
		void pump(id, stream);
		void stream.write(
			`>start ${JSON.stringify(message.start)}\n` +
			`>player p1 ${JSON.stringify(players.p1)}\n` +
			`>player p2 ${JSON.stringify(players.p2)}`
		);
	} else if (message.choice !== undefined) {
		const stream = battles.get(id);
		if (stream) void stream.write(`>${message.side} ${message.choice}`);
	} else if (message.close) {
		const stream = battles.get(id);
		if (stream) void stream.writeEnd();
		battles.delete(id);
	}
});
