/**
 * Capture retina product screenshots of the FolioOrb dashboard for the
 * landing page. Dev-only — Playwright and this script never ship to the site.
 *
 * Prereqs: the app must already be running with the seeded demo database
 * (see capture.sh, which orchestrates seed → boot → capture → optimize).
 *
 * Output: optimized WebP files in docs-site/public/assets/shots/, captured at
 * deviceScaleFactor 2 so they stay crisp on retina displays.
 */
import { chromium } from 'playwright';
import sharp from 'sharp';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const BASE_URL = process.env.SHOT_BASE_URL || 'http://127.0.0.1:8177';
const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = join(__dirname, '..', 'public', 'assets', 'shots');
const README_DASHBOARD_OUT = join(__dirname, '..', '..', 'docs', 'dashboard.webp');
const README_PLAN_OUT = join(__dirname, '..', '..', 'docs', 'plan-protect.webp');
const README_REVIEW_OUT = join(__dirname, '..', '..', 'docs', 'review-inbox.webp');

const VIEWPORT = { width: 1512, height: 950 };
const SCALE = 2;

// Each shot: name, how to reach it, what to capture, and the final WebP width.
// `zone` clicks the top dashboard tab; `analyticsPane` clicks an analytics sub-tab.
const SHOTS = [
  { name: 'readme-dashboard', zone: 'overview', mode: 'viewport', outWidth: 1600 },
  { name: 'risk-analytics-demo', zone: 'analytics', analyticsPane: 'risk', selector: '.analytics-sub-pane[data-analytics-pane="risk"]', outWidth: 1600 },
  { name: 'review-inbox-demo', reviewTab: 'inbox', selector: '.review-orbit-shell', outWidth: 1600 },
  { name: 'plan-protect-demo', reviewTab: 'plan', reviewScrollTop: 420, selector: '.review-orbit-shell', outWidth: 1600 },
  { name: 'senpai-mobile-flow', zone: 'overview', mode: 'mobile-flow', outWidth: 750 },
];
const requestedNames = new Set(
  (process.env.SHOT_NAMES || '').split(',').map((name) => name.trim()).filter(Boolean),
);
const selectedShots = requestedNames.size
  ? SHOTS.filter((shot) => requestedNames.has(shot.name))
  : SHOTS;

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
  if (name === 'readme-dashboard') {
    await sharp(pngBuffer)
      .resize({ width: outWidth, withoutEnlargement: true })
      .webp({ quality: 82, effort: 6 })
      .toFile(README_DASHBOARD_OUT);
    return README_DASHBOARD_OUT;
  }
  await mkdir(OUT_DIR, { recursive: true });
  const out = join(OUT_DIR, `${name}.webp`);
  await sharp(pngBuffer)
    .resize({ width: outWidth, withoutEnlargement: true })
    .webp({ quality: 82, effort: 6 })
    .toFile(out);
  if (name === 'plan-protect-demo') {
    await sharp(pngBuffer)
      .resize({ width: 1600, withoutEnlargement: true })
      .webp({ quality: 82, effort: 6 })
      .toFile(README_PLAN_OUT);
  }
  if (name === 'review-inbox-demo') {
    await sharp(pngBuffer)
      .resize({ width: 1600, withoutEnlargement: true })
      .webp({ quality: 82, effort: 6 })
      .toFile(README_REVIEW_OUT);
  }
  return out;
}

async function main() {
  if (requestedNames.size && !selectedShots.length) {
    throw new Error(`SHOT_NAMES did not match a product shot: ${[...requestedNames].join(', ')}`);
  }
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
  for (const shot of selectedShots) {
    try {
      if (shot.mode === 'mobile-flow') {
        if (await page.locator('#review-orbit').getAttribute('aria-hidden') === 'false') {
          await page.keyboard.press('Escape');
        }
        await page.setViewportSize({ width: 375, height: 812 });
        await switchZone(page, shot.zone);
        const senpai = page.locator('#dashboard-senpai');
        await senpai.evaluate((element) => element.classList.remove('is-hidden', 'is-expanded'));
        await page.locator('#dashboard-senpai-toggle').click({ force: true });
        await sleep(300);
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        await sleep(150);
        const png = await page.screenshot({ type: 'png' });
        const out = await toWebp(png, shot.name, shot.outWidth);
        console.log(`  ✓ ${shot.name} → ${out}`);
        results.push(shot.name);
        continue;
      }
      // Senpai can be hidden from the real overflow control. Keep product
      // captures unobscured; the mobile-flow artifact exercises it separately.
      await page.evaluate(() => {
        const senpai = document.getElementById('dashboard-senpai');
        if (!senpai) return;
        senpai.classList.add('is-hidden');
        senpai.classList.remove('is-expanded');
      });
      if (shot.zone) await switchZone(page, shot.zone);
      if (shot.analyticsPane) await switchAnalyticsPane(page, shot.analyticsPane);
      if (shot.reviewTab) {
        if (await page.locator('#review-orbit').getAttribute('aria-hidden') !== 'false') {
          await page.locator('#review-orbit-trigger').click();
        }
        await page.locator(`[data-review-tab="${shot.reviewTab}"]`).click();
        await page.waitForSelector(`[data-review-pane="${shot.reviewTab}"]`, {
          state: 'visible', timeout: 15000,
        });
        await sleep(3000);
        if (shot.reviewScrollTop) {
          await page.locator('.review-orbit-body').evaluate(
            (element, top) => { element.scrollTop = top; },
            shot.reviewScrollTop,
          );
          await sleep(250);
        }
      }

      let png;
      const captureCss = [
        '#dashboard-senpai { display: none !important; }',
        shot.name === 'risk-analytics-demo'
          ? 'body > .navbar { position: static !important; }'
          : '',
      ].filter(Boolean).join('\n');
      const captureOverride = await page.addStyleTag({ content: captureCss });
      try {
        if (shot.mode === 'viewport') {
          png = await page.screenshot({ type: 'png' }); // viewport clip
        } else {
          const el = page.locator(shot.selector).first();
          await el.scrollIntoViewIfNeeded().catch(() => {});
          await sleep(600);
          png = await el.screenshot({ type: 'png' });
        }
      } finally {
        await captureOverride?.evaluate((element) => element.remove()).catch(() => {});
      }
      const out = await toWebp(png, shot.name, shot.outWidth);
      console.log(`  ✓ ${shot.name} → ${out}`);
      results.push(shot.name);
    } catch (err) {
      console.log(`  ✗ ${shot.name} failed: ${err.message}`);
    }
  }

  await browser.close();
  console.log(`\nCaptured ${results.length}/${selectedShots.length} shots.`);
  if (results.length < selectedShots.length) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
