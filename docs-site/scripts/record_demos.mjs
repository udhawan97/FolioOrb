/**
 * Record short product-demo video loops of the FolioSenseAI dashboard for the
 * landing page. Dev-only — Playwright and these recordings' source never ship
 * beyond the optimized files under public/assets/demos/.
 *
 * Prereq: the app must already be running with the seeded demo database
 * (record_demos.sh orchestrates seed → boot → record → encode → cleanup).
 *
 * Output: raw .webm captures in docs-site/_demos/raw/, later trimmed and
 * re-encoded to MP4/WebM + poster by encode_demos.sh.
 */
import { chromium } from 'playwright';
import { mkdir, rm, readdir, rename, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const BASE_URL = process.env.SHOT_BASE_URL || 'http://127.0.0.1:8177';
const __dirname = dirname(fileURLToPath(import.meta.url));
const RAW_DIR = join(__dirname, '..', '_demos', 'raw');

// CSS-pixel record size. Displayed <= 760px wide on the site, so this is ~2x
// density. Playwright records at this size regardless of deviceScaleFactor.
const SIZE = { width: 1600, height: 1000 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Each scene records one .webm. `run` receives the page and drives the app;
 * keep motions slow and end on a calm, held state so the loop seam is soft.
 */
const SCENES = [
  {
    name: 'news',
    // Preroll runs BEFORE the recorder marks the trim window, so the loop never
    // opens on the loading skeleton — it starts on already-populated headlines.
    async preroll(page) {
      await page.click('[data-zone="news"]').catch(() => {});
      await page.waitForSelector('[data-zone-pane="news"]', { state: 'visible', timeout: 15000 }).catch(() => {});
      await sleep(4200); // fully populate grouped headlines
    },
    async run(page) {
      // Gentle scroll through the (already loaded) grouped news, then settle.
      await page.mouse.wheel(0, 300);
      await sleep(1900);
      await page.mouse.wheel(0, 300);
      await sleep(1900);
      await page.mouse.wheel(0, -600);
      await sleep(2200); // hold calm final state
    },
  },
  {
    name: 'verdicts',
    async run(page) {
      await page.click('[data-zone="holdings"]').catch(() => {});
      await page.waitForSelector('[data-zone-pane="holdings"]', { state: 'visible', timeout: 15000 }).catch(() => {});
      await sleep(2600); // table + sparklines load
      // The app's signature interaction: expand a holding's intelligence panel.
      const firstRow = page.locator('#holdings-table tr[data-ticker]').first();
      await firstRow.click().catch(() => {});
      await sleep(3200); // verdict + detail panel reveal
      await page.mouse.wheel(0, 240);
      await sleep(2200); // hold
    },
  },
];

async function main() {
  await rm(RAW_DIR, { recursive: true, force: true });
  await mkdir(RAW_DIR, { recursive: true });

  const browser = await chromium.launch();

  for (const scene of SCENES) {
    // A fresh context per scene so each gets its own clean video file.
    const context = await browser.newContext({
      viewport: SIZE,
      deviceScaleFactor: 1,
      colorScheme: 'dark',
      recordVideo: { dir: RAW_DIR, size: SIZE },
    });
    const page = await context.newPage();
    const contextStart = Date.now();
    console.log(`[${scene.name}] loading ${BASE_URL} ...`);
    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 45000 });
    await page.keyboard.press('Escape').catch(() => {}); // dismiss any first-run modal
    await page
      .waitForFunction(() => {
        const el = document.querySelector('#total-value');
        return el && /\d/.test(el.textContent || '');
      }, { timeout: 30000 })
      .catch(() => console.log(`  (total-value wait timed out; recording anyway)`));
    // Hide the in-app onboarding banner so footage reads as a pure cockpit.
    await page.evaluate(() => {
      document.getElementById('local-intel-guide')?.setAttribute('hidden', '');
      document.querySelector('.local-intel-guide')?.style.setProperty('display', 'none');
    }).catch(() => {});
    await sleep(1200);

    // Optional preroll (navigation + data load) happens outside the trim window
    // so the loop never opens on a loading/skeleton state.
    if (scene.preroll) await scene.preroll(page);

    // Measure where the meaningful action starts/ends within the recording so
    // the encoder can trim off the page-load lead-in deterministically. Video
    // time tracks wall-clock, so these offsets translate directly to seconds.
    const actionStart = Date.now();
    await scene.run(page);
    const actionEnd = Date.now();

    const video = page.video();
    await context.close(); // finalizes the .webm
    if (video) {
      const src = await video.path();
      const dest = join(RAW_DIR, `${scene.name}.webm`);
      await rename(src, dest).catch(() => {});
      // 0.6s lead-in so the first action reads as motion, not a jump cut.
      const trimStart = Math.max(0.2, (actionStart - contextStart) / 1000 - 0.6);
      const duration = (actionEnd - actionStart) / 1000 + 1.0;
      await writeFile(join(RAW_DIR, `${scene.name}.json`), JSON.stringify({ trimStart, duration }));
      console.log(`  ✓ ${scene.name} → ${dest}  (trim ${trimStart.toFixed(1)}s, dur ${duration.toFixed(1)}s)`);
    }
  }

  await browser.close();

  // Clean up any stray Playwright-named files, leaving only <scene>.webm.
  const files = await readdir(RAW_DIR);
  console.log(`\nRaw captures: ${files.filter((f) => f.endsWith('.webm')).join(', ')}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
