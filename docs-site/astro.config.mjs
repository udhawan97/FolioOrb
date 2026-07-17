// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://udhawan97.github.io',
  base: '/FolioOrb',
  integrations: [
    starlight({
      title: 'FolioOrb',
      description: 'Docs for FolioOrb, a local-first portfolio intelligence dashboard.',
      logo: {
        src: './src/assets/folio-orbit-icon.svg',
        replacesTitle: false,
      },
      favicon: '/assets/folio-orbit-icon.svg',
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/udhawan97/FolioOrb' },
      ],
      customCss: ['./src/styles/custom.css'],
      // The docs share the landing page's type system (see src/styles/tokens.css).
      // The landing page loads these itself in its own <head>.
      head: [
        { tag: 'link', attrs: { rel: 'preconnect', href: 'https://fonts.googleapis.com' } },
        { tag: 'link', attrs: { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: true } },
        {
          tag: 'link',
          attrs: {
            rel: 'stylesheet',
            href: 'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap',
          },
        },
      ],
      components: {
        Search: './src/components/Search.astro',
        TableOfContents: './src/components/TableOfContents.astro',
      },
      editLink: {
        baseUrl: 'https://github.com/udhawan97/FolioOrb/edit/main/docs-site/',
      },
      sidebar: [
        {
          label: 'Download & Install',
          items: [
            { label: 'Download', slug: 'download' },
            { label: 'Install on macOS', slug: 'install-macos' },
            { label: 'Install on Windows', slug: 'install-windows' },
            { label: 'Updating', slug: 'updating' },
            { label: 'Build from source', slug: 'build-from-source' },
            { label: 'Releases & versioning', slug: 'releases-and-versioning' },
          ],
        },
        {
          label: "What's Next",
          items: [{ label: 'Roadmap', slug: 'roadmap' }],
        },
        {
          label: 'Get Started',
          items: [
            { label: 'Introduction', slug: 'get-started/introduction' },
            { label: 'Installation', slug: 'get-started/installation' },
            { label: 'Optional Claude Setup', slug: 'get-started/claude-setup' },
          ],
        },
        {
          label: 'Using The Dashboard',
          items: [
            { label: 'Overview & Holdings', slug: 'dashboard/overview-holdings' },
            { label: 'Analytics & Risk', slug: 'dashboard/analytics-risk' },
            { label: 'News & Market Context', slug: 'dashboard/news-market-context' },
            { label: 'Action Plan', slug: 'dashboard/action-plan' },
          ],
        },
        {
          label: 'Claude AI Integration',
          items: [{ label: 'Narration, cost tracking & fallback', slug: 'claude-ai-integration' }],
        },
        {
          label: 'Meet Senpai',
          items: [{ label: 'The dashboard orb', slug: 'meet-senpai' }],
        },
        {
          label: 'Under The Hood',
          items: [
            { label: 'Architecture', slug: 'architecture' },
            { label: 'Privacy & Data Handling', slug: 'privacy' },
          ],
        },
        {
          label: 'Help',
          items: [
            { label: 'Troubleshooting & FAQ', slug: 'troubleshooting' },
            { label: 'Release Notes', slug: 'release-notes' },
          ],
        },
      ],
    }),
  ],
});
