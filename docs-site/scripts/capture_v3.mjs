/**
 * v3 asset capture: a clean cockpit hero with onboarding dismissed. Dev-only;
 * invoked by the canonical seed+boot workflow in capture.sh.
 * Output: optimized WebP in docs-site/public/assets/shots/.
 */
import { chromium } from 'playwright';
import sharp from 'sharp';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const BASE_URL = process.env.SHOT_BASE_URL || 'http://127.0.0.1:8177';
const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = join(__dirname, '..', 'public', 'assets', 'shots');
const VIEWPORT = { width: 1512, height: 950 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function dismissBanner(page) {
  // The "Local Intelligence — fast, private, always on" onboarding strip only
  // makes sense inside the app; hide it so the hero reads as a pure cockpit.
  await page.evaluate(() => {
    document.getElementById('local-intel-guide')?.setAttribute('hidden', '');
    document.querySelector('.local-intel-guide')?.style.setProperty('display', 'none');
    document.getElementById('dashboard-senpai')?.style.setProperty('display', 'none', 'important');
  }).catch(() => {});
}

async function toWebp(buf, name, w) {
  await mkdir(OUT_DIR, { recursive: true });
  const out = join(OUT_DIR, `${name}.webp`);
  await sharp(buf).resize({ width: w, withoutEnlargement: true }).webp({ quality: 82, effort: 6 }).toFile(out);
  console.log(`  ✓ ${name}.webp`);
}

async function main() {
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

  await b.close();
  console.log('v3 assets done');
}
main().catch((e) => { console.error(e); process.exit(1); });
