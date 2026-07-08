# FolioSenseAI — Website Motion & Demo Polish Plan

**Status:** Planning document. Nothing implemented yet.
**Author:** Fable (planning pass). **Executor:** Opus (implementation pass).
**Date:** 2026-07-07
**Target:** `docs-site/src/pages/index.astro` (landing page) + a small demo-recording pipeline.
**Prime directive:** *a product demo disguised as a landing page* — motion that shows the app doing its job, never decoration.

---

## 1. Current site audit (what's on `main` today)

### Working well — keep, don't rebuild

| Thing | State |
| --- | --- |
| Structure | 8 sections in the right order (hero → story → spotlights → demo panel → Senpai → download → trust → dev). Copy is short and on-voice. |
| Assets | All five shots are crisp retina WebP (88–128 KB): `hero-dashboard-demo` 2400×1508, `risk-analytics` 1600×1829, `verdicts` 1600×505, `news-themes` 1600×1122, `senpai-insight` 676×290. **No pixelated assets remain** — the "pixelated SVG" concern from the brief is already resolved; brand SVGs are pure vector. |
| Plumbing | OS-aware CTAs, live release metadata w/ static fallback, copy buttons, one IntersectionObserver reveal system, `prefers-reduced-motion` gate, `pointer:fine` gate on parallax, focus-visible styles. All of this survives untouched. |
| Capture pipeline | `docs-site/scripts/{capture.sh, capture_shots.mjs, seed_demo.py}` committed; `npm run shots`; demo DB = VOO 18sh / MSFT 22sh / SCHD 60sh / NVDA watchlist. |

### Gaps this pass fixes (ranked)

1. **No motion inside the product.** Every screenshot is a still. The page *tells* ("plain-English answers") but never *shows* the dashboard doing anything. This is the single biggest distance from Cursor-grade.
2. **Demo panel is inert.** `.demo-card` (index.astro:242–282) is hand-built DOM — allocation bars, verdict pills, stat rows — sitting there fully rendered. It's the perfect "status card" moment and it doesn't move.
3. **Spotlight tour is naive.** Fixed 46 px ring, 4 point-hotspots, `setInterval` that keeps firing while the hero is scrolled away (index.astro:564), no size-fitting to the highlighted region, no pause-on-hover.
4. **Feature spotlights are static crops** with a crush problem: `focus-top` clamps the 1600×1829 risk shot to 380 px (index.astro:761–762), hiding most of it.
5. **No trust/local-first visual.** Trust section is three text cards — the brief's "local machine → SHA256 → Claude optional" moment doesn't exist.
6. **Senpai is a screenshot** of a text bubble. A live typed line would be smaller, sharper, and actually in character.
7. **Reveals aren't sequenced.** Single `.reveal` class, no stagger orchestration — grids pop as one blob instead of cascading.
8. **Chip parallax is slightly heavy** (`data-depth` up to 26 px). Premium cap is ~10–12 px.
9. Housekeeping: `playwright` used by the shots pipeline but **not pinned in `docs-site/package.json`** (installed ad-hoc, 1.61.1); **ffmpeg not installed** on this machine; `og:image` is WebP (some crawlers want PNG/JPG fallback — minor, optional fix).

### Deliberately staying static (clarity + perf)

