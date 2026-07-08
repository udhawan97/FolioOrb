# FolioSenseAI Website v3 — "Private Cockpit" Full Redesign Plan

**Status:** Planning document. No implementation yet.
**Author:** Fable (design/creative direction pass), for Opus (execution pass).
**Date:** 2026-07-08
**Live site:** https://udhawan97.github.io/FolioSenseAI/ · Source: `docs-site/src/pages/index.astro` (~1,000-line monolith after the v2 motion pass)
**Creative direction:** *Futuristic private portfolio cockpit meets Apple product launch page.*

---

## 1. Design Diagnosis — why v2 still isn't premium

Audited the live page top-to-bottom at 1440×900 (fresh captures, 6,883px tall). The v2 motion pass added good mechanics (guided tour, two product loops, demo choreography) but the page is still **a stack of landing-page blocks, not a story**. Specifics:

| # | Problem | Evidence |
| --- | --- | --- |
| D1 | **Weak hierarchy.** Section titles render at ~1.5–2rem, same visual weight as body pull-quotes. "You get plain-English answers" (a story beat) and "Risk analytics" (a kicker) sit in the same muted gray at the same left margin. Nothing is cinematic; nothing commands a full viewport. | slice-1: story h3 ≈ spotlight kicker ≈ body |
| D2 | **Weak section transitions.** Sections are separated by nothing but vertical padding — some gaps exceed 300px of pure black (between story→spotlights, demo→senpai). The single fixed backdrop never changes, so scrolling feels like one long undifferentiated void, not chapters. | slice-1, slice-3 dead zones |
| D3 | **Weak motion where it matters.** The 1-2-3 story steps — the product's core pitch — are three static text cards with a fade-in. No icons, no artifacts, no sequence. Meanwhile the *videos* carry all the motion. Motion is decorating the page instead of explaining the workflow. | slice-1 top |
| D4 | **The news loop opens on a loading skeleton.** The first ~1.5s of `news.mp4` shows the pane's shimmer/skeleton state, so when autoplay starts the viewer sees a broken-looking empty window inside beautiful chrome. Worst frame of the whole page. | slice-3 |
| D5 | **Developer section = Lego blocks.** A naked code block floats left; four raw text links float right with no container and no baseline alignment; a lone accordion bar sits below at a *different* width (760px vs 1140px). No section container, no rhythm, no hierarchy. The `shasum` snippet in the trust card even wraps mid-token ("SHA256SUM S.txt"). | dev-section capture |
| D6 | **Generic SaaS card grids.** The `mini-grid` (Local-first / Live market context / Claude) and the three `trust-grid` cards are equal-size gray rounded rectangles with a small icon — exactly the pattern the brief bans. They *tell* value ("Live market context: quotes, history…") with zero product proof. | slice-3, dev-section |
| D7 | **Senpai is quarantined.** The product's signature personality appears once, mid-page, in one card — then a hidden footer easter egg. It guides nothing. |
| D8 | **Told, not shown.** Story steps 1–3, all three mini-grid cards, and two of three trust cards have no product pixels at all. The page has world-class real screenshots and uses them in only 4 places. |
| D9 | **Asset quality gaps.** No pixelated assets remain (v2 fixed those), but: the hero screenshot's *top banner* ("Local Intelligence — fast, private, always on" onboarding strip) eats ~20% of the cockpit visual with setup UI that means nothing to a first-time visitor; the senpai footer orb is a static 32px icon; `risk` still is fine but cropped to hide its best artifact (concentration dial). |
| D10 | **Typography is body-only.** Everything is system-stack at 3 sizes. There is no display scale, no tracking play on kickers, no tabular numerals on data chips. Linear/Vercel polish lives in exactly this layer. |

**What v2 got right (keep):** OS-aware CTAs + live release metadata wiring, region-based guided tour mechanic, video loop infrastructure (record → trim sidecar → encode → poster), demo-panel choreography pattern, reduced-motion discipline, zero-dependency architecture, real-screenshot policy.

---

## 2. New Creative Direction

**"Futuristic private portfolio cockpit meets Apple product launch page."**

