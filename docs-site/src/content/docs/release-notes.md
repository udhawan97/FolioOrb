---
title: Release Notes
description: What's new in FolioOrb, release by release.
---

The full changelog lives in
[`RELEASE_NOTES.md`](https://github.com/udhawan97/FolioOrb/blob/main/RELEASE_NOTES.md)
in the repository. Highlights of the current release below.

## v5.1.0 — Looking Back, Honestly

- **Year-end realized recap.** The Realized gains tab now opens with a year-by-year recap of
  your closed trades — realized P&L and return, sales and tickers covered, winners vs losers,
  and the best and worst position of the year. Reads every stored trade from your local
  database; no live quotes. Switch years with the toggle.
- **A verdict report card.** The Signals tab grades FolioOrb's own past Add / Trim / Hold calls
  by how each holding has done *since* the call — an overall "aged well" rate, a per-action
  breakdown, and a ledger with a ✓/✗ per call. A look-back, not a forward bet; small samples
  are noisy and it's not financial advice.
- Installing over any 5.0.x keeps all holdings, settings, and `.env`.

## v5.0.0 — FolioOrb

FolioOrb is the native desktop app for local-first portfolio intelligence.

- **FolioOrb everywhere** — app window, installers (`FolioOrb-macOS-arm64-*.dmg`,
  `FolioOrb-Windows-x64-*-Setup.exe`), docs, and repository at
  [github.com/udhawan97/FolioOrb](https://github.com/udhawan97/FolioOrb).
- **Data stays local** in the normal per-user app data directory for your
  platform.
- **Privacy posture stays clear** — FolioOrb is local-first, Claude-optional,
  never places trades, and reports to nobody.

## v4.5.2 — Reliability patch

A full-codebase bug audit and the fixes it surfaced — no new features, just
sturdier numbers and safer data.

- **Bad market data no longer poisons your analytics.** A zero or negative close
  (a halted or delisted ticker, a data glitch) used to contaminate annualized
  return, volatility, and correlation with `NaN`; those days are now treated as
  flat. Correlation reports "no data" honestly when a frozen price series makes
  it undefined, instead of faking a `0.0`.
- **Trim verdicts score the right way round** — a cheap stock is no longer handed
  a high-confidence *trim*.
- **A failed rollback can never leave you with no database.** Restore now stages
  and re-verifies the backup before touching your live database, and tells you
  clearly if data restored but settings didn't.
- **Watchlist edits never fabricate P&L**, the batch price-history endpoint
  validates its `period`, plus assorted updater, cache, and logging hardening.

No migration or `.env` change required.

## v4.5.1 — Export That Actually Exports

- **Fixed: CSV export and the import template now download in the desktop app.** The
  packaged app is a native window with no download chrome, so **Export CSV** and **Download
  template** used to open the file inline as raw text — no Save dialog, no back button. Both
  now route through a native **Save As…** dialog and write a real `.csv` (UTF-8 with the BOM
  Excel expects). Browsers download exactly as before. Either way, you get a file, not a
  dead end.
- **Website polish** — Senpai gets his own animated spotlight above the footer, a refreshed
  one-liner pill, and CSV import is now called out in the workflow walkthrough.
- Installing over v4.5.0 keeps all holdings, settings, and `.env`. Nothing about your data
  changes.

## v4.5.0 — The Spreadsheet Release

- **Export your holdings as CSV.** One click in the portfolio manager downloads your active
  holdings and watchlist as a clean, Excel-ready CSV — with every cell escaped against
  spreadsheet formula injection. The file you get *is* the import template.
- **Import holdings, two ways.** *Local* (always available, no API key) does a strict,
  exact-schema parse of the template — deterministic, free, offline, and never gated.
  *Claude assist* (when a key is set) maps almost any brokerage export onto the FolioOrb
  format for you, and every mapped row still passes the same strict validation before it
  touches your book. Clean template files skip Claude entirely.
- **A per-row report either way** — added, skipped (duplicates are skipped, never
  overwritten), or errored with a plain-English reason — plus a Senpai-narrated recap in
  Claude mode. Safety as usual: a 256 KB / 200-row import cap and content-type checks.

## v4.4.1 — Software Update, done right

- **Fixed: the updater falsely showing "You're offline."** The packaged app's bundled OpenSSL
  pointed at a build-machine certificate path that doesn't exist on your Mac, so every update
  check failed TLS verification and was reported as "offline" even when you were connected. Now
  fixed at the root — the checker verifies against a CA bundle shipped inside the app — and
  failure states are told apart instead of lumped together ("Couldn't securely check for
  updates," "GitHub rate limit reached," etc., each with its own diagnostic).
- **Real in-app updates on macOS**, not just "open the DMG." Update Now downloads, verifies,
  backs up your data, swaps in the new app, and relaunches automatically. Windows keeps its
  one-click silent install.
- **A consent-first in-app update system.** FolioOrb checks quietly for new versions, shows
  a calm indicator when one's available, and never downloads or installs without an explicit
  click. Check any time from **Check for Updates…** in the app menu or **Settings → Software
  Update**.
- **Your holdings are protected at every step.** A verified backup is taken before any update or
  migration; if the backup can't be made or fails verification, the update pauses rather than
  risking your data. **Restore previous version…** rolls back safely, always snapshotting current
  data first so nothing is lost either way.
- **Trustworthy downloads.** SHA-256 verified against published checksums, with optional minisign
  authenticity signing. Release notes render as text, not raw HTML.
- Built in eight phases, then hardened through repeated rounds of adversarial review — against
  both source and the actual installed app — that caught and fixed the offline/TLS root cause plus
  nine other real issues, including a data-loss gap in backup verification, an XSS path in
  release-notes rendering, and a macOS "quit unexpectedly" crash on every exit. 256 dedicated
  tests, `pylint` 10.00.

## v4.3.4 — Quieter Hot Paths

- **Performance release — no feature changes.** Targeted fixes to the code that runs most
  often, so the dashboard stays smooth as portfolios and interactions scale up. Installing
  over v4.3.3 or earlier keeps all holdings, settings, and `.env`.
- **Currency formatting no longer allocates per value** — every dollar figure was built with
  a freshly constructed `Intl.NumberFormat`, which is far more expensive than the formatting
  itself. The currency and world-market formatters are now built once and reused. Output is
  byte-for-byte identical.
- **The correlation heatmap stops rebuilding its canvas on hover** — the hover redraw was
  reassigning the canvas's pixel dimensions every time, which reallocates and clears the whole
  backing store even when the size is unchanged. It now only resizes the bitmap when the
  dimensions actually change.
- **Hover and resize work is coalesced to one pass per frame** — the heatmap's `mousemove`
  handler and the two dashboard-zone indicator resize handlers are throttled to
  `requestAnimationFrame`, so at most one layout read/redraw runs per frame.
- **Fixed misleading "AI failed" warnings when no Claude API key is configured** — running
  key-free (the default Local Intelligence mode) logged every briefing/insights/action-plan
  request as a warning-level failure, even though it's the expected, harmless case. These now
  log at debug with an accurate message; a genuine failure with a key present still warns.
- **Fixed the greyed-out Engine toggle opening the wrong panel** — tapping the disabled
  "Local Intel" control (no API key set) opened the passive intro card instead of the
  interactive **Connect Claude AI** panel. It now opens that panel directly — paste a key,
  hit Save & Connect, no restart — and closes the menu first so it isn't covered.
- **Verified:** the full 381-test suite passes, `pylint` holds at 10.00/10, and the theme,
  spacing, typography, and animations are untouched — these changes affect only how existing
  work is scheduled and routed, not what is drawn.

## v4.3.3 — One Range, Every Section

- **Feature release.** The Overview time-range switcher (Today / 1M / 3M / 6M / 1Y) gains a
  **1W** option and now drives the sector/movers panel, the portfolio briefing, and the
  allocation focus read — not just the P&L card. Installing over v4.3.2 or earlier keeps all
  holdings, settings, and `.env`.
- **One shared range.** All four sections read from a single selected time range instead of
  managing their own state, so switching to 3M means Insights, Briefing, Allocation, and
  P&L all narrate the same three months.
- **Fixed a real inconsistency** caught during testing: the hero P&L card needed weeks of the
  app's own usage history to compute longer ranges, so a newer portfolio could show
  "1M P&L: --" directly above a movers panel already showing a real number for that month
  from actual market price history. The hero card now falls back to the same price-history
  calculation so both agree.
- **Performance:** all five non-day ranges come from one new endpoint in a single request,
  cached per holdings set so revisiting a range is instant with no network call. Rapid
  switching never flashes stale data, each section fails independently with its own
  inline retry, and manual refresh now refreshes range data too.

## v4.3.2 — Scrolling, Finished

- **Performance release — no feature changes.** Second half of the v4.3.1 scroll fix,
  this time aimed at portfolios with a real number of holdings in them. Installing over
  v4.3.1 or earlier keeps all holdings, settings, and `.env`.
- **Fixed a sparkline redraw bug** — each holding's 7-day trend canvas was repainting
  every time it scrolled into view, even when its price history hadn't changed. It now
  only redraws when the data actually changes, verified pixel-for-pixel.
- **Fixed the real cost** — switching away from the Holdings tab hid it with
  `visibility: hidden`, which keeps a hidden element fully "in play" for layout. With
  enough holdings, that table's column-width math is expensive, and it was being
  recomputed on every scroll frame on *every* tab — not just Holdings. It's now skipped
  entirely while off-screen (`content-visibility: hidden`) and restored instantly on switch.
- **Result:** roughly 4× faster scrolling on Overview and Holdings with a 30-holding
  portfolio, with Analytics and News both meaningfully smoother too.

## v4.3.1 — Smooth Scrolling in the Desktop App

- **Performance release — no feature changes.** The native app scrolled sluggishly on
  macOS; v4.3.1 fixes it. Installing over v4.3.0 keeps all holdings, settings, and `.env`.
- **Fixed the universal scroll killers** — the ambient background moved off the scrolling
  page onto a fixed, compositor-cached layer (`background-attachment: fixed` repainted the
  whole gradient every frame), and the drifting background orbs lost a heavy `blur(40px)`
  filter that was re-rasterized each frame. Both help the browser and from-source runs too.
- **Desktop-app rendering profile** — inside the system WebView (WKWebView / WebView2) the
  app now drops `backdrop-filter` and freezes a few always-on ambient animations, which
  those engines render expensively. Frosted surfaces fall back to near-opaque fills, so the
  look holds up; the in-browser experience is left at full fidelity.
- **Result:** ~3× smoother scroll frame rate on the overview and analytics views in
  throttled testing, with janky frames cut by roughly two-thirds.

## v4.3 — FolioOrb Goes Desktop

- **One-click desktop installers** — no Python, no terminal. Download a native app for
  [macOS (Apple Silicon)](https://github.com/udhawan97/FolioOrb/releases/latest) or
  [Windows (x64)](https://github.com/udhawan97/FolioOrb/releases/latest) and launch it
  like any other app. The FastAPI server runs in-process behind a native window
- **Automated release pipeline** — every tagged release builds, smoke-tests, and publishes
  the `.dmg` and `.exe` to [GitHub Releases](https://github.com/udhawan97/FolioOrb/releases)
  with a `SHA256SUMS.txt`, so a broken build can never replace a good download
- **Rolling `latest-main` builds** — every merge to `main` refreshes a prerelease with the
  newest installers, available under "Development builds" on the site for early testers
- **Download-first website** — the [landing page](https://udhawan97.github.io/FolioOrb/)
  detects your OS, links straight to the current installer, and shows live release
  version, date, and checksums
- **Honest trust story** — early builds aren't code-signed yet, so the
  [install guides](https://udhawan97.github.io/FolioOrb/download/) walk through the
  expected macOS Gatekeeper / Windows SmartScreen warnings and how to verify your download
- **Local data stays put** — the installed app keeps your database and `.env` in the
  per-user data directory (`~/Library/Application Support/FolioOrb` on macOS,
  `%APPDATA%\FolioOrb` on Windows), never inside the app bundle

## v4.2 — Meet Senpai, and Never Get Lost on Day One

- **Senpai** — the dashboard orb formerly known as "dashboard pet" / "Portfolio Butler"
  is now named Senpai everywhere: ids, classes, JS, `localStorage`, and the visible label
- **Tips & tricks** — Senpai's quote rotation now surfaces genuinely useful one-liners
  (Research mode, hold-type icons, keyboard shortcuts) about 1 time in 4
- **First-run welcome guide** — a one-time modal on a fresh install with zero holdings,
  covering how to add a holding, what Research mode means, and what the four hold-type
  icons do — sourced straight from the same tooltips used elsewhere in the app
- **Docs site fix** — 5 internal links that 404'd on GitHub Pages (missing the site's
  base path) are fixed, and a **Documentation** link was added to the app's nav menu

## v4.1 — The Dashboard Finally Knows Its Own Key

- **In-dashboard API key configuration** — paste a Claude key from the nav, validated and
  written to `.env`, reconnected without a restart
- **Live token cost tracking** — the cost HUD now shows real accumulated input/output
  tokens and actual spend instead of a cache-based estimate
- **First-click holding expand** — rows expand their intelligence panel on the first
  click, with auto-refresh keeping prices current
- **Overview sector graph rework** — proportional weighted fills instead of absolute
  percentage bars, plus an overflow note when more sectors are held than the strip can show
- Assorted fixes: font resize regression, a scroll-interception bug, and ticker
  management now triggering a fresh quote load without a full reload

See the full [`RELEASE_NOTES.md`](https://github.com/udhawan97/FolioOrb/blob/main/RELEASE_NOTES.md)
for prior versions and complete technical detail on each change.
