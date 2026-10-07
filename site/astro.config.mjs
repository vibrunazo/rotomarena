// @ts-check
import { defineConfig } from 'astro/config';

import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';

// The domain isn't decided yet; this is the Netlify default for a site named "rotomarena".
export default defineConfig({
  site: 'https://rotomarena.netlify.app',
  integrations: [mdx(), sitemap()],
});
