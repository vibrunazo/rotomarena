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
  username: z.string().optional(), // its Showdown name in this game (with a lane number in parallel games)
  replay_name: z.string().optional(), // the replay's trainer label: its display name, or username in a mirror match
  team: z.string(),
  autopilot_rate: z.number(),
});

const decision = z.object({
  turn: z.number(),
  role: z.string(),
  action: z.object({ kind: z.string(), target: z.string(), tera: z.boolean(), mega: z.boolean().optional() }),
  source: z.string(),
  thought: z.string(),
  hidden_reasoning: z.string().default(''),
  probabilities: z.record(z.string(), z.number()).nullable().optional(), // decision models: every option's probability
  note: z.string(),
  tokens: z.number(),
  latency_ms: z.number(),
  cost_usd: z.number().default(0),
});

const match = z.object({
  id: z.string(),
  game: z.string(),
  format: z.string(),
  version: z.string().nullable(), // the ruleset version the game was played under
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
    retired: z.boolean().default(false),  // no longer played: off the leaderboards, its games still rated
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
    weights: z.enum(['open', 'closed']).nullable().optional(),
    params_b: z.number().nullable().optional(), // total parameters (billions), when published
    released: z.string().nullable().optional(), // release date, YYYY-MM-DD (OpenRouter listing, Hugging Face, or snapshot)
    price_tier: z.string().nullable().optional(), // by cost per game in the main benchmark (meta.price_tiers)
    tier_cost_usd: z.number().optional(),
    switch_rate: z.number(),
    signature_move: z.string().nullable(),
    most_used_pokemon: z.string().nullable(),
    median_tera_turn: z.number().nullable(),
    median_mega_turn: z.number().nullable().optional(),
    gimmicks: z.array(z.string()).optional(), // 'tera' (Gen 9 OU) and/or 'mega' (Champions): what its games allowed
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
  smogon_teams: z.number(), // how many of Smogon's sample teams use this Pokémon
  fallback: z.boolean(), // put in by the referee (an empty or illegal slot), not picked by the model
  // what its item, ability, nature and each move do (Showdown's tooltip texts), for hover tips
  notes: z.object({ item: z.string(), ability: z.string(), nature: z.string(), moves: z.record(z.string(), z.string()) }).optional(),
});
const drafts = defineCollection({
  loader: file('src/data/drafts.json', {
    parser: (text) => JSON.parse(text).map((d: { config_id: string; version: string; draft?: number }) => ({ id: `${d.version}-${d.config_id}-${d.draft ?? 1}`, ...d })),
  }),
  schema: z.object({
    config_id: z.string(), version: z.string(), format: z.string(), bench: z.string().nullable(),
    draft: z.number().default(1), drafts: z.number().default(1), // one of a model's drafts, in the order its games play them
    display_name: z.string(), model: z.string().nullable(), model_key: z.string().nullable(),
    format: z.string(), prompt_version: z.string(), drafted_at: z.string(), legal: z.boolean(),
    repaired: z.boolean(), repairs: z.array(z.string()),
    picks: z.object({
      legal: z.boolean(), species: z.array(z.string()), repairs: z.array(z.string()),
      attempts: z.array(z.object({
        attempt: z.number(), problems: z.array(z.string()), error: z.string().nullable().optional(),
        pokemon: z.array(z.string()), thought: z.string().nullable().optional(), tokens: z.number(),
      })),
    }),
    thought: z.string().nullable(), team_text: z.string().nullable(), members: z.array(member),
    meta: z.object({ used: z.number(), of: z.number(), slots: z.number(), fallbacks: z.number(), sample_teams: z.number() }),
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
