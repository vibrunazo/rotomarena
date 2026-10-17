// @ts-check
import { defineConfig } from 'astro/config';

import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';

// rotomarena.org, on Cloudflare Workers (static assets, site/wrangler.jsonc) since 17 Oct 2026. The old Netlify
// address redirects here (netlify-redirect/); a domain change means changing both.
export default defineConfig({
  site: 'https://rotomarena.org',
  integrations: [mdx(), sitemap()],
});
