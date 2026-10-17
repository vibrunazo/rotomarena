// @ts-check
import { defineConfig } from 'astro/config';

import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';

// Hosted on Cloudflare Workers (static assets, site/wrangler.jsonc) since 17 Oct 2026; the old Netlify address
// redirects here (netlify-redirect/). A custom domain later means changing this and that redirect.
export default defineConfig({
  site: 'https://rotomarena.vibrunazo.workers.dev',
  integrations: [mdx(), sitemap()],
});