One sentence to test every decision against: *a calm, dark instrument panel that presents itself one chapter at a time, narrated by a quiet AI companion.*

### Design language

| Layer | Spec |
| --- | --- |
| **Canvas** | Near-black `#050508`, but never flat: a fixed **financial grid** layer (1px hairlines at 72px rhythm, opacity 0.04, masked radially so it fades at edges) + **aurora** layer (2 large radial blobs, cyan `#6fd6f0` / periwinkle `#97acec`, blur 120px, opacity 0.10–0.16). |
| **Chapter tinting** | Each Act sets `--act-hue` on `<body>` via IntersectionObserver; the aurora blobs and section glows shift subtly (cyan → teal → peri → amber-warm for verdicts → back). Transform/opacity/filter only. This is the #1 fix for D2 — the *room changes* as the story advances. |
| **Panels** | Refined glass: `rgba(255,255,255,0.04)` fill, 1px `rgba(255,255,255,0.09)` border, `backdrop-filter: blur(10px)`, radius 20–24px, plus a 1px **gradient border** treatment (mask-composite) reserved for hero cockpit, verdict card, terminal, and download cards only — scarcity keeps it premium. |
| **Type scale** | System stack stays (Apple-native, 0KB). Add a real scale: Display `clamp(2.6rem, 6vw, 4.2rem)` w=740 tracking −0.035em; Section `clamp(2rem, 4vw, 3rem)` w=700; Kicker `0.78rem` uppercase tracking +0.14em in accent; Body 1.05rem `#9a9aa6`; Data chips get `font-variant-numeric: tabular-nums`. |
| **Chips & artifacts** | Glowing ticker chips (VOO/MSFT/SCHD/NVDA) with 6px status dots and soft outer glow; thin data-stream lines (SVG dashed paths animating dashoffset, 8–12s, opacity ≤0.15); market pulse sparkline strokes. |
| **Senpai** | A small luminous orb (existing brand SVG) with a breathing glow — *companion, not mascot*. Speaks in short set-width bubbles, one line at a time. |
| **Screenshots** | Real app only, retina, in window chrome. New rule: crop *below* the in-app onboarding banner for the hero cockpit so the visual is pure instrument panel. |

### Explicitly avoided
Gamer neon (saturation capped, glow radii ≤ 40px), cartoon Senpai (no eyes/limbs/bounce easing), generic card grids (max 2 equal-width cards side-by-side anywhere except download), slow/heavy motion (nothing above 700ms except the one-time hero sequence and ambient ≤0.15-opacity loops), random motion (every animation must demonstrate a product behavior or direct attention — if it does neither, cut it).

---

## 3. Story Architecture — the page as 8 acts

The page becomes one continuous narrative with a persistent guide. Acts 1+2 fuse into the hero (a download site cannot push CTAs below the fold; instead the hero *performs* the problem→awakening in its load sequence).

| Act | Section (component) | Beat | Viewer takeaway |
| --- | --- | --- | --- |
| **1+2** | `Hero` | Scattered signal chips (prices, headlines, tickers, betas) drift in the dark → converge into the cockpit screenshot as it powers on; headline lands. | "This app turns my scattered portfolio noise into one clear read." |
| **3** | `Workflow` (sticky scroll sequence) | 1 · Add holdings → 2 · It reads everything → 3 · Plain-English answer. Each step animates in a shared stage. | "It's genuinely three steps." |
| **4** | `Features` (5 product moments) | Risk analytics · Verdicts · News themes · Market context+Local-first (fused) · Claude optional. Real UI per moment. | "Every claim has product pixels behind it." |
| **5** | `DemoPanel` | The worked example: VOO + MSFT + SCHD + NVDA watchlist, choreographed table + read-outs. "Demo data. Real workflow." | "I can picture my own portfolio here." |
| **6** | `SenpaiRail` (persistent, not a section) | Orb travels a progress rail, commenting per act. The old standalone Senpai section dissolves into this + one compact intro moment inside Act 3. | "The app has a voice, and it's dry and competent." |
| **7** | `Trust` | Local-first / open source / SHA256 / traceable builds as one *verification console* moment, not 3 cards. | "I can verify every word of this." |
| **8** | `Download` + `DevConsole` + `Footer` | Platform cards (the conversion moment), then the rebuilt developer console. | "Download, or build it myself — both feel first-class." |

