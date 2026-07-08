---
title: Release Notes
description: What's new in FolioSenseAI, release by release.
---

The full changelog lives in
[`RELEASE_NOTES.md`](https://github.com/udhawan97/FolioSenseAI/blob/main/RELEASE_NOTES.md)
in the repository. Highlights of the current release below.

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

## v4.3 — FolioSenseAI Goes Desktop

- **One-click desktop installers** — no Python, no terminal. Download a native app for
  [macOS (Apple Silicon)](https://github.com/udhawan97/FolioSenseAI/releases/latest) or
  [Windows (x64)](https://github.com/udhawan97/FolioSenseAI/releases/latest) and launch it
  like any other app. The FastAPI server runs in-process behind a native window
- **Automated release pipeline** — every tagged release builds, smoke-tests, and publishes
  the `.dmg` and `.exe` to [GitHub Releases](https://github.com/udhawan97/FolioSenseAI/releases)
  with a `SHA256SUMS.txt`, so a broken build can never replace a good download
- **Rolling `latest-main` builds** — every merge to `main` refreshes a prerelease with the
  newest installers, available under "Development builds" on the site for early testers
- **Download-first website** — the [landing page](https://udhawan97.github.io/FolioSenseAI/)
  detects your OS, links straight to the current installer, and shows live release
  version, date, and checksums
- **Honest trust story** — early builds aren't code-signed yet, so the
  [install guides](https://udhawan97.github.io/FolioSenseAI/download/) walk through the
  expected macOS Gatekeeper / Windows SmartScreen warnings and how to verify your download
- **Local data stays put** — the installed app keeps your database and `.env` in the
  per-user data directory (`~/Library/Application Support/FolioSenseAI` on macOS,
  `%APPDATA%\FolioSenseAI` on Windows), never inside the app bundle

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

See the full [`RELEASE_NOTES.md`](https://github.com/udhawan97/FolioSenseAI/blob/main/RELEASE_NOTES.md)
for prior versions and complete technical detail on each change.
