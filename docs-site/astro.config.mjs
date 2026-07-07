// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://udhawan97.github.io',
  base: '/FolioSenseAI',
  integrations: [
    starlight({
      title: 'FolioSenseAI',
      description: 'Docs for FolioSenseAI, a local-first portfolio intelligence dashboard.',
      logo: {
        src: './src/assets/folio-orbit-icon.svg',
        replacesTitle: false,
      },
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/udhawan97/FolioSenseAI' },
      ],
      customCss: ['./src/styles/custom.css'],
      editLink: {
        baseUrl: 'https://github.com/udhawan97/FolioSenseAI/edit/main/docs-site/',
      },
      sidebar: [
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