**Connective tissue** (fixes "separate blocks"): chapter tinting (§2), a thin center **story spine** — 1px vertical gradient line that grows between acts (scaleY on scroll-reveal, pure transform) — plus consistent act headers: kicker + display title + one-line dek, always centered, always the same rhythm.

---

## 4. Hero Redesign Plan (Acts 1+2)

**Layout.** Full-viewport (`min-height: 92vh`) single-column, centered — replacing v2's 50/50 split. Copy block floats above a large cockpit visual that fills the lower ~55% and bleeds slightly off the bottom fold (invitation to scroll). Topbar unchanged (brand / Docs / Releases / GitHub).

**Copy.**
- Kicker: `LOCAL-FIRST PORTFOLIO INTELLIGENCE`
- H1 (Display): **"Your portfolio, finally speaks back."**
- Sub: "FolioSenseAI turns holdings, risk, news, and market context into plain-English portfolio reads — local-first, Claude-optional, built for trust."
- CTAs: primary **Download for macOS** (OS-aware promotion, live `v4.3.0 · 41 MB` metadata — keep v2 wiring verbatim), secondary **Download for Windows**, tertiary row Docs · GitHub · Release Notes · Development builds ▾. Release-strip chips (version/date/SHA) stay.
- Trust strip: Local-first · Claude optional · Open source · SHA256 verifiable.

