/**
 * Capture retina product screenshots of the FolioOrb dashboard for the
 * landing page. Dev-only — Playwright and this script never ship to the site.
 *
 * Prereqs: the app must already be running with the seeded demo database
 * (see capture.sh, which orchestrates seed → boot → capture → optimize).
 *
 * Output: optimized WebP files in docs-site/src/assets/shots/, captured at
 * deviceScaleFactor 2 so they stay crisp on retina displays.
 */
import { chromium } from 'playwright';
import sharp from 'sharp';
import { mkdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const BASE_URL = process.env.SHOT_BASE_URL || 'http://127.0.0.1:8177';
const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = join(__dirname, '..', 'public', 'assets', 'shots');
const RAW_DIR = join(__dirname, '..', '_shots', 'raw');

const VIEWPORT = { width: 1512, height: 950 };
const SCALE = 2;

// Each shot: name, how to reach it, what to capture, and the final WebP width.
// `zone` clicks the top dashboard tab; `analyticsPane` clicks an analytics sub-tab.
const SHOTS = [
  { name: 'hero-dashboard-demo', zone: 'overview', mode: 'viewport', outWidth: 2400 },
  { name: 'verdicts-demo', zone: 'holdings', selector: '[data-zone-pane="holdings"]', outWidth: 1600 },
  { name: 'risk-analytics-demo', zone: 'analytics', analyticsPane: 'risk', selector: '.analytics-sub-pane[data-analytics-pane="risk"]', outWidth: 1600 },
  { name: 'news-themes-demo', zone: 'news', selector: '[data-zone-pane="news"]', outWidth: 1600 },
  { name: 'senpai-insight-demo', zone: 'overview', selector: '#dashboard-senpai', outWidth: 900 },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function switchZone(page, zone) {
  const btn = page.locator(`[data-zone="${zone}"]`);
  if (await btn.count()) {
    await btn.first().click();
    await page.waitForSelector(`[data-zone-pane="${zone}"]`, { state: 'visible', timeout: 15000 }).catch(() => {});
    await sleep(2800); // let charts + any fetches settle
  }
}

async function switchAnalyticsPane(page, pane) {
  const btn = page.locator(`.analytics-zone-tab[data-analytics-pane="${pane}"], #analytics-tab-${pane}`);
  if (await btn.count()) {
    await btn.first().click();
    await page
      .waitForSelector(`.analytics-sub-pane[data-analytics-pane="${pane}"]`, { state: 'visible', timeout: 15000 })
      .catch(() => {});
    await sleep(3000); // let the pane's charts fetch + render
  }
}

async function toWebp(pngBuffer, name, outWidth) {
  await mkdir(OUT_DIR, { recursive: true });
  const out = join(OUT_DIR, `${name}.webp`);
  await sharp(pngBuffer)
    .resize({ width: outWidth, withoutEnlargement: true })
    .webp({ quality: 82, effort: 6 })
    .toFile(out);
  return out;
}

async function main() {
  await rm(RAW_DIR, { recursive: true, force: true });
  await mkdir(RAW_DIR, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: VIEWPORT,
    deviceScaleFactor: SCALE,
    colorScheme: 'dark',
  });

  console.log(`Loading ${BASE_URL} ...`);
  await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 45000 });
  // Dismiss any first-run modal / tooltip and the onboarding banners so the
  // hero shows the dashboard itself, not setup chrome.
  await page.keyboard.press('Escape').catch(() => {});
  for (const sel of ['#local-intel-guide-dismiss', '#senpai-welcome-dismiss']) {
    const el = page.locator(sel);
    if (await el.count()) await el.first().click({ timeout: 3000 }).catch(() => {});
  }
  // Wait until the portfolio total has populated with a real (non-placeholder) value.
  await page
    .waitForFunction(() => {
      const el = document.querySelector('#total-value, [data-role="total-value"], .hero-pnl-value');
      return el && /\d/.test(el.textContent || '');
    }, { timeout: 30000 })
    .catch(() => console.log('  (total-value wait timed out; capturing anyway)'));
  await sleep(2500);

  const results = [];
  for (const shot of SHOTS) {
    try {
      await switchZone(page, shot.zone);
      if (shot.analyticsPane) await switchAnalyticsPane(page, shot.analyticsPane);

      let png;
      if (shot.mode === 'viewport') {
        png = await page.screenshot({ type: 'png' }); // viewport clip
      } else {
        const el = page.locator(shot.selector).first();
        await el.scrollIntoViewIfNeeded().catch(() => {});
        await sleep(600);
        png = await el.screenshot({ type: 'png' });
      }
      const out = await toWebp(png, shot.name, shot.outWidth);
      console.log(`  ✓ ${shot.name} → ${out}`);
      results.push(shot.name);
    } catch (err) {
      console.log(`  ✗ ${shot.name} failed: ${err.message}`);
    }
  }

  await browser.close();
  console.log(`\nCaptured ${results.length}/${SHOTS.length} shots.`);
  if (results.length < SHOTS.length) process.exitCode = 1;
}

main();
