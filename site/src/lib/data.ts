// Small helpers over the exported data. Numbers shown on the site come from here, never typed into copy.
import { getCollection, type CollectionEntry } from 'astro:content';
import metaJson from '../data/meta.json';
import findingsJson from '../data/findings.json';
import headToHeadJson from '../data/head_to_head.json';

export type Model = CollectionEntry<'models'>['data'];
export type Match = CollectionEntry<'matches'>['data'];
export type Draft = CollectionEntry<'drafts'>['data'];

export async function allDrafts(): Promise<Draft[]> {
  return (await getCollection('drafts')).map((e) => e.data);
}

export const meta = metaJson;
type H2H = { a: string; b: string; games: number; a_wins: number; b_wins: number; draws: number };
/** Head-to-head records on one leaderboard. */
export const headToHeadFor = (board: string): H2H[] => (headToHeadJson as Record<string, H2H[]>)[board] ?? [];

export type Board = { id: string; title: string; description: string; seasons: string[]; rated_matches: number; models: number };
/** The rankings, the first being the main one; each is fitted over the rated games of some seasons. */
export const boards = meta.leaderboards as Board[];
export const mainBoard = boards[0];

type Finding = { id: string; show: boolean; [key: string]: unknown };
export const findings: Record<string, Finding> = Object.fromEntries(
  (findingsJson as Finding[]).map((f) => [f.id, f]),
);

export async function allModels(): Promise<Model[]> {
  return (await getCollection('models')).map((e) => e.data);
}

/** The models on one leaderboard, with that board's rating fields, best first; unrated ones last. */
export async function boardModels(board: string = mainBoard.id): Promise<Model[]> {
  return (await allModels())
    .filter((m) => m.boards[board])
    .map((m) => ({ ...m, ...m.boards[board] }))
    .sort((a, b) => (b.rating ?? -Infinity) - (a.rating ?? -Infinity));
}

export async function modelsById(): Promise<Map<string, Model>> {
  return new Map((await allModels()).map((m) => [m.config_id, m]));
}

export type MatchEntry = { slug: string; data: Match };

/** Matches newest first; `slug` is the URL segment under /matches/ or /retracted/. */
export async function matchEntries(collection: 'matches' | 'retracted' = 'matches'): Promise<MatchEntry[]> {
  return (await getCollection(collection))
    .map((e) => ({ slug: e.id, data: e.data }))
    .sort((a, b) => b.data.id.localeCompare(a.data.id));
}

export const fmtDuration = (s: number) => (s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);

export const fmtRating = (r: number | null) => (r === null ? '—' : Math.round(r).toString());
export const fmtPct = (x: number, digits = 0) => `${(x * 100).toFixed(digits)}%`;
export const fmtInt = (n: number) => n.toLocaleString('en-US');

export function roleLabel(role: string): string | null {
  return { anchor: 'anchor', sparring: 'sparring partner', control: 'control group' }[role] ?? null;
}

/** "2026-10-07" from the export's "20261007". */
export const fmtDate = (d: string) => (d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : d);

export function winner(match: Match) {
  return match.players.find((p) => p.role === match.winner_role) ?? null;
}
