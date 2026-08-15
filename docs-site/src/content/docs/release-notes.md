---
title: Release Notes
description: What's new in FolioOrb, release by release.
---

import { Aside } from '@astrojs/starlight/components';

The full changelog lives in
[`RELEASE_NOTES.md`](https://github.com/udhawan97/FolioOrb/blob/main/RELEASE_NOTES.md)
in the repository. Highlights of the current release below.

## v5.13.0 — Checked at the edges

- **Faded-out panels leave the keyboard path.** v5.12.0 gave five header panels
  one closing behaviour; other surfaces were hidden a different way — faded to
  invisible, with clicks switched off — which stops a mouse but not the Tab key.
  On a freshly loaded dashboard 14 of 47 keyboard stops were controls of this
  kind, sitting past the last visible one. The portfolio manager, the first-run
  welcome panel, the collapse pill, the hidden Senpai orb, the holdings table
  during a scan, and the loading splash now all leave the tab order while hidden,
  opening and closing exactly as before.
- **A junk symbol is refused instead of looked up.** FolioOrb's rule for a symbol
  — letters, numbers, `.`, `-` or `^`, up to 10 characters — was applied when you
  add a holding but not when one is read back. 2 of the 12 addresses that take a
  symbol checked it; the rest passed whatever arrived to the market-data provider
  and into the log. All of them now check first, including the two that take a
  comma-separated list. Valid symbols are unchanged.
- **Undoing a DCA buy can only touch its own portfolio's holding.** The undo found its
  holding by internal row number alone, and that number carries no portfolio with
  it, so it could change a holding in a different book while reporting success.
  It now looks the holding up inside the plan's own portfolio.
- No schema migration. Installing over v5.12.0 preserves local data, backups,
  settings and keys.

## v5.12.0 — Calm at every size

- **Closed header panels leave the keyboard path.** Brand, Claude-key, live-feed,
  overflow, and cost details now synchronize their visible, ARIA, and inert state;
  Escape closes the active panel and returns focus to its trigger.
- **Senpai stops covering phone-width portfolio truth.** Below 576 px the compact
  orb occupies a row after the dashboard, automatic activity stays compact, and
  the full line expands only after an explicit tap.
- **Review Plan fits 320 px.** Its cards shrink with the sheet while wide
  portfolio and target tables keep their own horizontal scrollers.
- **Restore cancellation is layered.** When an exact restore confirmation is
  open, the first Escape cancels it and returns keyboard focus to Restore; a
  second Escape closes Review Orbit. After **Queue restore** is submitted, its
  busy state blocks misleading Escape, Cancel, close, and tab actions until the
  request finishes. Explicit failures safely re-enable both choices; interrupted
  responses are reconciled with persisted Backup Vault state and otherwise stay
  visibly **Status unknown**.
- **Rehearsals cannot go stale silently.** Changing the holding or cash replaces
  the old projection with **Preview outdated**, and late or out-of-order responses
  are ignored.
- Shared service/client seams now carry portfolio scoping, valuation,
  realized-sales math, backup handling, DCA state, local exports, and Review
  Orbit behavior without changing the financial or recovery contracts.
- Privacy docs now distinguish credential-only Anthropic availability checks,
  prompted Claude payloads, and publisher/CDN news-thumbnail requests.
- No schema migration. Installing over v5.11.0 preserves local data, backups,
  settings, and keys.

## v5.11.0 — Plan & Protect

- **Set a target course.** Store exact basis-point targets across the eligible
  holdings in one Portfolio, then compare them with current allocation when every
  required USD quote is usable. Missing and foreign-priced rows block drift rather
  than being treated as zero.
- **Rehearse an external-cash buy.** Preview shares, average cost, and projected
  allocation for a ticker you already own. The rehearsal is read-only, buy-only,
  USD-only, and neither a forecast nor a recommendation.
- **See every book without blending performance.** The all-Portfolios pulse shows
  known USD value and completeness per book, isolates quote failures, and keeps its
  aggregate explicitly partial when any book is incomplete.
- **Export the record, not a tax answer.** The annual realized CSV uses stored sale
  facts and reconciles displayed rows. It does not model lots, fees, holding periods,
  wash sales, or tax classification.
- **Carry human-readable records.** A manifest-backed ZIP contains CSVs for
  Portfolios, holdings, sales, snapshots, and the DCA ledger. It excludes settings,
  secrets, AI caches, backups, and SQLite, so it is sensitive but not restorable.
- **Know whether the safety net is fresh.** Manual-backup freshness stays separate
  from an opt-in, once-per-local-day automatic policy. Auto retention touches only
  verified `auto-*` snapshots.
- Frozen smoke checks use an isolated data root, while native record exports stage
  and fsync a private sibling file before an atomic destination swap.
- Schema v6 adds a nullable target field; existing local data remains intact.

<Aside type="caution" title="Bounded on purpose">
Plan & Protect never places a trade. Targets are not recommendations, the buy rehearsal
does not model taxes or forecast prices, the realized recap is not a tax filing, and a
portable records ZIP is not a restore package.
</Aside>

## v5.10.2 — DCA deletion follow-up

- **A refused DCA delete is no longer silent.** The plan dialog now explains that
  applied buys must be undone first so their holding changes remain traceable. If
  the ledger refuses deletion, FolioOrb shows that reason in-app. Once no applied
  buys remain, deletion removes pending and skipped entries as documented.
- No schema changes or migration. Installing over v5.10.1 preserves local data and keys.

## v5.10.1 — Trust and flow patch

- **Browsing the Backup Vault is read-only.** Listing, integrity checks, holding counts,
  downloads, and restore selection no longer create SQLite WAL/SHM sidecars. An absent
  vault stays absent, and a snapshot with a non-empty sibling WAL is refused as incomplete.
  Live database backup counts remain WAL-aware.
- **DCA decisions use in-app dialogs.** Apply all, undo applied, skip all, change amount,
  and delete plan no longer depend on native browser prompts that WKWebView may not show.
  The dialogs validate inline, trap focus, cancel with Escape, and return focus to the
  opener. Ledger math and apply/undo behavior are unchanged.
- **Holdings reaches its rows on a phone.** The compact toolbar no longer inherits a
  320 px desktop flex basis after stacking vertically.
- **The welcome guide opens at the top.** It focuses Close rather than auto-scrolling to
  its footer action, while keeping its modal focus and Escape behavior.
- **Every Review Orbit tab is visible.** Phone-width tabs wrap instead of hiding Backups
  beyond a scrollbar-free strip; arrow-key navigation and tab semantics remain intact.
- No schema changes or migration. Installing over v5.10.0 preserves local data and keys.

## v5.10.0 — Architecture pass

- **Holdings can only be edited through the portfolio that owns them.** The edit,
  delete and delete-trade endpoints resolved a row by id alone and ignored the
  portfolio the request was scoped to, so with more than one portfolio a change
  could land on the wrong book — and record its realized sale in the wrong ledger.
  All three now check ownership and answer 404 when the holding isn't yours.
- **A slow endpoint no longer freezes the dashboard.** Fifty-two endpoints were
  declared async while doing blocking work (Yahoo, SEC EDGAR, Claude, large
  scans), each holding the single event loop while every other request queued
  behind it. They now run in the worker threadpool, and the guard that missed
  them sweeps every router instead of a hand-written list.
- **A single `NaN` price can no longer blank every position weight**, and with it
  the concentration score and what Claude is told about your book.
- **The action plan sees your sector and country exposure again** — it had been
  reading keys nothing produced, and sending Claude an empty block.
- **One market-hours answer and one concentration scale**, instead of two of each
  that could disagree on the same page.
- No schema changes and no migration.
- Also ships the user-flow resilience work below, which was prepared as v5.9.3
  and never cut as its own tag.

## v5.9.3 — User-flow resilience (shipped in v5.10.0)

- **Review Orbit owns the viewport.** It stays fixed above the sticky navbar on
  compact screens and hides fixed dashboard utilities while open.
- **Holding details work from the keyboard.** Native disclosure controls expose
  their expanded state, collapsed detail content leaves the accessibility tree,
  and ticker lookups stay scoped to the holdings table.
- **News failures are retryable.** A failed feed offers an announced in-place
  retry and does not require a page reload to recover.
- **Focus returns somewhere visible.** Closing Manage after entering from the
  first-run guide falls back to the named Manage control instead of focusing the
  hidden guide.
- **Help buttons have names.** Icon-only tooltip triggers—including dynamically
  rendered ones—derive an accessible name from their help heading.
- **The Action Plan fits 320 px.** Its header stacks cleanly with no page-wide
  horizontal overflow.
- No portfolio math, trade behavior, or schema changed; existing data and keys
  are preserved.

## v5.9.2 — No duplicate requests on load

- **A cold load no longer fetches the same endpoint twice.** It was 29 requests
  across 26 endpoints; it is now 26 across 26. Sparkline history and the benchmark
  comparison share one request between the cached-paint and live-fetch passes, and
  the intelligence-mode handler no longer redoes its work when the Claude heartbeat
  re-applies a mode that has not changed. Refreshing still refetches everything.
- **One Claude call per payload.** The AI insights loader had two callers that could
  fire together on a switch into Claude mode and no in-flight guard, so a single
  payload could cost two billed calls. It now has the same guard its local
  counterpart always had.
- This closes the known issue listed under v5.9.1 below. No feature or schema
  changes.

## v5.9.1 — Userflow fixes

- **The welcome guide is a real modal.** The first-run guide blocked the mouse but left the
  dashboard behind it reachable by Tab, and never moved focus into itself. It now marks the
  background inert, moves focus to **Add your first holding**, traps Tab in both directions,
  and returns focus to its opener — matching Review Orbit and the portfolio manager.
- **Senpai settles instead of covering the numbers.** On desktop the quip bubble stayed
  pinned open over the bottom-right of the dashboard, hiding Today's impact contributions
  and part of the world-markets strip. It now fades back to the orb a few seconds after it
  speaks, as it already did on mobile. Clicking the orb brings the last line back.
- **Ticker validation works again.** The ticker field's `pattern` was not a valid regular
  expression under the stricter parser current browsers use, so it was dropped entirely and
  logged a console error on every load. Dashes and carets (`BRK-B`, `^GSPC`) validate as
  intended; invalid input no longer slips past the field check.
- **Add-holding errors are announced.** The inline error is now a live region tied to the
  ticker field, so screen-reader users hear what went wrong.

### Known issues

- A cold load still requests three endpoints twice (`benchmark-comparison`,
  `analytics-insights`, and the batched price history), which lengthens first paint. Queued
  for the next release.

## v5.9.0 — The Review Orbit

- **One review workspace.** Inbox, Data Trust Center, monthly/quarterly Review Pack,
  type-aware Watchlist Compare, thesis cadence, and the Local Backup Vault live behind the
  new Review control.
- **Attention without automation.** Price gaps, pending DCA buys, upcoming earnings,
  calibration history, and thesis reviews are prioritised locally. Nothing places a trade
  or changes a holding.
- **Coverage before confidence.** Prices, quote metadata, fund fees, dividend
  classification, top-holdings ETF overlap, theses, and stored history disclose their
  coverage and sources. Missing stays missing.
- **Verified recovery.** Manual vault snapshots contain the SQLite database only, excluding
  API keys and `.env`. Restores are verified, applied only across a clean restart, and keep
  a verified safety copy of the pre-restore database.
- **Review packs tell the truth about returns.** Print-ready HTML and CSV include current
  valuation, stored snapshots, realized trades, P&L contributors, and thesis attention;
  raw value change names its stored opening snapshot and is labeled as cash-flow affected,
  not time-weighted performance.
- **Additive schema v5.** Optional thesis review timestamp/cadence fields do not affect
  valuation or verdict math. Installing over v5.8.0 preserves all existing data and keys.

## v5.8.0 — The Workspace Remembers

- **Theme and place persist.** Light/dark mode and the last dashboard zone restore across
  refreshes, relaunches, and portfolio switches; the saved theme is applied before first paint.
- **Research means research.** Research-only tickers never fill the largest-holding tile,
  portfolio briefing, action-plan buckets, or invested-position projections. An all-research
  portfolio says it has no invested positions instead of narrating imaginary P&L.
- **No invented $100K projection.** With no positions, personalized scenario cards stay hidden
  and the chart shows only the S&P 500 as an index labeled `100 = start`.
- **A proper keyboard modal.** Manage Portfolio takes focus, traps Tab, makes the background
  inert, closes with Escape, and returns focus to the opener.
- **320 px without page-wide overflow.** The app bar, zone tabs, menus, cards, and internally
  scrollable holdings table stay inside the viewport.
- **Faster, truthful startup.** Frontend libraries are vendored, portfolio/market cache paints
  immediately, duplicate cache misses collapse, and cold starts use a progress-linked
  compounding splash only when there is genuinely nothing ready to show.
- Installing over v5.7.0 keeps the database, holdings, trades, DCA history, thesis notes,
  settings, and API key. No schema migration is required.

## v5.7.0 — Reasons and Seasons

- **Your thesis, on every holding.** Each expanded holding gets a box for the reason you own
  it, in your own words. Claude never reads or writes it, it round-trips through CSV, and a
  background refresh can't clobber an edit in progress.
- **A dividend calendar.** The income card now shows which months pay you, not just the annual
  total — twelve bars built from each payer's real trailing ex-dates, so a monthly REIT and a
  quarterly stock land in their own months rather than an assumed rhythm.
- **Honest about what the months mean.** They're ex-dividend months — the cutoffs to own each
  payer — and the card says so, since cash lands later. A payer whose schedule can't be read
  from history is named as unscheduled, never smeared across months nobody observed.
- Installing over v5.6.0 keeps the existing database, holdings, trades, DCA history, settings,
  and API key. No schema migration is required.

## v5.6.0 — Inside Out

- **Insider activity (SEC Form 4).** Recent open-market buys and sells by a company's own
  officers and directors, in each stock's expanded detail. Grants, gifts, and tax withholding
  are shown but never counted as conviction; funds have no insiders and say so.
- **Financials over time (SEC XBRL).** Revenue, net margin, and diluted EPS by fiscal year
  from filed numbers, with revenue history stitched across the 2018 GAAP tag change. Missing
  metrics stay blank, never a fabricated zero.
- **Dividend income view.** Annual cash your holdings pay you at your position size, blended
  yield, and an ex-dividend heads-up. Non-payers are named, never counted as $0.
- **Filings in plain English.** 8-K item codes are labelled by what they report ("Results
  announced," "Officer or director change") instead of raw numbers.
- **Fixed: low-yield dividend yields read 100× too high.** yfinance reports dividend yield in
  two fields 100× apart; a sub-1% yield rendered as tens of percent. Normalized once at the
  source — Apple now reads 0.32%, not 32%.
- Installing over v5.5.0 keeps the existing database, holdings, trades, DCA history, settings,
  and API key. No schema migration is required.

## v5.5.0 — Straight From the Source

- **The filings, unfiltered.** The News tab shows what your companies actually told the SEC —
  8-K, 10-Q, 10-K — pulled from EDGAR and linked to the source document. Funds and crypto are
  named as non-filers, never shown as companies that filed nothing. No Claude key needed.
- **The curve, and where fear actually sits.** The market backdrop reads the US Treasury yield
  curve (2s10s, 3m10y) and reports where the VIX sits in its own five-year range. An inverted
  curve nudges verdicts toward quality; flat, normal, and steep are reported and left alone.
- **What your funds cost you.** Expense ratios as real dollars per year and over a decade,
  with the growth assumption stated next to the projection. A fee that can't be read stays
  unknown — never a quiet $0.
- **Whether your ETFs are the same bet.** Pairwise overlap across your funds' top 10 published
  holdings, labeled for exactly what it measures.
- **Earnings with the bar attached.** The radar carries the consensus EPS estimate and the
  recent beat record alongside the date.
- **Fixed: fund fees read 100× too high.** An expense ratio could be scored in the most
  expensive tier when it was among the cheapest, dragging that fund's quality score. Ratios are
  now normalized once, at the source.
- Installing over v5.4.2 keeps the existing database, holdings, trades, DCA history, settings,
  and API key. No schema migration is required.

## v5.4.2 — Honest Valuation, Safer Ledgers

- **Return math now matches the full investment.** Portfolio total-return percentage includes
  the cost basis of both open and already-sold shares, matching the realized + unrealized gain
  shown beside it.
- **Bad quotes never become a confident read.** Zero, non-finite, malformed, or missing prices
  are labeled unavailable; incomplete valuations do not write daily snapshots or generate
  portfolio-level Claude briefings, analytics narration, or action plans.
- **Applied DCA buys stay traceable.** Undo applied buys before deleting their plan so the
  contribution ledger and holding mutation cannot drift apart.
- **Cleaner architecture and public docs.** Lifecycle, valuation, DCA, and narrative caching now
  have focused service interfaces, while the landing page and docs share a sharper visual system.
- Installing over v5.4.1 keeps the existing database, holdings, trades, DCA history, settings,
  and API key. No schema migration is required.

## v5.4.1 — Per-Portfolio Verdict History

- **Your track record follows the portfolio.** The Signals "how did my past calls age?" report
  card and calibration stats now scope to the portfolio you're viewing, instead of blending Add /
  Trim / Hold calls across all of them.
- Verdicts logged before this update are kept and attributed to your default portfolio (additive
  schema v4 migration). Installing over any 5.4.0 keeps everything in place.

## v5.4.0 — More Than One Portfolio

- **Multiple portfolios.** A switcher in the top bar lets you create, rename, delete, and switch
  between portfolios — give your taxable account, IRA, and experiments their own scoreboards.
- **Everything re-scopes.** Value, P&L, holdings, every analytics chart, news, DCA plans, and the
  AI briefings/action-plans all follow the portfolio you're viewing. The Manage panel names the
  one you're editing.
- **Cleanly separated.** Each portfolio's data — including its cached AI narratives (namespaced
  per portfolio) — stays its own; switching never shows another portfolio's content. "My
  Portfolio" is always present and can't be deleted; new portfolios start empty.
- Installing over any 5.3.x keeps your holdings as the default portfolio.

## v5.3.1 — Accurate Sales, Working Links

- **Record a sale at the real price and date.** Reducing a holding now lets you enter the actual
  sale price and date (pre-filled with today's, but editable) — so a sale you made last month
  books into your realized P&L and year-end recap correctly, in the right tax year. Leave the
  price blank to use the live market price.
- **External links work in the desktop app.** Links like console.anthropic.com (to get a Claude
  key) and the docs now open in your real browser instead of a dead in-app frame.
- Installing over any 5.3.0 keeps everything in place.

## v5.3.0 — Honest When Things Go Wrong

- **Never a scary $0.** If market data can't be reached, the dashboard keeps your last-known
  values and shows an honest "unavailable" status instead of $0 with a green "synced" check —
  and it no longer writes that $0 into your performance history (which left a permanent fake
  cliff in the P&L/drawdown charts).
- **Honest about your Claude key.** Saving a key now verifies it actually reaches Anthropic
  before claiming "connected," you can disconnect Claude from the key panel, and the offline
  setup steps point at the one-click panel instead of "edit .env and restart in a terminal."
- **No accidental sales from a typo.** Reducing a holding's share count now asks before booking
  a realized sale, and mid-typing keystrokes no longer book phantom sales.
- **Smaller edges filed down.** First-run/empty portfolios get an "Add your first holding"
  prompt; remove/world-markets/news failures surface clearly instead of silently; stale hero
  tiles clear on an empty portfolio; and Cmd/Ctrl shortcuts no longer double-fire.
- Installing over any 5.2.x keeps everything in place.

## v5.2.1 — DCA, Polished

- **Bulk actions ask first.** "Apply all" and "Skip all" now confirm with the count and dollar
  total, and each plan gets an **Undo applied** action that reverses a whole backfill in one move.
- **Pause means pause.** Resuming a paused plan no longer retroactively books the buys skipped
  while it was paused — it picks up from the resume date.
- **Sharper edges filed down.** Undoing a buy that empties a holding now retires that holding
  (no $0 leftover); an exact-duplicate plan is blocked; same-ticker plans are told apart in the
  bucket; large backfills render lightly; and double-taps can't fire a duplicate action.
- Installing over any 5.2.0 keeps all plans, holdings, and settings (additive schema v3).

## v5.2.0 — Auto-Invest, On Your Terms

- **DCA auto-invest plans, simulated locally.** The most-asked question — "can it sync my
  broker's auto-invest?" — answered the local-first way. Set a ticker, a dollar amount, and a
  cadence (daily / weekly / monthly); each interval books a buy at that day's *real* close into
  a review bucket. Weekends and holidays snap to the next trading day.
- **Nothing moves until you say so.** Every booked buy waits for you to **Apply** it (shares and
  average cost update), **Skip** it, or leave it. Applies are reversible with **Undo**; skips can
  be **Restored**. A past start date backfills the full history, with a double-count guard if you
  already hold the ticker.
- **Catches up after you've been away.** Reopen the app after a week and it fills in every missed
  buy, idempotently — never double-booking. A badge shows how many are waiting.
- Installing over any 5.1.x keeps all holdings, settings, and `.env`. Still no brokerage
  connection; still not financial advice.

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
  never places trades, and has no FolioOrb telemetry or cloud account.

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