Story steps, mini icon grid, download cards (hover polish only), dev section, footer, all docs pages. The risk-analytics spotlight also stays a still (it's the dense "read me" shot; motion would fight comprehension) — its fix is the crop, not animation.

---

## 2. Motion system (site-wide tokens)

Define once as CSS custom properties + two utility classes; every animation on the page uses these. No libraries.

```css
:root {
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);     /* entrances — fast start, soft settle */
  --ease-std: cubic-bezier(0.4, 0, 0.2, 1);        /* UI state changes, spotlight travel */
  --ease-pop: cubic-bezier(0.34, 1.56, 0.64, 1);   /* verdict stamps & chips ONLY (small overshoot) */
  --dur-micro: 150ms;   /* copy-button flip, dot pulses */
  --dur-ui: 240ms;      /* hovers, toggles */
  --dur-reveal: 560ms;  /* scroll entrances */
  --stagger: 80ms;      /* per-sibling delay step */
}
```

Rules:

- **Transforms + opacity only.** No animating layout, filters, or box-shadow spreads (shadow changes ride on transform-lifted pseudo-elements or are accepted as paint-only hover cost, as today).
- **Distances:** reveals translateY ≤ 16 px; hover lifts ≤ 3 px; parallax chips clamp `data-depth` to **±12 px**; entrance scale range 0.97→1 (hero stage 1.015→1 settle).
- **Stagger:** `.reveal-group` parent + `--i` index var → `transition-delay: calc(var(--i) * var(--stagger))`. Apply to story steps, mini grid, trust grid, demo rows, chips.
- **Loops:** every looping thing (spotlight tour, demo videos, trust vignette, bar shimmer) is governed by one "active" IntersectionObserver — off-screen ⇒ paused (`video.pause()`, `clearInterval`/flag, `animation-play-state: paused` via a `.is-idle` class). Nothing animates unwatched.
- **Hover = read intent:** spotlight tour and demo-panel choreography pause while the pointer is over them.
- **Reduced motion:** loops never start (videos show posters and get native `controls` so the content stays reachable), tour parks on hotspot 1 with its label visible, reveals become opacity-only, parallax off, typewriter renders instantly. Existing `reduce` gate (index.astro:515) is the single source of truth.
- **Mobile:** chips already hidden <720 px; tour runs but slower (dwell 4 s) and ring scales down; videos keep `playsinline muted`; no pointer-driven effects (`pointer:fine` gate stays).
- **Budget:** interaction JS stays vanilla and inline, **+≤6 KB** over current; zero CLS (explicit dimensions on all media); Lighthouse ≥95 ×4 maintained.

---

## 3. Demo asset plan — five moments, only two video files

The premium trick (and the perf trick): use **DOM choreography on real UI** where possible, **short MP4/WebM loops** only where the app must visibly *behave*, and **zero GIFs** (per the constraint: video/poster/reduced-motion-fallback beats GIF everywhere; a GIF would be 5–10× the bytes).

### A. Hero — "the dashboard, touring itself" *(DOM, 0 new bytes)*

Upgrade the existing spotlight into a real guided tour over the existing hero screenshot:

- On load: window-chrome settles (scale 1.015→1, `--dur-reveal`, `--ease-out`) after the existing `.reveal`; chips keep their staggered pop.
- Tour: ring becomes a **region-fitting rounded rect** (not a fixed circle) that morphs between hotspots (left/top/width/height in %, `--ease-std`, 700 ms travel, ~3.2 s dwell), tooltip re-anchors, one hotspot at a time.
- Hotspot regions on the 2400×1508 shot (starting values, fine-tune in browser):
  1. `{x:3.5, y:40, w:23, h:19}` — "Live value & today's P&L"
  2. `{x:51, y:40, w:21, h:15}` — "What moved, in dollars"
  3. `{x:2.5, y:62, w:39, h:33}` — "Look-through sector exposure"
  4. `{x:43, y:62, w:55, h:33}` — "Today's impact, plain English"
  5. `{x:75, y:82, w:21, h:14}` — "Senpai reads the room"
- Pauses when hero off-screen or hovered; reduced-motion parks on #1.

### B. Demo portfolio panel — "the status card" *(DOM, 0 new bytes)*

When `.demo-card` enters the viewport: rows cascade in (stagger), allocation bars grow `width: 0 → var(--w)` (`--ease-out`, 700 ms), verdict pills stamp with `--ease-pop`, side stats fade up last, badge glints once. Re-arms if it leaves and re-enters. Pointer-over pauses/holds final state. This is moment #2 and costs nothing.

### C. News & market context — **real video loop** *(MP4/WebM + poster)*

Recorded from the live app (demo DB): News zone opens → grouped cards populate → gentle scroll → theme chips visible. ~8 s, ends calm, loops.
Replaces the static `news-themes-demo.webp` inside its existing window-chrome. Poster = final calm frame.

### D. Verdicts — **real video loop** *(MP4/WebM + poster)*

Holdings zone: table loads → first row click-expands the intelligence panel (the app's signature interaction) → verdict + sparkline visible → collapse. ~9 s, loops.
Replaces `verdicts-demo.webp` in its spotlight.

### E. Local-first trust vignette — *(inline SVG + CSS, ~2–3 KB)*

New visual column in the trust section: a monoline laptop + orbit mark; a slow 12 s cycle: pulse "SQLite · on device" → shield chip stamps "SHA256 ✓ verified" → a small toggle flicks "Claude · optional" on/off. Matches the existing `icons` stroke style (1.6 px, `--cyan`). Calm, credible, no cartoon. Pauses off-screen.

### F. Senpai micro-demo — *(DOM typewriter, removes 16 KB)*

Replace the `senpai-insight-demo.webp` still with a live assistant card: breathing orb (existing SVG, slow scale 1↔1.03) + a quip that types out on reveal (~28 chars/s) and rotates on click (share the footer-egg quip list). Reduced-motion: full line rendered instantly.

**Demo-data guarantee:** everything recorded runs `seed_demo.py` (VOO/MSFT/SCHD/NVDA, fictional sizes) against a throwaway temp DB with `ANTHROPIC_API_KEY=""` — the recorded UI shows the LOCAL badge and zero personal data. Demo panel keeps its "Demo data only" chip; add a matching mini-chip to the two video captions.

### Recording & encoding pipeline (extends the committed shots pipeline)

- **Prereq (dev machine only):** `brew install ffmpeg`. Pin `playwright` + version in `docs-site/package.json` devDependencies (fixes the unpinned-tooling gap).
- **`docs-site/scripts/record_demos.mjs`** (new): Playwright chromium, viewport **1600×1000 @ DPR 1**, `recordVideo: {size: 1600×1000}` (Playwright records at CSS-pixel size; displayed ≤760 px wide ⇒ ≥2× density). Per demo: navigate, wait for `#total-value` to populate, click `[data-zone="news"]` / `[data-zone="holdings"]`, scripted waits + row-expand click, close context → `.webm` out.
- **`docs-site/scripts/encode_demos.sh`** (new): trim the first ~0.7 s (Playwright's white-flash start) and any dead tail; encode
  `ffmpeg -i in.webm -ss 0.7 -c:v libx264 -crf 23 -preset slow -pix_fmt yuv420p -movflags +faststart -an out.mp4`
  plus optional `libvpx-vp9 -crf 34 -b:v 0` WebM (ship only if smaller); poster = last frame → sharp → WebP q82.
- **Output:** `docs-site/public/assets/demos/{news,verdicts}.mp4` (+`.webm` if smaller) + `{name}-poster.webp`. npm script: `"demos": "./scripts/record_demos.sh"` (seed → boot app on :8177 → record → encode → cleanup, mirroring `capture.sh`).

### Embed pattern (both videos)

```html
<video class="demo-loop" muted loop playsinline preload="none"
       width="1600" height="1000" poster={demo('news-poster.webp')}
       aria-label="FolioSenseAI news view populating grouped headlines for the demo portfolio">
  <source src={demo('news.webm')} type="video/webm" />
  <source src={demo('news.mp4')} type="video/mp4" />
</video>
<noscript><img src={demo('news-poster.webp')} alt="…" width="1600" height="1000" /></noscript>
```

JS: the shared "active" IO calls `play()` on enter (catch + ignore autoplay rejection), `pause()` on exit; reduced-motion never plays and adds `controls`. `preload="none"` + poster ⇒ zero video bytes until scrolled near. No `autoplay` attribute (JS-driven), so JS-off shows the poster — same picture the section has today.

---

## 4. Placement map (6 moments, nothing else moves more than today)

| Section | Motion | New bytes |
| --- | --- | --- |
| Hero | A: settle + chip stagger + region-morphing tour | 0 |
| Story steps | stagger reveal only | 0 |
| Spotlight: risk | **stays still**; fix crop (see §5) | 0 |
| Spotlight: verdicts | D: video loop | ~1.2 MB lazy |
| Spotlight: news | C: video loop | ~1.2 MB lazy |
| Mini grid | stagger reveal only | 0 |
| Demo panel | B: bars/pills/stats choreography | 0 |
| Senpai | F: breathing orb + typewriter | −16 KB |
| Download | hover polish only (existing) | 0 |
| Trust | E: SVG vignette + stagger | +~3 KB |
| Dev / footer | unchanged (footer egg stays) | 0 |

---

## 5. Technical implementation notes for Opus

1. **One file, mostly:** all page changes land in `docs-site/src/pages/index.astro` (markup + inline script + scoped style). Keep the existing script sections' order; add a single `activeIO` observer and reuse the `reduce` flag.
2. **Tour refactor:** replace `.spotlight` fixed-circle with `.spot-region` (absolute, `border-radius: 10px`, border + outer-glow, `left/top/width/height` transitions). Data: array of `{x,y,w,h,label}`. Keep `aria-hidden` — the labels' information already exists in surrounding copy; additionally mirror the active label into a visually-hidden `aria-live="polite"` element for SR parity.
3. **Fix the risk-crop:** `focus-top` becomes an explicit `aspect-ratio: 16/10` viewport on `.spot-shot` with `object-position: top`; the 1600×1829 risk shot shows its top half cleanly at container width instead of a 380 px squash. Verify no CLS (aspect-ratio reserves space).
4. **Demo panel choreography:** pure CSS classes toggled by IO (`.demo-card.play` → child animations with `--i` delays). Bars animate `transform: scaleX` (not width) with `transform-origin: left` to stay compositor-only; pills use `--ease-pop`; re-arm by removing `.play` on exit.
5. **Trust vignette:** inline `<svg>` in the markup (no asset fetch), CSS keyframes, `.is-idle` pause class from the shared IO.
6. **Typewriter:** ~15 lines of JS, types into a fixed-height line (reserve height ⇒ no CLS), caret via CSS border-right blink, instant-render under `reduce`.
7. **Parallax clamp:** change `data-depth` values to ≤12 (18/-22/26/-16 → 10/-12/12/-10).
8. **`package.json`:** add `"playwright": "^1.61.1"` to devDependencies + `"demos"` script. Do **not** add any runtime dependency.
9. **Optional (5 min, do it):** add a JPEG `og:image` fallback (`sharp` one-liner from the hero shot) since some link unfurlers still skip WebP.
10. **GitHub Pages compatibility:** everything is static files under `public/` — no headers, no service worker, no range-request assumptions (GH Pages serves 206 fine for `<video>`).

## 6. Performance budget (hard limits)

- Each video: **≤1.5 MB hard cap, ~1.2 MB target**; combined lazy media ≤3 MB; posters ≤60 KB each.
- Above-the-fold added bytes: **≤10 KB** (CSS+JS+SVG, all inline). No new requests before scroll.
- `preload="none"` on both videos; posters are the only eager-ish media and they're `loading="lazy"` (below fold).
- CLS = 0 (dimensions/aspect-ratio everywhere, typewriter height reserved). LCP unchanged (hero img untouched; add `fetchpriority="high"` to it while in there).
- All loops pause off-screen. No `setInterval` without the active-IO gate.
- Lighthouse (desktop): Perf/A11y/BP/SEO ≥95. Mobile perf ≥90 acceptable only if the delta is video-poster decode; otherwise fix.

## 7. QA plan (run twice — fix, then re-run)

1. `npm run build` clean; `npm run preview` walkthrough top-to-bottom at 1512 / 1280 / 768 / 390 px.
2. Browsers: Chrome + Safari (WebKit matters for `playsinline`, backdrop-filter, VP9-vs-H264 source pick). Edge = Chromium, note-only.
3. Toggles: `prefers-reduced-motion` emulation (loops→posters+controls, tour parked, instant typewriter); JS disabled (posters render, static release links work); offline API (fallback hrefs intact).
4. Motion review: no jank in DevTools performance overlay (60 fps during tour + demo-panel play), no layout thrash (no purple in the profile during loops), loops verifiably paused when scrolled away (check `document.querySelectorAll('video')[0].paused`).
5. Content: freeze-frame both videos start/mid/end — demo tickers only, LOCAL badge visible, no `.env`/key/personal data in any frame; "Demo data" chips present.
6. Links: hero CTAs resolve to real installer assets (API-driven), docs/GitHub/releases/install-guide/license links 200, base-path correctness on every internal href.
7. Assets: `du -h public/assets/demos/*` within budget; videos play-loop seamlessly (no visible seam frame); posters match final frames.
8. Lighthouse pass; a11y spot-check (focus order, video aria-labels, aria-live tour mirror, contrast of new chips).
9. Second polish pass on timing feel: dwell times, stagger steps, easing — tune by eye, then stop. No third pass.

## 8. File-by-file checklist for Opus

- [ ] `docs-site/package.json` — pin `playwright` devDep; add `demos` script
- [ ] `docs-site/scripts/record_demos.mjs` — new (Playwright recordVideo driver)
- [ ] `docs-site/scripts/record_demos.sh` — new (seed → boot :8177 → record → encode → cleanup)
- [ ] `docs-site/scripts/encode_demos.sh` — new (ffmpeg trim/encode/poster; called by the .sh above)
- [ ] `docs-site/public/assets/demos/` — `news.mp4`, `verdicts.mp4` (+`.webm` if smaller), 2 posters
- [ ] `docs-site/src/pages/index.astro` — motion tokens; stagger groups; hero tour (region morph + active-IO + hover-pause + aria-live); demo-panel choreography; two video embeds replacing stills; risk-crop fix; trust vignette; Senpai typewriter (remove webp usage); parallax clamp; og:image jpg fallback; `fetchpriority` on hero img
- [ ] Delete `docs-site/public/assets/shots/senpai-insight-demo.webp` usage (keep file harmless or remove)
- [ ] PR with before/after Lighthouse numbers and asset-size table; docs deploy verifies on merge

**Out of scope:** docs pages, Starlight theme (`custom.css`), README (unchanged), any runtime JS dependency, scroll-scrubbed/sticky sequences (rejected: scroll-hijack risk for near-zero benefit on a one-screen hero).

## 9. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Playwright webm shows banding on the dark UI after H264 re-encode | crf 23 + `yuv420p`; if banding visible, crf 21 or add light `noise=alls=6` dither; budget allows |
| Autoplay blocked in some browser states | JS `play().catch()` — poster remains, page still makes sense |
| Record-time flakiness (news needs live Yahoo data) | same mitigation as shots pipeline: run on good network, script waits on real selectors, re-run is cheap (`npm run demos`) |
| Loop seam visible | end scenes on a still state ≥1 s; trim to a calm final frame that visually matches the opening frame |
| Repo grows ~2.5 MB | acceptable one-time cost; assets are versioned product media |
| First live run reveals timing tune needed | QA pass 2 exists precisely for dwell/stagger tuning |

## 10. Copy-ready execution prompt for Opus

> Execute **`docs/plans/website-motion-plan.md`** in `udhawan97/FolioSenseAI`, working on a feature branch off latest `main`. Read the whole plan first; decisions are settled — do not re-litigate (DOM choreography for hero/demo-panel/trust/Senpai; exactly two MP4/WebM video loops for news + verdicts with posters and `preload="none"`; no GIFs; no new runtime deps; no scroll-hijacking).
> Order of work: (1) `brew install ffmpeg` if missing; pin playwright devDep; build the record/encode pipeline (§3) and produce the two loops + posters from the seeded demo app — verify every frame is demo-data-only; (2) implement §5's index.astro changes — motion tokens, stagger groups, region-morphing hero tour with active-IO/hover-pause/aria-live, demo-panel choreography, video embeds, risk-crop fix, trust vignette, Senpai typewriter, parallax clamp, og fallback; (3) run the §7 QA loop twice, tuning timing between passes; (4) PR with Lighthouse before/after and an asset-size table, merge on green, verify the deployed page.
> Hard constraints: every loop pauses off-screen; reduced-motion shows posters + parked tour + instant text; JS-off degrades to today's static page; per-video ≤1.5 MB; above-fold added bytes ≤10 KB; CLS 0; Lighthouse ≥95 desktop; all existing links and release-metadata behavior preserved.

---

*End of plan.*
