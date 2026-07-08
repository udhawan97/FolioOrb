# FolioSenseAI v4.3.2 Release Notes

**Release date:** July 8, 2026

---

## ✦ Scrolling, Finished

> *v4.3.2 is the second half of the v4.3.1 scroll-performance fix. Same goal — no feature changes, no data migration — this time aimed at portfolios with a real number of holdings in them.*

v4.3.1 fixed the background and blur effects that made every scroll frame expensive everywhere in the app. That was a real win, but it left the biggest cost in place for anyone with more than a handful of positions: the Holdings table itself, and a quieter bug in how its sparklines redraw.

**Fixed the sparkline redraw.** Each row's 7-day trend chart lives in a canvas that redraws whenever it scrolls into view. The check for "did this row's data actually change" was being skipped, so every row repainted on every pass through the viewport — even rows that hadn't moved. A holding's canvas now only repaints when its underlying price history actually changes, verified pixel-for-pixel: unchanged data draws nothing, changed data draws correctly.

**Fixed the real cost: tables you can't see still cost you.** Switching away from the Holdings tab hid it with `visibility: hidden`, which keeps a hidden element fully "in play" for the browser's layout engine. With enough holdings, the Holdings table's column-width math is expensive — and it was being recomputed on every scroll frame on *every* tab, Overview and News included, because the hidden Holdings table was still there to think about. It's now skipped entirely while off-screen and restored instantly when you switch back, so the other tabs stop paying rent for a table they're not showing.

**Measured result (30-holding portfolio, the case that showed it worst):** Overview scrolling roughly **4× faster**, Analytics and News both meaningfully smoother, Holdings itself close to **4× faster**. Two CSS approaches that looked promising on paper — a stricter table layout mode, and a narrower containment hint — were tested, measured, and dropped: one visibly shifted column widths on smaller windows, the other simply didn't help. Neither shipped.

No holdings, settings, or `.env` changes are required — installing v4.3.2 over v4.3.1 or earlier keeps everything as-is.

---

# FolioSenseAI v4.3.1 Release Notes

**Release date:** July 8, 2026

---

## ✦ Smooth Scrolling in the Desktop App

> *v4.3.1 is a performance release. The desktop app scrolled sluggishly on macOS; this fixes it — no feature changes, no data migration, just a much smoother dashboard.*

The native app (macOS DMG / Windows EXE) renders inside a system WebView — WKWebView on macOS, WebView2 on Windows — which pays a much steeper per-frame cost for certain effects than a desktop browser does. On slower machines that showed up as laggy, sluggish scrolling. v4.3.1 removes those hot spots:

**Fixed the two universal scroll killers.** The ambient page background used `background-attachment: fixed`, which forces the browser to repaint the entire glow gradient on *every* scroll frame; it now lives on a fixed, compositor-cached layer that's painted once. The drifting background "orbs" carried a heavy `blur(40px)` filter that had to be re-rasterized each frame while they animated; the blur is gone (the glows were already soft radial gradients) and the drift is now a cheap, GPU-composited transform. Both changes benefit the browser and from-source runs too.

**Added a desktop-app rendering profile.** Inside the native WebView, the app now switches to a lighter profile that drops `backdrop-filter` (frosted surfaces fall back to near-opaque fills, so the look holds up) and freezes a few always-on ambient animations. The in-browser and run-from-source experience is deliberately left at full fidelity — nothing was removed from the design.

**Measured result:** roughly a **3× improvement** in scroll frame rate on the overview and analytics views under CPU-throttled testing, with janky frames cut by about two-thirds. No holdings, settings, or `.env` changes are required — installing v4.3.1 over v4.3.0 keeps everything as-is.

---

# FolioSenseAI v4.3 Release Notes

**Release date:** July 7, 2026

---

## ✦ FolioSenseAI Goes Desktop

> *v4.3 is the release where FolioSenseAI stops being a thing you set up and starts being a thing you download. No Python, no terminal, no `pip install` — just a native app.*

Until now, running FolioSenseAI meant having Python on your machine and a comfortable relationship with a terminal. v4.3 removes that entirely. There are now real installers — a **`.dmg`** for macOS (Apple Silicon) and a clean per-user **`.exe`** for Windows — that drop a native app on your machine and open the dashboard in its own window. The FastAPI server still runs locally; it just runs *inside* the app now instead of a terminal tab you have to keep alive.