**The awakening sequence** (one-time, on load, 900–1400ms total, CSS keyframes with delays; skipped entirely under reduced-motion → final state):
1. 0–300ms: canvas grid + aurora fade in; 8–10 signal chips (`AAPL +0.7%`, `Fed holds`, `β 0.85`, `VOO`, `semis ↑`, headline fragments) scattered at low opacity across the viewport.
2. 250–900ms: chips fly toward the cockpit position (transform-only, ease-out-quint, staggered 40ms) shrinking and dimming as they're "ingested."
3. 600–1100ms: cockpit screenshot resolves — opacity 0→1, scale 1.03→1, `filter: blur(8px)→0` — with a single glow-ring pulse expanding once behind the chrome.
4. 1100ms+: steady state — 4 floating insight chips dock at the corners (keep v2's, parallax ≤ ±10px), the **region tour** begins (keep v2 mechanic; retune hotspots to the new crop), and a slow market-pulse line draws across the bottom of the chrome (SVG dashoffset, 10s loop, opacity 0.12).
5. Senpai orb fades in at the rail's first station with bubble: *"I read the portfolio so you don't have to stare at a red Tuesday alone."*

**Hero asset:** re-crop `hero-dashboard-demo.webp` to start *below* the in-app onboarding banner (pure cockpit: total value, P&L, sector map, today's impact). Re-capture via existing `capture.sh` with a `page.evaluate` that dismisses/collapses the banner first — see §Asset Plan.

---

## 5. Animated 1-2-3 Workflow Plan (Act 3) — the signature section

**Structure.** Desktop: two columns. Left = **sticky stage** (a glass panel, `position: sticky; top: 20vh`, height ~56vh) where one artifact scene plays per step. Right = three step blocks, each ~70vh apart so scrolling naturally sequences them. Normal document flow — zero scroll hijacking. An IntersectionObserver on each step block sets `data-step="1|2|3"` on the stage; scenes crossfade (opacity/transform only, 450ms). Mobile: stage collapses; each step becomes a self-contained block with its own compact artifact.

**Scenes** (all DOM/SVG/CSS, no video):

| Step | Stage scene | Icon (animated) | Copy | Senpai side-note |
| --- | --- | --- | --- | --- |
| **1 · Add your holdings** | Ticker chips `VOO` `MSFT` `SCHD` `NVDA` fly in and snap into a mini holdings table (4 rows, tabular-nums, staggered 80ms); NVDA lands with a `watch` badge. | Plus-in-circle that draws itself (SVG stroke-dashoffset) | "Tickers, shares, cost basis. No brokerage link, no sign-up." | *"Drop in VOO and AAPL. No brokerage link. No awkward data-hostage situation."* |
| **2 · It reads the whole picture** | A radar/scanner sweep (conic-gradient beam rotating 4s) passes over the table; as it sweeps, analysis chips ping into orbit: `β 0.85` · `HHI 21` · `Tech 17%` · `3 headlines` · `risk-on`, each with a brief glow pulse. | Pulsing volatility wave (SVG path, dashoffset loop) | "Exposure, risk, concentration, news, and market regime — computed on-device." | *"I checked risk, concentration, headlines, and whether your 'diversification' is just tech in a trench coat."* |
| **3 · You get plain-English answers** | A verdict card resolves from blur: `VOO — HOLD · High confidence`, one sentence typing beneath ("Tracking its index closely; nothing here needs action."), a small green confidence bar filling. | Chat/answer bubble whose check-mark strokes itself in | "Verdicts, drivers, and themes in language you can act on." | *"Here's the read: what changed, why it matters, and what to consider next."* |

Senpai side-notes render as small rail bubbles anchored to each step (desktop) / inline note cards (mobile). **Reduced-motion:** stage becomes three static rendered panels stacked inside the step blocks; icons freeze at final frame; no sticky.

---

## 6. Feature Section Plan (Act 4) — product moments, not cards

Five moments (the brief's 7 features, with **Market context fused into Local-first** and **Open-source traceability owned by Act 7** to avoid repetition). Alternating visual side, each: kicker + Section title + one benefit line + product visual + animated highlight ring + animated icon + one data artifact. Copy ≤ 2 lines, always.

| Moment | Title / benefit line | Visual | Highlight + artifact | Senpai |
| --- | --- | --- | --- | --- |
| **A · Risk analytics** | "See the risk behind the return." / "Scatter, correlation, concentration, drawdown — every number explained beneath it." | `risk-analytics-demo.webp`, re-cropped to *lead* with the concentration dial + scatter | Region ring visits scatter → dial; artifact: pulsing β 0.85 dial chip | *"Concentration check: five sectors, one ego."* |
| **B · Holdings verdicts** | "A verdict for every position." / "Hold / Add / Trim / Exit — with the why attached." | `verdicts.mp4` loop (keep) | Ring follows the expanding intelligence panel; artifact: 4 verdict chips (Hold/Add/Trim/Exit) with the active one glowing | — (video carries it) |
| **C · News that touches your book** | "Headlines, mapped to holdings." / "Grouped, deduplicated, and themed — only what you own or watch." | `news-v2.mp4` (re-trimmed, see §Asset Plan) | Artifact: 3 mini news-cards clustering into one theme chip ("dividend income") | *"I read the news so it doesn't read you."* |
| **D · Local-first, with live context** | "Runs on your machine. Watches the whole market." / "Quotes, history, regime, world indices — computed and cached locally." | New capture: markets tab (`analytics-tab-markets`) still, retina | Artifact: glowing laptop icon with DB-lock (animated §7); a world-indices ticker strip drifting | *"Your data stays home. The market comes to you."* |
| **E · Claude, when you choose** | "Local by default. Narrated when you want." / "Add a key for briefings, action plans, and news themes. Everything else never needed it." | Split micro-panel: same verdict text in "Local" vs "Claude" voice, toggled | Artifact: the toggle itself — flips every 6s, narration line crossfades | *"I'm eloquent either way. Claude just adds adjectives."* |

Cohesion: identical act-header rhythm, same window-chrome treatment, same ring/artifact grammar. Distinctness: alternating layout, per-moment accent (A teal, B amber, C cyan, D green-cyan, E peri), unique artifact each. **The v2 `mini-grid` and its three generic cards are deleted** — their content now lives in D and E with product proof.

---

## 7. Animated Icons & Artifacts Plan

One system: inline SVG components (~24×24 viewBox, 1.6px stroke, `currentColor`), each animated by a scoped CSS class. No Lottie, no dependency — every icon ≤ ~15 lines of SVG + ≤ 12 lines CSS. All loop 4–12s, pause off-screen via the shared IO (add `.paused` → `animation-play-state: paused`), freeze under reduced-motion.

| Icon | Use | Animation |
| --- | --- | --- |
| Laptop + lock | Local-first (D), Trust | Lock shackle clicks shut once per 8s; soft glow breathes |
| Volatility wave | Risk (A), Step 2 | Path dashoffset flows; amplitude pulse every 6s |
| News cluster | News (C) | 3 card outlines drift together, merge into a tagged chip |
| Ticker chips | Step 1, Demo | Chips snap-in with 60ms stagger, dot blinks on land |
| Claude toggle | E | Knob slides, narration line fades in/out |
| Hash → check | Trust, Dev verification card | Hex string scrolls, resolves into a stroked check |
| Device cards | Download | Apple/Windows glyph cards; subtle sheen sweep on hover only |
| Terminal | DevConsole | Caret blinks; prompt line types on first reveal |
| Radar sweep | Step 2 | Conic beam rotation 4s + ping dots |
| Orb (Senpai) | Rail | Breathing scale 1↔1.06 4s + glow opacity |

**Ambient artifacts:** data-stream lines (2–3 SVG paths per act boundary, dashed, animating dashoffset 10–12s, opacity 0.08–0.15) and the story spine (§3). Both `aria-hidden`, both transform/opacity only, both removed under reduced-motion.

---

## 8. Senpai Scroll Guide Plan (Act 6, persistent)

**Desktop (≥1100px):** a right-edge **progress rail** — 2px track, 8 station dots (one per act), vertically centered, ~40px from the edge (never overlaps content at `--maxw` 1140px on ≥1280px screens; hidden 1100–1279px if it would collide — measure at build). The Senpai orb (28px) travels the rail via `top` interpolation? No — **transform: translateY** interpolated from scroll progress (rAF-throttled, passive listener). On act change: orb pulses once, a bubble (max-width 240px, glass, 0.85rem) slides in beside it for 6s, then collapses to the orb. Clicking the orb replays the current act's line; clicking a station dot smooth-scrolls to that act (it's also nav).

**States/lines:**
- Hero: *"I read the portfolio so you don't have to stare at a red Tuesday alone."*
- Workflow: *"Three steps. I do the middle one."*
- Risk: *"Beta 0.85 — you'll lag the rip, dodge the worst of the dip."*
- News: *"Only the headlines that touch your book."*
- Demo: *"Fake holdings. Real workflow. My commentary: complimentary."*
- Trust: *"Local-first. Your database never texts anyone."*
- Download: *"Pick your platform. I'll behave. Mostly."*
- Dev: *"Or build me yourself. I'm flattered either way."*

**Accessibility & restraint:** rail is `role="navigation"` with labeled dots; bubbles `aria-hidden` with a single `aria-live="polite"` mirror (reuse v2's `#tour-live` pattern); a small ✕ on the bubble collapses the rail to dots-only, persisted in `localStorage` (`fs-senpai-rail: off`); never renders over CTAs (rail z-index below topbar, right-edge only); fully removed under reduced-motion (bubbles become nothing — the inline mobile cards carry the content instead).

**Mobile:** rail is display:none. Instead, 3 inline `SenpaiNote` cards (compact orb + one line) placed after Hero, after Workflow, before Download. Same component as the workflow side-notes.

---

## 9. Developer Section Redesign Plan (Act 8b) — "Build it yourself" console

Kill the Lego. One premium container: `max-width: 1040px`, radius 24px, glass fill, gradient border, padding `3.5rem` desktop / `1.5rem` mobile, generous `7rem` section spacing.

**Desktop two-column (5/7):**
- **Left — the pitch.** Kicker `OPEN SOURCE`; title "Build it yourself."; one line: "A compact FastAPI + SQLite app with no frontend build step. Clone it, run it, pull it apart." Then **link pills** (2×2 grid): Build from source · Release & versioning · Latest-main build · GitHub repo — each a bordered pill with a 16px icon, hover: border-accent + translateY(−1px), 150ms. Below: **verification mini-card** — `shasum -a 256 -c SHA256SUMS.txt` one-liner (`white-space: nowrap; overflow-x: auto` — fixes the mid-token wrap from D5) + the hash→check animated icon + "Every release ships checksums."
- **Right — the terminal.** A real terminal card: traffic-light bar + 3 **tabs** (`Clone` / `macOS · Linux` / `Windows`), tab switch swaps the command set (no layout shift — fixed min-height). Content lines **type in on first reveal** (IO-triggered, `steps()` caret, ~18ms/char, staggered per line; reduced-motion or JS-off → fully rendered static). Prompt glyph `❯` in accent, output lines dimmed, one `# comment` line max per tab. Copy button per tab (reuse v2 copy pattern). Tab content:
  - Clone: `git clone https://github.com/udhawan97/FolioSenseAI.git` / `cd FolioSenseAI` / `./scripts/setup.sh`
  - macOS·Linux: the `install-mac.sh` one-liner + `FOLIO_REF=latest-main` variant as comment
  - Windows: the `irm … | iex` one-liner
- The old standalone "One-line install (advanced)" accordion **is deleted** (absorbed into tabs).

Mobile: single column, pitch → terminal → pills. Terminal fonts `0.82rem`, horizontal scroll allowed inside the card only.

---

## 10. Motion System Plan

**Tokens** (extend v2's set in `:root`):

| Token | Value | Use |
| --- | --- | --- |
| `--ease-out` | `cubic-bezier(0.22, 1, 0.36, 1)` | All entrances |
| `--ease-std` | `cubic-bezier(0.4, 0, 0.2, 1)` | Tours, tab swaps, rail |
| `--dur-micro` | 150ms | Hovers, copy ticks (120–180 band) |
| `--dur-reveal` | 560ms | Section reveals (450–700 band) |
| `--dur-hero` | 1200ms total | One-time awakening (900–1400 band) |
| `--dur-loop` | 4–12s | Icons, ambient artifacts |
| `--dur-senpai` | 320ms | Bubble in/out (250–400 band) |
| `--stagger` | 70ms | Grouped reveals |

**Entrance grammar (new):** `opacity 0→1`, `translateY(14px)→0`, **`filter: blur(6px)→0`** — the "blur resolve" — applied via the existing `.reveal`/`.reveal-group` classes (upgrade in place). Hover grammar: lift −2px + gradient-border opacity + glow ≤ `0 12px 40px rgba(accent, 0.12)`, 150ms. Focus ring tour: keep v2 region mechanic; one instance per visible viewport max (hero ring pauses while a feature ring is on screen — shared controller).

**Rules:** transform/opacity/filter only (no width/height/top/left animation anywhere); `will-change` applied by JS only during active animation, removed after; every loop pauses off-screen (one shared IO — merge v2's video observer, workflow stage, icon pauser, and act-tint setter into a single `motion.js` controller); no scroll hijack, no scroll-linked *position* effects except the sticky stage and rail translate (both rAF-throttled); zero CLS (all media has width/height/aspect-ratio, stage has fixed height); no bounce easing anywhere (`--ease-pop` from v2 is **removed**).

**Reduced-motion contract** (single checklist Opus must satisfy): reveals → opacity-only instant; hero sequence → final state; workflow → static stacked panels; icons/artifacts/aurora-shift → frozen/removed; videos → poster + controls (keep v2 behavior); rail → hidden, inline cards shown; terminal → pre-rendered text.

---

## 11. Performance Plan

Budgets (enforced in QA pass 2):

| Budget | Limit |
| --- | --- |
| Landing JS (all inline modules) | ≤ 14KB minified total (v2 ≈ 8KB; +6KB for rail/workflow/terminal) |
| New raster/video media | Hero re-crop ≈ 90KB webp; markets still ≤ 160KB; `news-v2.mp4` ≤ 1.2MB (re-trim of existing raw or fresh record); **no other new video** — steps/icons/artifacts are DOM/SVG/CSS (0KB media) |
| Page weight before scroll | ≤ 450KB (hero webp + HTML/CSS/JS + fonts=0) |
| Videos | `preload="none"` + poster (keep), served only on scroll |
| Lighthouse | ≥ 95 × 4 on the built page, desktop + mobile presets |

Techniques: keep `fetchpriority="high"` hero; `loading="lazy"` + `decoding="async"` all below-fold imagery; `content-visibility: auto` + `contain-intrinsic-size` on Acts 4–8 sections (big win for a 7k-px page); aurora/grid are pure CSS gradients (no images); blur-resolve entrances limited to ≤ 8 elements per viewport (filter is compositor-expensive on low-end); system font stack stays (0KB, Apple-native); **cache-bust public/ assets by filename** (`news-v2.mp4`, `hero-cockpit-v3.webp`) since `public/` bypasses Astro hashing and Pages CDN caches hard; sticky stage uses `transform` crossfades only.

---

## 12. Copywriting Plan

Tone: professional, minimal, futuristic, slightly witty, finance-aware. Rules: H1s ≤ 6 words; deks ≤ 1 sentence; body ≤ 2 lines; every witty line belongs to Senpai (the page itself stays straight); numbers get tabular-nums; "not financial advice" stays in the footer as personality.

Locked copy (from brief + v2 keepers):
- Hero H1: **"Your portfolio, finally speaks back."** (alt if it reads awkward in situ: "Portfolio intelligence that runs on your machine.")
- Hero sub: "FolioSenseAI turns holdings, risk, news, and market context into plain-English portfolio reads — local-first, Claude-optional, built for trust."
- Workflow act title: "Know what changed. Understand why. Decide what to do next."
- Demo badge: **"Demo data. Real workflow."**
- Trust act title: "Open source. Traceable builds. Your data stays on your machine."
- Claude moment: "Local-first by default. Claude-enhanced when you choose."
- Download dek: "Runs on your machine. No Python, no terminal, no account."
- Footer: "Not financial advice. Very much a dashboard." + quips (keep v2 easter egg)
- All Senpai lines: §5 + §8 tables.

---

## 13. Implementation Handoff (for Opus)

### Component plan (new structure — kill the monolith)

```
docs-site/src/
├── pages/index.astro                 # thin shell: imports sections in act order
├── components/landing/
│   ├── Topbar.astro
│   ├── Hero.astro                    # Act 1+2 (awakening sequence, tour, chips)
│   ├── Workflow.astro                # Act 3 (sticky stage + 3 steps)
│   ├── FeatureMoment.astro           # generic act-4 moment (props: side, accent, visual, artifact slot)
│   ├── Features.astro                # composes 5 moments A–E
│   ├── DemoPanel.astro               # Act 5 (port v2 demo-card + choreography)
│   ├── SenpaiRail.astro              # Act 6 (desktop rail) 
│   ├── SenpaiNote.astro              # inline note card (mobile + workflow side-notes)
│   ├── Trust.astro                   # Act 7 (verification console moment)
│   ├── Download.astro                # Act 8a (platform cards, port v2 wiring)
│   ├── DevConsole.astro              # Act 8b (§9)
│   ├── AnimatedIcon.astro            # icon system (name prop → SVG + anim class)
│   └── Footer.astro
├── styles/landing.css                # tokens, type scale, canvas layers, shared grammar
└── scripts/landing/
    ├── motion.js                     # single IO controller: reveals, act tint, pausing, video play/pause
    ├── tour.js                       # region ring (port v2, multi-instance + arbitration)
    ├── workflow.js                   # step→stage state
    ├── rail.js                       # senpai rail (scroll progress, bubbles, dismiss)
    ├── terminal.js                   # tabs + type-in
    └── release.js                    # GitHub API metadata (port v2 verbatim)
```

### Asset plan

| Asset | Action | Tool |
| --- | --- | --- |
| `hero-cockpit-v3.webp` | Re-capture hero with onboarding banner dismissed (add `page.evaluate` click on banner ✕ / or `localStorage` pre-seed before goto), crop to cockpit | `capture.sh` + tweak to `capture_shots.mjs` |
| `news-v2.mp4` + poster | Re-encode from a fresh recording whose action marker starts *after* content populates (bump scene's post-click settle to ~5s before marking `actionStart`) | `record_demos.sh` |
| `markets-demo.webp` | New still: analytics → markets tab (`[data-analytics-pane="markets"]`) | `capture_shots.mjs` (add shot entry) |
| `verdicts.mp4` | Keep as-is | — |
| `risk-analytics-demo.webp` | Re-crop/re-capture leading with concentration dial + scatter | `capture_shots.mjs` |
| Icons/artifacts | Inline SVG in `AnimatedIcon.astro` — no files | — |
| Delete | `senpai-insight-demo.webp` refs (already gone), v2 mini-grid icons | — |

All captures use the seeded demo DB (VOO 18sh / MSFT 22sh / SCHD 60sh / NVDA watchlist) — no real data, "Demo data. Real workflow." label on Demo + any composite.

### Build order (with the two required review loops)

1. **Foundation:** `landing.css` tokens/canvas/type + `motion.js` + component shells; port release.js/Download/Topbar/Footer untouched-in-behavior. Page renders all acts statically.
2. **Hero** (sequence + tour port) → **Workflow** (stage + steps) → **Features** (5 moments) → **DemoPanel port** → **Trust** → **DevConsole** → **SenpaiRail last** (needs all acts to exist).
3. Assets re-captured in parallel with 1 (they gate Hero/Features only).
4. **Review loop 1 (mechanical):** `npm ci && npm run build`; Playwright sweep — 0 console errors, videos play/pause off-screen, sticky stage correct at 1440/1280/768/390, rail collision check at 1100–1279px, reduced-motion sweep, JS-disabled render (all content visible, static), CLS = 0 via Lighthouse trace, link check (every CTA/doc/release URL 200s, base-path correct).
5. **Review loop 2 (craft):** top-to-bottom read at 1440 and 390 — spacing rhythm consistent (act padding equal), no orphan words in titles, tour rings land on the right regions of the *new* crops, Senpai lines fire once per act (no spam on scroll-jitter — hysteresis in rail.js), copy against §12 rules, Lighthouse ≥95×4, total-weight audit against §11 budgets. Fix and re-run loop 1 checks for anything touched.
6. PR with before/after captures per act; merge → verify Pages deploy serves `-v3`/`-v2` assets (curl 200s) → live Lighthouse spot-check.

### QA checklist (condensed, both loops)
Build clean · 0 console errors · CLS 0 · Lighthouse ≥95×4 · reduced-motion full contract (§10) · JS-off readable · mobile no-overflow 390px · rail never overlaps content or CTAs · one focus-ring instance at a time · videos pause off-screen · all loops pause off-screen · no real data in any pixel · every link 200 · public/ assets renamed for cache-bust · `npm ci` green (lockfile untouched — **no new deps**).

### Risks & tradeoffs

| Risk | Mitigation |
| --- | --- |
| Sticky-stage jank on Safari/iOS | Plain `position: sticky` + opacity crossfades only; fallback: stage becomes per-step inline panels below 768px anyway |
| `filter: blur` entrances on low-end GPUs | Cap concurrent blur-resolves at 8; drop blur (keep fade/translate) below 768px via media query |
| Senpai rail annoying users | 6s auto-collapse, ✕ persistence, dots-only mode, full hide < 1100px |
| Hero awakening delays LCP | LCP element is the cockpit `<img>` itself — it's in initial HTML with `fetchpriority=high`; the animation only *reveals* it (opacity/filter), so LCP paints at image-load, not sequence-end. Verify in loop 1 trace |
| Scope (5 feature moments + rail + workflow) | Acts are independent components; if wall-clock demands, moment E (Claude toggle) is the designated cut — its content survives in copy |
| Pages CDN serving stale assets | New filenames for every changed `public/` asset (`-v3`, `-v2`) |
| 1000-line monolith migration regressions | Foundation step ports v2's *working* JS (release, copy, OS-detect) verbatim before any redesign code lands; loop 1 diff-checks every preserved behavior |

---

*End of plan. Implementation belongs to Opus; nothing above has been coded.*
