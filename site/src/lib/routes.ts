// Every internal link goes through here. Moving the Pokémon pages under a game prefix later (a multi-game site)
// means changing these paths, moving the page files, and adding redirects in site/public/_redirects.
export const routes = {
  home: '/',
  // A benchmark's current leaderboard is its page (data.boardHref); these are Overall, categories, archived versions
  board: (id: string) => `/leaderboard/${id}/`,
  benchmarks: '/benchmarks/',
  archive: '/benchmarks/archive/',
  bench: (id: string) => `/benchmarks/${id}/`,
  matches: '/matches/',
  teams: '/teams/',
  retracted: '/retracted/',
  paper: '/paper/',
  citation: '/paper/#citation',
  faq: '/faq/',
  submit: '/submit/',
  changelog: '/changelog/',
  credits: '/credits/',
  model: (configId: string) => `/models/${configId}/`,
  match: (slug: string) => `/matches/${slug}/`,
  retractedMatch: (slug: string) => `/retracted/${slug}/`,
};
