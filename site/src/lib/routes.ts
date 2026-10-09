// Every internal link goes through here. Moving the Pokémon pages under a game prefix later (a multi-game site)
// means changing these paths, moving the page files, and adding redirects in netlify.toml.
export const routes = {
  home: '/',
  leaderboard: '/leaderboard/',
  board: (id: string, main: boolean) => (main ? '/leaderboard/' : `/leaderboard/${id}/`),
  benchmarks: '/benchmarks/',
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
