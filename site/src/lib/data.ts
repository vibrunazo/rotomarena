// Small helpers over the exported data. Numbers shown on the site come from here, never typed into copy.
import { routes } from './routes';
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

export type Board = { id: string; title: string; description: string; kind: string; category: string | null; bench: string | null; versions: string[]; anchor: string; archived?: boolean; rated_matches: number; models: number };
/** The rankings: Overall first, then categories, then each benchmark; each fits the rated games of some ruleset versions. */
export const boards = meta.leaderboards as Board[];

export type Bench = { id: string; title: string; tagline: string; description: string; status: string; boards: string[]; main: string | null; rated_matches: number; models: number };
/** The benchmark families, presented like SWE-bench's: each has a page and a leaderboard tab; its first board is its main one. */
export const benches = (meta.benches ?? []) as Bench[];
export const liveBenches = benches.filter((b) => b.status === 'live' && b.main);
export const boardById = (id: string) => boards.find((b) => b.id === id);
/** The leaderboard at /leaderboard/: the first live bench's main board (Overall if there are no benches). */
export const mainBoard = (liveBenches[0] && boardById(liveBenches[0].main!)) || boards[0];
export const benchOf = (board: Board) => benches.find((b) => b.id === board.bench) ?? null;
/** A bench's current leaderboards (main first); superseded versions are on the archive page. */
export const benchBoards = (bench: Bench) => bench.boards.map(boardById).filter((b): b is Board => !!b && !b.archived);
/** Where a board lives: a benchmark's current board is the benchmark's page; the rest are under /leaderboard/. */
export const boardHref = (board: Board) => {
  const bench = benches.find((b) => b.main === board.id);
  return bench ? routes.bench(bench.id) : routes.board(board.id);
};
/** A cost in dollars, rounded up to a tenth of a cent so a paid model never reads as $0; 'free' only when it cost
 *  nothing (local models, free tiers). The tolerance keeps 0.013 from rounding up to 0.014. */
export const fmtCost = (usd: number) => (usd > 0 ? `$${(Math.ceil(usd * 1000 - 1e-9) / 1000).toFixed(3)}` : 'free');
/** The leaderboard: the main benchmark's page. */
export const leaderboardHref = () => routes.bench(liveBenches[0].id);
export const archivedBoards = (bench: Bench) => bench.boards.map(boardById).filter((b): b is Board => !!b && !!b.archived);

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

/** What a role tag means, for its tooltip (`type`: which control bot it is). */
export function roleTitle(role: string, type?: string): string | undefined {
  if (role === 'control') {
    // what every control is, then what this one measures
    const general = 'Control group: a scripted bot every model plays. It follows fixed rules instead of judgement, so it sets a bar to measure against.';
    const specific = type === 'pokechamp'
      ? 'This one searches: it simulates one turn of every move and switch against the replies it expects, and plays the safest. A model below it plays worse than a simple calculator.'
      : 'This one picks random moves. A model below it is probably broken, not just bad.';
    return `${general} ${specific}`;
  }
  return {
    anchor: 'The fixed point of the rating scale: pinned at 1500, so every other rating is measured against it',
    sparring: 'Plays every new model during placement, so the top of the table has a strong common opponent',
  }[role];
}

export const provisionalTitle = (games: number) =>
  `Fewer than ${games} rated games: the rating is an early estimate and can still move a lot`;

/** The contestants: language models and decision models (the rest are scripted bots). */
export const isModel = (m: { type: string }) => m.type === 'direct_llm' || m.type === 'decision';

/** "2026-10-07" from the export's "20261007". */
export const fmtDate = (d: string) => (d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : d);

export function winner(match: Match) {
  return match.players.find((p) => p.role === match.winner_role) ?? null;
}
