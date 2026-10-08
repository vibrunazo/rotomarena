// Data comes from `rotomarena export-site` (src/data). The site renders it; it never computes ratings.
import { defineCollection } from 'astro:content';
import { file, glob } from 'astro/loaders';
import { z } from 'astro/zod';

const player = z.object({
  config_id: z.string(),
  display_name: z.string(),
  agent_type: z.string(),
  provider: z.string().nullable(),
  model: z.string().nullable(),
  model_key: z.string().nullable(), // the weights' id across games and providers ('org/model'); null for bots
  quantization: z.string().nullable(),
  role: z.string(),
  team: z.string(),
  autopilot_rate: z.number(),
});

const decision = z.object({
  turn: z.number(),
  role: z.string(),
  action: z.object({ kind: z.string(), target: z.string(), tera: z.boolean() }),
  source: z.string(),
  thought: z.string(),
  hidden_reasoning: z.string().default(''),
  note: z.string(),
  tokens: z.number(),
  latency_ms: z.number(),
  cost_usd: z.number().default(0),
});

const match = z.object({
  id: z.string(),
  game: z.string(),
  format: z.string(),
  season: z.string().nullable(),
  date: z.string(),
  players: z.array(player),
  winner_role: z.string().nullable(),
  turns: z.number(),
  duration_seconds: z.number(),
  void_reason: z.string().nullable(),
  log: z.array(z.string()),
  decisions: z.array(decision),
});

const models = defineCollection({
  loader: file('src/data/models.json', {
    parser: (text) => JSON.parse(text).map((m: { config_id: string }) => ({ id: m.config_id, ...m })),
  }),
  schema: z.object({
    config_id: z.string(),
    display_name: z.string(),
    type: z.string(),
    role: z.string(),
    provider: z.string().nullable(),
    model: z.string().nullable(),
    model_key: z.string().nullable(),
    quantization: z.string().nullable(),
    rating: z.number().nullable(),
    ci_low: z.number().nullable(),
    ci_high: z.number().nullable(),
    provisional: z.boolean(),
    games: z.number(),
    wins: z.number(),
    losses: z.number(),
    draws: z.number(),
    win_rate: z.number(),
    turns: z.number(),
    autopilot_rate: z.number(),
    hallucinated_move_rate: z.number(),
    tokens_per_turn: z.number().nullable(),
    cost_per_game_usd: z.number(),
    switch_rate: z.number(),
    signature_move: z.string().nullable(),
    most_used_pokemon: z.string().nullable(),
    median_tera_turn: z.number().nullable(),
    longest_thought: z.string().nullable(),
    shortest_thought: z.string().nullable(),
    hallucinations: z.array(z.object({ action: z.string(), count: z.number() })),
    // standing on each leaderboard it has played on (rating fields above are the main board's)
    boards: z.record(z.string(), z.object({
      rating: z.number().nullable(), ci_low: z.number().nullable(), ci_high: z.number().nullable(), games: z.number(),
      wins: z.number(), losses: z.number(), draws: z.number(), win_rate: z.number(), provisional: z.boolean(),
    })),
  }),
});

const matches = defineCollection({ loader: glob({ pattern: '*.json', base: './src/data/matches' }), schema: match });
const retracted = defineCollection({ loader: glob({ pattern: '*.json', base: './src/data/retracted' }), schema: match });

// Teams the models built themselves from the format's rules (rotomarena teams draft), refereed by Showdown.
const member = z.object({
  species: z.string(), sprite: z.string().nullable(), item: z.string(), ability: z.string(), tera_type: z.string(),
  nature: z.string(), evs: z.record(z.string(), z.number()), moves: z.array(z.string()),
});
const drafts = defineCollection({
  loader: file('src/data/drafts.json', {
    parser: (text) => JSON.parse(text).map((d: { config_id: string }) => ({ id: d.config_id, ...d })),
  }),
  schema: z.object({
    config_id: z.string(), display_name: z.string(), model: z.string().nullable(), model_key: z.string().nullable(),
    format: z.string(), prompt_version: z.string(), drafted_at: z.string(), legal: z.boolean(),
    repaired: z.boolean(), repairs: z.array(z.string()),
    thought: z.string().nullable(), team_text: z.string().nullable(), members: z.array(member),
    attempts: z.array(z.object({
      attempt: z.number(), problems: z.array(z.string()), error: z.string().nullable().optional(),
      thought: z.string().nullable().optional(), team_text: z.string().nullable().optional(), tokens: z.number(),
      cost_usd: z.number(), finish_reason: z.string().nullable().optional(),
    })),
  }),
});

// Hand-written explanations shown on a model's page, one Markdown file per config id (src/content/about).
const about = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/about' }),
  schema: z.object({ title: z.string() }),
});

export const collections = { models, matches, retracted, about, drafts };
