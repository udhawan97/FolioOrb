/**
 * v3 asset capture: a clean cockpit hero (onboarding banner dismissed) and a
 * markets-tab still. Dev-only; run via the same seed+boot flow as capture.sh.
 * Output: optimized WebP in docs-site/public/assets/shots/.
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function dismissBanner(page) {
  // The "Local Intelligence — fast, private, always on" onboarding strip only
  // makes sense inside the app; hide it so the hero reads as a pure cockpit.
  await page.evaluate(() => {
    document.getElementById('local-intel-guide')?.setAttribute('hidden', '');
    document.querySelector('.local-intel-guide')?.style.setProperty('display', 'none');
  }).catch(() => {});
}

async function toWebp(buf, name, w) {
  await mkdir(OUT_DIR, { recursive: true });
  const out = join(OUT_DIR, `${name}.webp`);
  await sharp(buf).resize({ width: w, withoutEnlargement: true }).webp({ quality: 82, effort: 6 }).toFile(out);
  console.log(`  ✓ ${name}.webp`);
}

async function main() {
  await rm(RAW_DIR, { recursive: true, force: true });
  await mkdir(RAW_DIR, { recursive: true });
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: VIEWPORT, deviceScaleFactor: 2, colorScheme: 'dark' });
  await p.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 45000 });
  await p.keyboard.press('Escape').catch(() => {});
  await p.waitForFunction(() => {
    const el = document.querySelector('#total-value');
    return el && /\d/.test(el.textContent || '');
  }, { timeout: 30000 }).catch(() => {});
  await sleep(2500);
  await dismissBanner(p);
  await sleep(600);

  // Hero cockpit — viewport clip of the (now banner-free) overview.
  await toWebp(await p.screenshot({ type: 'png' }), 'hero-cockpit-v3', 2400);

  // Markets still — analytics → markets pane.
  await p.click('[data-zone="analytics"]').catch(() => {});
  await sleep(1500);
  await p.click('[data-analytics-pane="markets"], #analytics-tab-markets').catch(() => {});
  await sleep(2600);
  const markets = p.locator('[data-analytics-pane="markets"]').first();
  if (await markets.count()) {
    await markets.scrollIntoViewIfNeeded().catch(() => {});
    await sleep(500);
    await toWebp(await markets.screenshot({ type: 'png' }), 'markets-demo', 1600);
  }

  await b.close();
  console.log('v3 assets done');
}
main().catch((e) => { console.error(e); process.exit(1); });