**One-click installers.** Download the [macOS DMG](https://github.com/udhawan97/FolioSenseAI/releases/latest) or [Windows installer](https://github.com/udhawan97/FolioSenseAI/releases/latest), launch it, and you're in. Your database and `.env` live in the per-user data directory (`~/Library/Application Support/FolioSenseAI` on macOS, `%APPDATA%\FolioSenseAI` on Windows) — never inside the app bundle — so updates and uninstalls leave your portfolio untouched.

**An automated, honest release pipeline.** Every version tag builds both platforms in GitHub Actions, smoke-tests that the frozen app actually boots, and only *then* publishes the installers plus a `SHA256SUMS.txt` to GitHub Releases. A broken build can never replace a good download. Every merge to `main` also refreshes a rolling `latest-main` prerelease for early testers, kept clearly separate from stable.

**A download-first website.** The [landing page](https://udhawan97.github.io/FolioSenseAI/) was rebuilt around real, retina screenshots of the actual dashboard — it detects your OS, links straight to the current installer, and shows the live release version, date, and commit. The docs gained a full Download & Install section with macOS Gatekeeper and Windows SmartScreen walkthroughs.

**Signing, honestly.** These early builds are not yet code-signed, so macOS and Windows will show a first-launch warning. That's expected for an open-source app without a paid certificate, and the install guides show exactly what you'll see and how to verify your download against the published checksums. Code signing and notarization are the planned next step.

v4.3 is the release that turns a project you clone into a product you install.

---

# FolioSenseAI v4.2 Release Notes

**Release date:** July 7, 2026

---

## ✦ Meet Senpai, and Never Get Lost on Day One

> *v4.2 is the release where the orb finally got a name it can keep. Say hello to Senpai — and to the welcome guide that explains what everything means before you have to ask.*

The dashboard's resident orb has a name now, everywhere it lives. What used to be "dashboard pet" / "Portfolio Butler" scattered across the codebase — IDs, CSS classes, JS variables, the `localStorage` key, the visible label — is now **Senpai**, top to bottom. Same orb, same corner of the screen, same personality. Just one name instead of three.

Senpai also got something to actually say. Alongside its usual Claude-flirting commentary, it now rotates in genuine tips and tricks — what Research mode does, what each hold-type icon means, the `M` and `?` shortcuts — surfacing roughly one time in four so they read as a helpful aside, not a lecture.

Brand-new installs get a proper welcome now instead of an empty dashboard. On first launch with zero holdings, a one-time guide walks through adding a holding, what Research mode means, and what each of the four hold-type icons — Auto, Trade, Core, Anchor — actually does, sourced straight from the same tooltips the rest of the app already uses. Dismiss it once and it's gone for good.

The documentation site also got fixed. Five internal links were quietly 404ing on GitHub Pages because they didn't account for the site's base path — worth fixing since v4.2 also adds a **Documentation** link directly in the app's menu, so it needs to actually work.

v4.2 is a naming exercise and a first-impression fix, wrapped around one bug nobody had reported yet but everybody would have hit eventually.

---

## What's New

### Senpai (formerly "dashboard pet")

- Full rename across `templates/index.html`, `static/js/dashboard.js`, and `static/css/style.css` — every id, class, JS variable/function, CSS keyframe, and the `localStorage` key (now `foliosense-dashboard-senpai-visible`) says `senpai`, not `pet`.
- The one visible label, "Portfolio Butler," is now "Senpai."
- Pure naming pass — no behavior changed; `_HOLD_MODE_META` and every other tooltip are untouched.

### Tips & Tricks Quotes

- New `DASHBOARD_SENPAI_TIP_QUOTES` array — genuinely useful one-liners covering Research mode, the four hold-type modes, and the `M`/`?` shortcuts.
- Woven into the existing quote rotation in `showQuote()` at roughly a 1-in-4 chance per cycle (`SENPAI_TIP_QUOTE_CHANCE = 0.25`) without disturbing the underlying rotation index, so the regular commentary still cycles in order.

### First-Run Welcome Guide

- New modal (`#senpai-welcome-guide`), shown once when a fresh install has zero holdings, covering: adding a holding, what Research mode does, and the four hold-type icons — the hold-type list renders directly from `_HOLD_MODE_META` so it can never drift from the tooltips shown elsewhere in the app.
- Dismissal (close button or backdrop click) persists via `foliosense-senpai-welcome-seen` in `localStorage`; "Add your first holding" closes the guide and opens the portfolio manager directly.

### Documentation

- Fixed 5 internal docs-site links (`troubleshooting.md`, `get-started/introduction.md`, `get-started/claude-setup.md`) that rendered without the GitHub Pages base path and 404'd — converted to relative links, which resolve correctly regardless of base path.
- Added a **Documentation** entry to the nav overflow menu, linking to the hosted docs site in a new tab.

---

## Developer Notes

- FastAPI metadata version bumped to **`4.2.0`** (previous releases kept it pinned at `4.0.0`).
- Static cache keys: `style.css?v=101`, `dashboard.js?v=94`, `analytics-charts.js?v=14`.
- **366 tests passing** (up from 361 in v4.1) — 2 existing tests in `test_intelligence_engine_ui.py` were updated to assert on the new `senpai-*` identifiers instead of the old `pet-*` ones.
- No database schema changes — no migration required.
- No `.env` changes required.

---

## Install & Upgrade

**Prerequisite:** Python 3.11+ from [python.org](https://www.python.org/downloads/). Windows: check "Add Python to PATH" during install.

### Mac — one command

Open Terminal (⌘ Space → "Terminal"), paste, and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioSenseAI/release-v4.2/scripts/install-mac.sh | bash
```

Downloads, installs, and places a **FolioSenseAI** shortcut on your Desktop. Browser opens automatically. Next time: double-click the Desktop shortcut.

### Windows — one command

Open PowerShell (Win+R → "powershell"), paste, and press Enter:

```powershell
irm https://raw.githubusercontent.com/udhawan97/FolioSenseAI/release-v4.2/scripts/install-win.ps1 | iex
```

Downloads, installs, and places a **FolioSenseAI** shortcut on your Desktop. Browser opens automatically. Next time: double-click the Desktop shortcut.

### Upgrading from v4.1

Run the same install command above — it detects your existing `database/` and `.env`, preserves them, and starts the updated app. No manual backup or file copying required.

No schema migration or `.env` change required. If you had toggled Senpai's visibility off before this update, it resets to visible once (the `localStorage` key changed names) — toggle it back off from menu → Dashboard → Senpai if you'd rather it stay hidden.

---

## Final Word

v4.2 is still not financial advice. It's just the release where the orb got a name, first launches got a map, and the docs stopped sending people into the void.

---

# FolioSenseAI v4.1 Release Notes

**Release date:** June 28, 2026

---

## ✦ The Dashboard Finally Knows Its Own Key

> *v4.1 is the release where setup stopped requiring a text editor. You can now hand Claude your API key from the dashboard itself — and watch it spend every token in real time.*

FolioSenseAI now has an **in-dashboard API key panel**. Click the brand mark, paste your `sk-ant-*` key, and the dashboard validates it, writes it to `.env`, and reconnects Claude without a restart. No terminal. No `.env` file hunting. Input is validated client-side and server-side against the canonical Anthropic key format before a single character touches disk.

The cost HUD in the nav got honest. Instead of estimating from cache occupancy, the dashboard now tracks **real token counts** across every Claude call made in the session. The nav breakdown shows actual input and output tokens, a live cost figure, and a predicted per-run annotation derived from backend constants — so you always know what a full scan costs before you click refresh again.

The holdings table got faster and more responsive. Rows now expand on the **first click**, latency on the expand path was cut, and an **auto-refresh** keeps prices current without manual intervention. The Overview sector graph was refactored to render weighted bars with proper proportional fills and a clean overflow note.

v4.1 is a tightening: the same cockpit, now easier to configure and harder to misread.

---

## What's New

### In-Dashboard API Key Configuration

- **`POST /api/ai/configure-key`** — accepts an `api_key` body, validates against `^sk-ant-[A-Za-z0-9_\-]{20,300}$`, writes a single `ANTHROPIC_API_KEY=…` line to `.env` (creating the file if absent), and reloads the Anthropic client in-process. No restart required.
- **API Key panel** — accessible from the brand mark in the nav. Password-type input with show/hide toggle, live keystroke validation (strips paste garbage, checks format character-by-character), a save button that activates only when the key is structurally valid, and an inline status message on success or failure. Closes on click-outside and Escape.
- **Heartbeat reconnect** — on a successful key save the panel triggers a fresh `/api/ai/heartbeat` call so the HUD mode chip updates from Local → Claude AI without reloading the page.
- **`reinitialize_client()`** in `ai_service.py` — hot-swaps the module-level Anthropic client with a new key, allowing the server to pick up a key change without process restart.

### Live Token Cost Tracking

- **`_track_usage()`** in `ai_service.py` — called after every `client.messages.create()`, accumulates `total_in` / `total_out` across the process lifetime in a module-level counter.
- **`get_accumulated_usage()`** — exposes the live totals for the cache stats route.
- **`/api/ai/cache/stats`** now returns:
  - `actual_input_tokens` / `actual_output_tokens` / `actual_cost_usd` — real tracked tokens from this session
  - `predicted_per_run.cost_usd` — computed from `_PREDICTED_IN/OUT_PER_RUN` constants using live pricing, so updating the constants or rates reflects immediately on next poll
  - `pricing` block — input/output rates the frontend reads directly; rates are no longer hardcoded in JS
- **Cost HUD** — frontend prefers actual tracked tokens when available, falls back to cache estimate when none have been spent. Appends `~$0.0003 / full scan (~5,600 tok)` to the breakdown line derived from backend constants.

### Holdings Table

- **Auto-refresh** — the holdings table now refreshes live prices on an interval without a manual trigger. A subtle CSS indicator marks the refresh cycle.
- **First-click expand** — rows now inject the summary expansion via `injectSummaryRows` before attempting to open, so the detail pane appears on the very first click. The previous two-click flow is gone.
- **Latency patch** — the expand path was rescheduled to reduce perceived latency; the scanning animation fires immediately while intelligence loads asynchronously behind it.

### Overview Sector Graph

- **Proportional fills** — sector bars now render weighted fills using `--snapshot-fill` CSS custom properties, scaled relative to the top sector rather than absolute percentages, so a single-dominant-sector portfolio does not show every bar at 100%.
- **Overflow note** — when more sectors are held than the strip can display, a `+N more` note appears below the visible bars.
- **Dot + track layout** — each row now has a leading coloured dot, a labelled track, and a fill bar, replacing the previous plain-text list.

### Bug Fixes

- **Font resize regression** — a resize event was causing text scaling to clamp incorrectly when the panel container had not yet fully painted; the measurement is now deferred past the layout tick.
- **Scrolling bug** — a competing `overflow` rule on the holdings container was intercepting scroll events on the inner panel; specificity corrected.
- **Ticker management** — adding a ticker through the manage modal now correctly triggers a fresh quote load for the newly added position without requiring a full page reload.

---

## Developer Notes

- FastAPI metadata version still **`4.0.0`** — no API contract changes, only additions.
- New endpoint: `POST /api/ai/configure-key` — in `app/routers/ai.py`
- New helper: `_update_env_file(key, value)` — writes a single `KEY=VALUE` line to `.env` atomically; creates the file if absent
- New functions in `ai_service.py`: `_track_usage()`, `get_accumulated_usage()`, `reinitialize_client()`
- Static cache keys: `style.css?v=99`, `dashboard.js?v=91`, `analytics-charts.js?v=14`
- **361 tests passing** (up from 356 in v4.0)
- No database schema changes — no migration required.
- No `.env` changes required; the key panel writes `.env` for you.

---

## Install & Upgrade

**Prerequisite:** Python 3.11+ from [python.org](https://www.python.org/downloads/). Windows: check "Add Python to PATH" during install.

### Mac — one command

Open Terminal (⌘ Space → "Terminal"), paste, and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioSenseAI/release-v4.1/scripts/install-mac.sh | bash
```

Downloads, installs, and places a **FolioSenseAI** shortcut on your Desktop. Browser opens automatically. Next time: double-click the Desktop shortcut.

### Windows — one command

Open PowerShell (Win+R → "powershell"), paste, and press Enter:

```powershell
irm https://raw.githubusercontent.com/udhawan97/FolioSenseAI/release-v4.1/scripts/install-win.ps1 | iex
```

Downloads, installs, and places a **FolioSenseAI** shortcut on your Desktop. Browser opens automatically. Next time: double-click the Desktop shortcut.

### Upgrading from v4.0

Run the same install command above — it detects your existing `database/` and `.env`, preserves them, and starts the updated app. No manual backup or file copying required.

No schema migration or `.env` change required. All v4.0 data carries over as-is.

---

## Final Word

v4.1 is still not financial advice. It is just the first version that will let you configure Claude from the dashboard while watching exactly how much each opinion costs.

---

# FolioSenseAI v4.0 Release Notes

**Release date:** June 27, 2026

---

## ✦ The Portfolio Finally Has Opinions

> *v4.0 is the release where the dashboard stopped watching your book and started reading it. Now it tells you what to do with it — and what the market is saying about it while you decide.*

Your portfolio now has an **Action Plan**. Claude reads the full book — signals, regime, concentration, earnings risk — and comes back with a prioritized Hold / Add / Trim / Exit breakdown, a thesis for each bucket, and the macro mood ring right there on the card. No Claude key? The local fallback runs the same bucket logic deterministically and generates plain-language headlines and per-bucket priority moves, no API call, no wait. Either way, the plan is cached for 24 hours and invalidates itself when your portfolio's dominant action or concentration meaningfully shifts — so rebalancing clears the stale take without you having to ask.

Your portfolio also has a **News tab** now — a fourth zone alongside Overview, Holdings, and Analytics. It pulls live yfinance headlines for every active holding, dedupes, caches, and groups them by ticker. In Claude mode it adds a portfolio-wide briefing and a set of cross-holding theme clusters so you can see which macro story is quietly working three of your positions at once. Holdings with no news still appear; the feed never silently drops a position.

The cockpit got a deeper pass too. The dark canvas is noticeably darker, panels lift off it cleanly, the gain/loss bar is taller, the P&L glow is more dramatic, the sector strip is glassier, and two cascading specificity bugs that were leaving icon pills cramped in the holdings table were finally rooted out and killed.

v4.0 is the release where "what does this mean?" gets a partner: "what should I actually do about it?"

---

## What's New

### Action Plan

- **`/api/ai/action-plan`** — Claude reads the full portfolio signal snapshot and returns a prioritized bucket plan: Hold / Add / Trim / Exit. Each bucket carries a thesis, top moves, and supporting context. Cached 24 h in `AISummary` (ticker=`BOOK`, type=`action_plan`). Falls back deterministically when Claude is unavailable or `force_local=True`.
- **Drift invalidation** — the cache key includes the portfolio's dominant-action distribution and concentration signature. Rebalancing or a meaningful shift in signals automatically invalidates the cached plan so a stale take never lingers after you act.
- **Regime-aware context** — the plan surfaces the current market regime (risk-on / risk-off / neutral) alongside the thesis so bucket decisions have macro backdrop, not just holding-level math.
- **Local fallback with real language** — when Claude is not in the loop, the fallback now builds a plain-language headline from the dominant signal ("3 positions flagged for trim/exit — 4 anchors steady") and generates per-bucket priority moves with specific tickers and actionable copy.
- **Action Plan UI** — four bucketed cards with colour-accented top borders, regime chip, Claude vs Local mode badge, per-bucket thesis, and a refresh button. Skeleton loading state holds layout during the fetch so the card does not pop.

### News

- **`/api/news/feed`** — always available (no Claude key needed). Fetches and caches yfinance headlines for all active holdings and watchlist tickers concurrently. Normalized, deduped, and sorted by recency. Holdings with no news are still included so the feed never silently omits a position.
- **`/api/news/themes`** — Claude mode only, gated on heartbeat. One Haiku call per unique headline signature: a second-person portfolio briefing ("here is what today's news means for your book") plus cross-holding theme clusters grouping the macro narrative that is hitting multiple positions at once.
- **`news_service.py`** — new service covering fetch, in-memory TTL caching (5 min during market hours, 1 h when closed), normalization, dedup, and concurrent multi-ticker fetching.

### UI Polish

- **Darker canvas** — `--bg-base` deepened (`#0a0a0f` → `#050508`), surface opacities pulled back, nav surface opacity raised (`0.62` → `0.88`). Every panel now has more room to lift off the background.
- **Snapshot panel shell** — panels carry their own opaque dark surface, a stronger top-edge inset highlight, and a real drop shadow.
- **Sector strip** — taller (4.5 rem → 6 rem), border-radius bumped, segment sheen dialed back (0.28 → 0.18) for a glassier feel.
- **Gain/loss bar** — taller (0.7 rem → 1 rem); mover tracks taller (0.48 rem → 0.65 rem) with a higher-contrast track background.
- **P&L glow** — text-shadow radius widened (22 px → 32 px) for a more dramatic green/red bleed on positive and negative days.
- **Briefing card** — ambient periwinkle crown stronger (9% → 14%), header padding bumped, separator upgraded from `--hairline` to `--hairline-hover`.
- **Holdings mode box icon fix** — a specificity collision between the GROUP rule (0,2,0) and the per-element rule (0,2,0) left `min-height` losing unpredictably, clipping icons at the top of manage-modal pill buttons. Parent-scoped selectors at (0,3,0) now definitively own `min-height`, `justify-content`, and `overflow` for both modal segments and table-row strips.

### Bug Fixes

- **Mode persistence** — `initDashboardPet()` was hardcoding `_forcedLocalMode = true` on every page load, silently overwriting the preference saved by `enableClaudeAiAndReload()`. The fix reads the `PET_MODE_KEY` value from `localStorage` and only defaults to local (`"1"`) when no preference is stored. Switching to Claude AI now sticks across reloads.
- Two new tests in `tests/test_intelligence_engine_ui.py`: one asserting the init function reads localStorage and `enableClaudeAiAndReload()` writes `"0"`, one asserting the nav Engine toggle and the banner "Enable Claude AI" button both exist with correct `aria-pressed` and JS wiring.

---

## Developer Notes

- FastAPI metadata version **`4.0.0`**
- New router: `app/routers/news.py` — mounted at `/api/news`
- New service: `app/services/news_service.py`
- New AI service function: `generate_news_themes()` in `ai_service.py`
- `_collect_portfolio_signals_core()` extracted and shared between `/investment-signals/all` and `/action-plan` to avoid computing the signal pipeline twice
- Static cache keys: `style.css?v=97`, `dashboard.js?v=90`, `analytics-charts.js?v=13`
- No database schema changes — no migration required.
- No `.env` changes required.
- **356 tests passing**

---

## Install & Upgrade

### Fresh install

**Mac / Linux**

```bash
curl -L -o FolioSenseAI-v4.0.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v4.0.zip
unzip FolioSenseAI-v4.0.zip
cd FolioSenseAI-release-v4.0
./scripts/setup.sh
```

**Windows PowerShell**

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v4.0.zip" -OutFile "FolioSenseAI-v4.0.zip"
Expand-Archive -Path "FolioSenseAI-v4.0.zip" -DestinationPath .
cd FolioSenseAI-release-v4.0
.\scripts\setup.ps1
```

### Upgrade from v3.x

1. Stop the app (`Ctrl+C`).
2. Back up `database/` and `.env`.
3. Download v4.0 into a **new folder** — do not overwrite in place.
4. Copy `database/` and `.env` into the new tree.
5. Run setup once, then use `start.sh` / `start.ps1` going forward.

No schema migration or `.env` change required. All v3.x tables carry over as-is.

---

## Final Word

v4.0 is still not financial advice. It is just the first version that will tell you, with a thesis and a regime chip, what it thinks you should probably do about it.

---

# FolioSenseAI v3.1 Release Notes

**Release date:** June 27, 2026

---

## ✦ Warm on Arrival

> *v3.1 is the release where the dashboard stopped treating every page load like the first time it had ever heard of your portfolio. The data was already there — it just needed somewhere to live between refreshes.*

Your holdings table now paints from the last saved snapshot the moment the page opens, before a single network request has left the building. Behind the scenes, every service that once scraped Yahoo Finance independently — quotes, analyst recommendations, holding intelligence, earnings dates, move explanations, ETF price signals — now shares a single cached response per ticker, with TTLs that stretch to an hour when the market is closed. A background thread warms those caches on startup so the first real fetch is never cold. Two O(n) hot paths in the Analytics Signals pane became O(1). And a quiet design pass made the verdict mix bar, signal board tiles, and confidence spectrum feel more considered.

v3.1 is a tightening, not a reinvention. The same cockpit, now ready before you sit down.

---

## What's New

### Performance

- **Shared `.info` cache** — six previously independent callers (quotes, analyst recs, holding intelligence, earnings calendar, move explainer, ETF price-zone signal) now draw from one cached Yahoo Finance scrape per ticker via `get_ticker_info()`. TTL is 5 minutes during market hours, 1 hour when closed. Redundant round-trips on a typical dashboard load: gone.
- **Stale-while-revalidate portfolio cache** — on every successful `/api/portfolio/value` response the full payload is written to `localStorage`. On the next page open the holdings table and summary cards render instantly from that snapshot; live prices replace them in place as they arrive.
- **Background startup warmup** — a daemon thread fires immediately on server start, pre-fetching quotes, 1-year history closes, and world market data for all active holdings. The first real dashboard request hits a warm cache rather than a cold scrape.
- **Analytics Signals O(1) lookups** — watchlist filtering and allocation-weight accumulation rebuilt with a `Set` and `Map` respectively, replacing `Array.find` calls inside hot iteration loops.

### UI Polish

- **Verdict mix bar** — taller at 18 px (up from 12), segment gaps with individual rounded end-caps, inset shadow for depth.
- **Signal board tiles** — wider minimum footprint (104 px), taller minimum height (72 px), larger ticker label (0.95 rem), smoother `will-change` lift on hover with border and shadow transition.
- **Confidence spectrum** — band rows separated by hairlines, indicator dot enlarged with a `color-mix` glow ring, ticker pills show a hover state, average confidence value enlarged and set in tabular numerals, `+N more` badge simplified.

### Code Quality

- **Bug fix** — `data_quality` in `holding_intelligence.py` was stuck at `"static"` whenever live country weights or top holdings arrived but live sectors did not. It now correctly reflects `"live"` whenever any live data is present.
- Removed `_normalize_expense_ratio` — the function only cast to `float` and did not perform the normalization its name and docstring claimed; logic is now inline with an accurate comment.
- `stock_service.py` restructured end-to-end: module docstring added, constants and helpers appear before the functions that reference them, `_parallel_fetch()` extracted to deduplicate `get_all_quotes` / `get_portfolio_quotes`, closure `_r()` promoted to module-level `_round_or_none()`.
- Dead function `holdingAllocPct()` in `analytics-charts.js` removed — fully superseded by the `allocByTicker` Map.
- Buried local imports in `holding_intelligence.py` moved to module top (no circular dependency); lazy `import yfinance` inside `etf_price_signal.fetch_etf_price_signal` promoted to module level.
- `event_calendar.py` and `move_explainer.py` migrated to `get_ticker_info()` — they now benefit from the shared cache automatically.

---

## Developer Notes

- FastAPI metadata version **`3.1.0`**
- Static cache keys: `style.css?v=97`, `dashboard.js?v=90`, `analytics-charts.js?v=13`
- No database schema changes — no migration required.
- No `.env` changes required.
- **297 tests passing**

---

## Install & Upgrade

### Fresh install

**Mac / Linux**

```bash
curl -L -o FolioSenseAI-v3.1.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v3.1.zip
unzip FolioSenseAI-v3.1.zip
cd FolioSenseAI-release-v3.1
./scripts/setup.sh
```

**Windows PowerShell**

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v3.1.zip" -OutFile "FolioSenseAI-v3.1.zip"
Expand-Archive -Path "FolioSenseAI-v3.1.zip" -DestinationPath .
cd FolioSenseAI-release-v3.1
.\scripts\setup.ps1
```

### Upgrade from v3.0

1. Stop the app (`Ctrl+C`).
2. Back up `database/` and `.env`.
3. Download v3.1 into a **new folder** — do not overwrite in place.
4. Copy `database/` and `.env` into the new tree.
5. Run setup once, then use `start.sh` / `start.ps1` going forward.

No schema migration or `.env` change required. Your `verdict_snapshots` table carries over as-is.

---

## Final Word

v3.1 is still not financial advice. It is just ready before you finish opening the tab.

---

# FolioSenseAI v3.0 Release Notes

**Release date:** June 27, 2026

---

## ✦ The Portfolio Stopped Pretending It Was Diversified

> *FolioSenseAI v3.0 is the release where your book gets treated like a system — overlap, mood, timelines, and three futures with probability bars — instead of a decorative pile of tickers wearing a diversification costume.*

Your portfolio finally has **look-through exposure**, a **market-regime chip**, **peer context**, **earnings risk flags**, **Base/Bull/Bear scenarios**, and an entire **Analytics** tab with five sub-zones and per-chart insight lines. Claude and Local Intelligence now share one engine across briefing, analytics, and verdicts. The navbar got an overflow menu. The pet only wiggles on hover. Very composed. Still judging you.

---

## What's New

### Dashboard &amp; UX

- **Three zones** — Overview, Holdings, and Analytics with persistent tab state
- **Portfolio briefing card** — Claude narrative or deterministic local digest
- **Navbar overflow menu** — theme, text size, pet mode, AI-cost controls in one sheet
- **Semantic color tokens** — green means money up, not "design liked it"
- **Local Intelligence guide** — dismissible banner when Claude is available but Local mode is active
- **Holdings command deck** — action tray, agent status pill (idle / scanning / ready)

### Intelligence &amp; Verdicts

- **Look-through exposure** — sector, country, theme overlap, duplicate detection, HHI concentration
- **Market regime context** — SPY/TLT/VIX/UUP backdrop with cached daily weight shifts
- **Peer-relative positioning** — own-range percentile vs peer median
- **Earnings event awareness** — names inside 14 days get capped confidence and a risk note
- **Time horizons** — `auto` / `trade` / `core` / `anchor` with cycle pill on verdict card
- **Confidence ranges** — `range_low` / `range_high` beside headline score
- **Base / Bull / Bear scenarios** — local paths plus Claude probability splits when AI is connected
- **Claude tension gating** — nudges only when inputs conflict; agreement skips the drama
- **Verdict calibration snapshots** — logged to SQLite for future hit-rate accountability
- **Deep intelligence on expand** — richer context loads async when you open a row

### Analytics *(new zone)*

- **Five sub-tabs** — Performance, Risk, Exposure, Signals, Markets
- Lazy Chart.js visualizations with per-tab insight bar and per-widget tip cards
- Growth projection, correlation matrix, drawdown, beta, rolling vol, sector tilt, conviction gaps, macro alignment, and more

---

## Developer Notes

- FastAPI metadata version **`3.0.0`**
- New services: `portfolio_exposure.py`, `market_regime.py`, `peer_relative.py`, `event_calendar.py`, `verdict_calibration.py`, `verdict_ai_enhancement.py`, `portfolio_analytics.py`, `portfolio_projection.py`, `analytics_insights.py`
- Extended `investment_signal.py` — horizon weights, confidence ranges, scenario builders, modifier hooks
- Extended Claude prompts in `ai_service.py` — disagreement, scenario-probability, briefing, analytics-narrator
- `VerdictSnapshot` model + startup migration for `verdict_snapshots`
- Extended `hold_class` schema — `trade` and `core` alongside `auto` and `anchor`
- New API routes under `/api/portfolio/*`, `/api/ai/portfolio-summary`, `/api/ai/analytics-insights`, `/api/ai/portfolio-exposure`, `/api/ai/verdict-calibration`, `/api/ai/intelligence/{ticker}/deep`, `/api/stocks/world-markets`, `/api/stocks/history/batch`
- Static cache keys: `style.css?v=93`, `dashboard.js?v=88`, `analytics-charts.js?v=9`
- Analytics insights cache version **`widget_insights_version: 2`**
- **`297 tests passing`** — analytics, briefing, projection, intelligence engine UI, calibration, scenarios

---

## Install &amp; Upgrade

### Fresh install

**Mac / Linux**

```bash
curl -L -o FolioSenseAI-v3.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v3.zip
unzip FolioSenseAI-v3.zip
cd FolioSenseAI-release-v3
./scripts/setup.sh
```

**Windows PowerShell**

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v3.zip" -OutFile "FolioSenseAI-v3.zip"
Expand-Archive -Path "FolioSenseAI-v3.zip" -DestinationPath .
cd FolioSenseAI-release-v3
.\scripts\setup.ps1
```

Open [http://localhost:8000](http://localhost:8000). Anthropic API key is optional.

### Upgrade from v2.x

1. Stop the app (`Ctrl+C`).
2. Back up `database/` and `.env`.
3. Download v3 into a **new folder** — do not overwrite in place.
4. Copy `database/` and `.env` into the new tree.
5. Run setup once, then `start.sh` / `start.ps1` going forward.

The `verdict_snapshots` table is created automatically on startup. No `.env` changes required. `force_local=true` still skips Claude; all local intelligence works offline.

---

## Final Word

v3.0 still is not financial advice. It is a more honest briefing layer — overlap, mood, timelines, and futures with probability bars — for portfolios that stopped pretending five tech ETFs count as diversification.

---

# FolioSenseAI v2.4 Release Notes

**Release date:** June 25, 2026

## Headline

FolioSenseAI v2.4 is the mode-control release: Claude when you want the charm, Local Intelligence when you want deterministic quiet, and fresher-feeling market data without extra drama.

## What's New

- **Claude AI / Local Intel toggle** — switch verdict quips without removing your API key
- **`force_local=true`** on `/api/ai/investment-signals/all` — deterministic local quips on demand
- **Persistent mode preference** in browser storage
- **60-second quote cache** — snappier repeated dashboard loads
- **Last-sync resilience** — keeps last good timestamp on failed refresh
- **Sync-state race fix** — HUD commits before render; in-flight guard on portfolio value load
- **Toggle polish** — placement, labels, pet copy

## Upgrade Notes

No database migration or `.env` change required.

```bash
curl -L -o FolioSenseAI-v2.4.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v2.4.zip
unzip FolioSenseAI-v2.4.zip
cd FolioSenseAI-release-v2.4
./scripts/setup.sh
```

---

# FolioSenseAI v2.3 Release Notes

**Release date:** June 2026

## Headline

FolioSenseAI v2.3 is the graceful-offline release: clearer no-key behavior, sharper local labels, and one less thing for CodeQL to side-eye.

## What's New

- Claude offline setup guidance in the brand callout
- **Local Intelligence Verdict** labels when Claude is disconnected
- Dynamic verdict kicker updates on reconnect
- Day-change rendering polish and timing-signal log sanitization

## Final Word

v2.3 still is not financial advice. It just stopped pretending Claude was whispering when he wasn't in the room.
