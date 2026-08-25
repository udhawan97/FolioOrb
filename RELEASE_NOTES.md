# FolioOrb v5.15.0 Release Notes

**Release date:** August 25, 2026

## Headline

Review what matters, then keep the receipt. Review Orbit can now separate urgent
data gaps from routine reminders, save a fresh data-health or target-plan
snapshot when you ask for one, and reopen where you left off.

## Added

### Filter the review inbox without losing the whole picture

- The Inbox now has four live filters: **All**, **Data gaps**, **Needs review**,
  and **On the radar**. Each shows its count before you choose it.
- Filtering changes only what is visible. The Review badge and header keep the
  total count, so a quiet reminder cannot make an urgent gap disappear.
- The selected filter stays on this device and is restored the next time Review
  Orbit opens.

### Save a data-health receipt

- The Data Trust Center can now save an Excel-friendly CSV with generation time,
  overall quality, snapshot coverage, and one row per coverage area.
- Saving performs a fresh read-only coverage check at that moment. The CSV names
  foreign-priced positions separately because they stay outside USD totals.
- Missing tickers, sources, and caveats remain explicit. A partial or unavailable
  area is never rewritten as complete during export.

### Save a current target-course snapshot

- Plan can save a CSV snapshot of the persisted target basis points, current
  allocation, descriptive drift, known USD value, and valuation quality.
- Saving performs a fresh read-only valuation. If target inputs have unsaved
  changes, FolioOrb asks you to save the course before exporting.
- If required quotes are missing or foreign-priced, the file names them and
  leaves drift unavailable. It does not substitute zero, convert currencies, or
  place a trade.

### Return to the same review context

- Review Orbit remembers the last tab, Inbox filter, and Month/Quarter Review
  Pack choice in local browser/app storage.
- Invalid or inaccessible stored values fail back to Inbox, All, and Month.
  Holdings, financial records, and settings are not changed.

## Public surface

- README and website copy, release examples, Review Orbit documentation, and
  current demo screenshots now describe the four shipped workflows.
- The capture pipeline adds a Review Inbox artifact from the repository's
  isolated fictional demo profile; provider-backed market facts are current at
  capture time.

## Under the hood

- The new exports reuse Review Orbit's existing USD-only valuation and planning
  contracts. No provider, FX, brokerage, or portfolio-calculation path was added.
- No schema migration. Installing over the latest published stable, v5.13.0,
  preserves local holdings,
  snapshots, backups, settings, keys, targets, and thesis text.

---

# FolioOrb v5.14.0 Mainline Milestone — Included in v5.15.0

**Mainline milestone:** August 22, 2026 · This version was not published as a
stable tag; its changes ship publicly in v5.15.0.

## Headline

Eight dialogs, one meaning for the word "modal". Every panel that dims the
dashboard behind it now keeps the keyboard inside itself, and gives focus back to
something real when it closes. Two of the dialogs that leaked were the ones asking
you to confirm something you cannot undo.

## Fixed

### A dialog now keeps the keyboard inside it

FolioOrb has eight panels that dim the dashboard and ask you for something: rename
a portfolio, delete one, record a sale, confirm a DCA action, the first-run
welcome, Manage Portfolio, Review Orbit, and Software Update. Each had been given
its own answer to what "modal" means, and the answers had drifted apart. Three of
them stopped the mouse and nothing else, so pressing Tab walked straight out onto
the dashboard behind — which was still fully live.

Measured by walking the real keyboard path on the running dashboard, before and
after:

| Dialog | Tab presses that left the dialog — before | after |
|---|---|---|
| Rename portfolio | 6 of 8 | 0 |
| **Delete portfolio?** | **7 of 8** | 0 |
| **Record a sale** | **2 of 8** | 0 |
| Review Orbit | 1 of 8 | 0 |
| Software Update | 0 of 10, but the dashboard behind it stayed reachable | 0 |
| Manage Portfolio | 0 of 12 | 0 |

- The two in bold are confirmations for things that cannot be undone. On
  **Delete portfolio?** the very first Tab press left the dialog: you could drive
  the whole dashboard — switch portfolio, edit a holding — while a delete
  confirmation still stood open in front of you, and the two could then disagree
  about which portfolio you meant.
- All eight now hold the keyboard until you answer them, and the dashboard behind
  is properly out of reach — for a screen reader and the mouse as well, not just
  for Tab.
- Escape closes any of them, as before. Where a dialog has a step inside it,
  Escape still unwinds one step at a time: in Review Orbit it clears an armed
  restore first, and a restore already running still refuses to be interrupted.

### Closing a dialog no longer loses your place

When a dialog closed, FolioOrb tried to put the keyboard back on the control that
opened it. If that control was gone, nothing happened at all and focus fell to the
very top of the page — so the next Tab press started the whole dashboard again.

- This was not a rare case. Renaming or deleting a portfolio redraws the list that
  held the button you clicked, so by the time the dialog closed the button had
  reliably gone. Both flows lost your place every time; measured, focus landed
  nowhere at all.
- Every dialog now names a landmark to fall back on — the portfolio switcher, the
  Manage Portfolio button, the Review Orbit button — and the return is checked
  rather than assumed, so a dialog can no longer hand focus to something that
  quietly refuses it.
- If you use a mouse you will not notice any of this. If you use the keyboard,
  closing a dialog now puts you next to where you were instead of at the top of
  the page.

### A dialog opened on top of another one is usable

Opening a panel marked everything else on the page as unreachable — correctly, but
that "everything else" included the other dialogs' own markup. A second dialog
opened over the first therefore arrived unreachable: on the first-run welcome
panel, a dialog opened on top could not be focused or typed into at all, while the
panel underneath went on answering the keyboard.

- Dialogs now stack. Opening one on top of another makes the new one reachable,
  hands it the keyboard, and gives the keyboard back to the one underneath when it
  closes.
- The paths that reach two at once are unchanged in every other respect: recording
  a sale from inside Manage Portfolio, and confirming a DCA action, both behave as
  they did.

### A tab strip no longer swallows a keypress

Review Orbit's tab strip keeps one tab reachable at a time, which is normal for a
tab strip — but the containment counted the parked tabs as stops. Its idea of the
last control sat behind the real one, so once per lap around the dialog a Tab
press went nowhere at all: no focus ring anywhere on screen, and a second press
needed to get back in.

- Parked tabs are no longer counted, so the wrap happens on the last control you
  can actually reach and every Tab press lands somewhere visible.
- This one only became visible once a single implementation served all eight
  dialogs; each private copy had the same flaw, and each had only one surface to
  be wrong about.

## Under the hood

- The five behaviours a modal dialog owes the keyboard — containment, an
  unreachable background, Escape, a checked focus return, and stacking — moved out
  of eight private copies into one shared module, `static/js/modal-surface.js`.
  Around 140 lines of duplicated interaction code came out of `dashboard.js`,
  `review-orbit.js`, `updates.js` and `dca-workflow.js`.
- Two of the bugs above were only findable this way. A parked tab counted as a tab
  stop, and `document.body` — which is present, visible, and accepts a focus
  request without doing anything — passed every staleness check the old focus
  return could make. Both were in all eight copies.
- New guards: a sweep that fails the build when a new dialog declares itself modal
  without opting into the shared behaviour, a ban on re-introducing a private
  focus trap, a script load-order check, and 22 runtime tests driving the module
  against a fake DOM. Suite 1527 → 1536 Python tests, 22 → 44 frontend runtime
  tests.
- A test assertion that a newer Pylint flags was rewritten, so the lint job is
  clean again at its usual 10.00/10.

## Upgrading

Nothing to do. No database changes, no settings changes, no change to any number
FolioOrb shows you. This release only changes how dialogs behave once they are
open.

---

# FolioOrb v5.13.0 Release Notes

**Release date:** August 15, 2026

## Headline

Three edges where a value crossed a boundary unchecked. Panels that were hidden
only by fading now leave the keyboard path as well. A stock symbol arriving in a
web address is checked before FolioOrb looks it up. And undoing a DCA buy can
only change a holding in the portfolio that owns the plan.

## Fixed

### Faded-out panels leave the keyboard path

v5.12.0 gave five header panels one closing behaviour. Other surfaces were hidden
a different way — faded to invisible, with clicks switched off — and kept theirs.
Switching off clicks stops a mouse but not the Tab key, so their controls stayed
in the keyboard path while invisible on screen and unannounced by a screen
reader.

- On a freshly loaded dashboard, 14 of 47 keyboard stops were controls of this
  kind: 10 in the closed portfolio manager, 3 in the first-run welcome panel, and
  the collapse pill for an expanded holding. They sit at the end of the tab
  order, so a keyboard user tabbing to the bottom of the page ran out of visible
  controls and kept going with no focus ring anywhere on screen.
- Three more were found while reviewing the fix, and are included: the Senpai orb
  when you have hidden it (a saved setting, so it applied on every load), the
  holdings table while an AI scan runs (its per-row disclosure buttons and the
  header tips), and the loading splash as it fades away (its **Skip** button).
- All of them now leave the tab order while hidden. Opening and closing them
  looks exactly as before; the switch happens after the fade finishes.
- Verified on the running dashboard: a 20-press Tab walk from the top of the page
  now lands on 20 visible, named controls, where the same walk previously reached
  an invisible one. Panels still open and close normally, including with reduced
  motion.

### A junk symbol is refused instead of looked up

FolioOrb has one rule for what a stock symbol may look like: letters, numbers,
`.`, `-` or `^`, up to 10 characters. Adding or importing a holding already
applied it. Reading did not — 2 of the 12 addresses that take a symbol checked
it, and the rest passed whatever arrived straight through to the market-data
provider and into the log.

- An 80-character piece of junk used to come back as an ordinary 200 answer; the
  provider was asked for it by name, and the name was written to the log.
- Every address that takes a symbol now applies the rule first, including the two
  that take a comma-separated list. A symbol that does not fit is refused up
  front. Valid symbols are unchanged, and lower case still works — `aapl` and
  `AAPL` behave identically.
- Nothing the dashboard itself produces can be refused: every stored symbol
  passed the same rule when it was added, so no existing bookmark, deep link or
  saved portfolio stops working.

### Undoing a DCA buy can only touch its own portfolio's holding

Applying a DCA buy has always written to a holding in the plan's own portfolio.
Undoing one did not check: it found the holding by its internal row number alone,
and that number carries no portfolio with it. If it ever pointed at a holding in
a different portfolio, the undo changed that holding's share count — and could
mark it inactive — while reporting an ordinary success.

- The undo now looks the holding up inside the plan's own portfolio, so it can
  only change a position in the book the plan belongs to.
- If no such holding is there, the buy still returns to pending and the message
  says so, instead of claiming a clean undo.
- Nothing in FolioOrb is known to create a plan whose buy points outside its own
  portfolio, so this is very unlikely to have affected your numbers; there was
  simply nothing preventing it. If you keep more than one portfolio and a share
  count ever looked wrong after an undo, it is worth a check.
- What this does and does not change: an undo now always writes to the plan's own
  portfolio. It still finds a buy by that buy's own number, so the fix is about
  where the change lands, not about which buys can be named — and the dashboard
  only ever offers you buys from the portfolio you are in.

## Under the hood

- Two analytics views — conviction gaps and confidence spectrum — now read the
  verdict scan directly instead of calling another endpoint's handler inside the
  app. Same numbers, one less layer.
- Target planning and the rest of the app now ask the same place for "the active
  holdings in this portfolio", so that rule cannot drift between screens.

## Upgrade notes

- No schema migration, no configuration change, no new dependency. Installing
  over v5.12.0 preserves your local data: holdings, realized sales, snapshots,
  DCA history, theses, settings, backups and API keys all stay where they are.

## Notes

- **If you script against the local API:** eight addresses now answer `422` for a
  symbol outside the rule above, where they previously answered `200` —
  `/api/ai/summary/{ticker}`, `/api/ai/move-explanation/{ticker}`,
  `/api/ai/intelligence/{ticker}`, `/api/ai/intelligence/{ticker}/deep`,
  `/api/ai/investment-signal/{ticker}`, `/api/ai/analyst-recommendation/{ticker}`,
  `/api/stocks/price/{ticker}` and `/api/stocks/history/{ticker}`.
  `GET /api/stocks/history/batch?tickers=…` and `GET /api/review/compare?tickers=…`
  now reject the whole request if any symbol in the list is malformed, rather than
  passing the bad element along. `/api/ai/insider-activity/{ticker}` and
  `/api/ai/fundamentals/{ticker}` already rejected malformed symbols; only their
  message text has changed.
- Valid symbols are unaffected on every one of those addresses. This is a minor
  version rather than a major one because the API is loopback-only and serves the
  bundled dashboard, and only input that was already malformed changes behaviour.
- If you set `DEFAULT_HOLDINGS` in `.env`, any entry that does not fit the symbol
  rule is now skipped when a new default portfolio is seeded, instead of being
  planted as a row nothing can price.

---

# FolioOrb v5.12.0 Release Notes

**Release date:** August 13, 2026

## Headline

The dashboard now stays calm at every size: closed header panels leave the
keyboard path, Senpai stops covering phone-width portfolio truth, Review Plan
contains its wide tables, and restore or rehearsal state cannot outlive the
input that created it.

## Fixed

### Header details close completely

- Brand, Claude-key, live-feed, overflow, and cost panels now share one
  disclosure contract. Closing one synchronizes its visual state,
  `aria-expanded`, `aria-hidden`, and `inert` state, so invisible controls are
  not still reachable by Tab.
- Escape closes the active panel and returns keyboard focus to the control that
  opened it. Pointer behavior and the existing visual transitions are unchanged.

### Phone-width content keeps the numbers clear

- Below 576 px, Senpai now occupies a compact row after the dashboard instead
  of a fixed layer over portfolio cards. Automatic commentary shows only the
  activity indicator; the full line expands after an explicit tap.
- Review Orbit's Plan cards can shrink to the 320 px viewport. Wide portfolio
  and target tables keep their own horizontal scroller instead of widening the
  whole sheet.

### Review decisions stay bound to their context

- When restore confirmation is visible, the first Escape cancels only that
  confirmation and returns keyboard focus to its Restore control. A second
  Escape closes Review Orbit.
- Once **Queue restore** is submitted, the confirmation enters a visible busy
  state and cannot falsely imply cancellation while the request is in flight.
  Tabs remain locked during that request. An explicit failure restores Retry
  and Cancel; an interrupted response is reconciled against persisted Backup
  Vault state and remains **Status unknown** rather than claiming cancellation
  if FolioOrb cannot confirm the outcome.
- A buy rehearsal is now tied to the exact holding and cash input that produced
  it. Editing either field replaces the old projection with an explicit
  **Preview outdated** state, and a late or out-of-order response cannot repaint
  stale numbers.

## Under the hood

- Portfolio scoping, valuation, realized-sales math, backup handling, DCA
  workflow state, local exports, and Review Orbit now run through smaller shared
  service/client seams. This is a structural hardening pass: the financial and
  recovery contracts remain unchanged and have dedicated Python and JavaScript
  regression coverage.
- The public docs now describe outbound data accurately: the local database is
  never uploaded, provider requests remain bounded, remote news thumbnails are
  identified, and Anthropic availability checks are separated from the compact
  derived context or sanitized CSV sample sent by prompted Claude features.

## Upgrade notes

Install over v5.11.0 as normal. There is no schema migration. Holdings, realized
sales, snapshots, DCA history, theses, settings, backups, and API keys remain in
the existing local data directory. FolioOrb still does not connect to a
brokerage or place trades.

---

# FolioOrb v5.11.0 Release Notes

**Release date:** August 11, 2026

## Headline

Plan with targets, rehearse a buy, export the records behind your book, and know
whether your local safety net is current — all inside Review Orbit, without
connecting a brokerage or turning incomplete market data into false precision.

## Added

### Plan & Protect in Review Orbit

- **Target weights and drift.** Set integer basis-point targets across every owned,
  active holding in a Portfolio. FolioOrb compares them with current allocation
  only when every required USD quote is usable; otherwise it names the missing or
  foreign-priced rows instead of producing partial drift.
- **All-Portfolios pulse.** See known USD value and completeness for every book,
  plus a known-value total. A quote failure is isolated to its Portfolio; the
  overview does not pretend the total is a complete account-level performance
  measure.
- **Buy rehearsal.** Preview an external-cash USD buy for a ticker you already own.
  It reuses current available quotes and average-cost math, makes no database
  change, never trims, and is neither a forecast nor a recommendation.

### Local records you can inspect

- **Annual realized recap CSV.** One row per stored sale, using its stored date,
  proceeds, and average-cost basis. Totals reconcile to the displayed rounded
  rows. This is a calendar-year record, not a tax filing: it does not model lots,
  fees, holding periods, wash sales, or tax classification.
- **Portable records ZIP.** Export human-readable CSV files for Portfolios,
  holdings (including inactive/watchlist rows, notes, theses, and targets),
  realized trades, snapshots, DCA plans, and DCA contributions, plus a manifest
  with row counts and checksums. The export excludes keys, settings, AI caches,
  backups, and the SQLite database; it is sensitive and is not a restore package.

### A clearer local backup posture

- Review Orbit now grades the newest verified **manual** backup as current (up to
  7 days), due (8–30 days), stale (over 30 days), or missing. Corrupt newer files
  are skipped, and the UI keeps the same-device warning visible.
- Optional launch-time automatic backups are off by default, attempt at most once
  per local day, verify before publication, and retain seven verified `auto-*`
  snapshots. They never prune manual, update-safety, restore-safety, or exported
  backups.

## Under the hood

- Schema v6 adds one nullable `target_weight_bps` field to holdings. Existing
  databases migrate additively and retain all holdings, trades, snapshots, DCA
  history, theses, settings, and keys.
- Backup creation now serializes manual, automatic, verification, and pruning work
  across app processes; uses collision-proof names and private staging files; and
  publishes without replacing an existing destination.
- Portable exports materialize one pinned SQLite transaction, order rows
  deterministically, and reject an archive before download if cumulative
  uncompressed or final compressed output exceeds 64 MiB.
- Frozen release smoke tests now force an isolated data root and database before
  importing app modules, so package verification cannot migrate or create real
  user state. Native record exports stage and fsync a private sibling file before
  atomically replacing the chosen destination; cancellations and write failures
  are reported separately.

## Upgrade notes

Install over v5.10.2 as normal. Target fields begin unset, automatic backup
remains disabled until you opt in, and none of the new planning or export views
mutates shares or places trades.

---

# FolioOrb v5.10.2 Release Notes

**Release date:** August 2, 2026

## Headline

A focused DCA follow-up. Deleting a plan now tells you up front that applied buys
must be undone, and a refused delete shows the ledger's reason instead of looking
like a button that did nothing.

## Fixes

### 🧾 DCA deletion explains the traceability rule

FolioOrb deliberately refuses to delete a DCA plan while it has applied buys so
the holding changes remain traceable. The v5.10.1 dialog incorrectly said those
buys would stay in the holding, then ignored the API conflict that enforced the
rule. The dialog now tells you to undo applied buys first, and any refusal is
shown in-app. Once no applied buys remain, deletion removes pending and skipped
entries as documented.

## Notes

No schema changes and no migration. Installing over v5.10.1 preserves holdings,
trades, snapshots, DCA history, theses, settings, and API keys.

---

# FolioOrb v5.10.1 Release Notes

**Release date:** August 2, 2026

## Headline

A trust-and-flow patch. The local Backup Vault is now genuinely read-only when
you browse or verify it, DCA decisions use accessible in-app dialogs in the
desktop window, and three compact-screen dead ends are gone.

## Fixes

### 💾 Looking at a backup no longer changes it

Opening the Backups tab used normal SQLite connections for integrity and holding
counts. Against a WAL-mode snapshot, SQLite could create `-shm` and `-wal`
companions beside the vault file even though the user had only asked to list it.
Vault inspection now uses an immutable read-only connection, listing an absent
vault does not create its directory, and a non-empty sibling WAL is refused as
an incomplete artifact instead of being silently ignored. Live-database counts
remain WAL-aware, so safety backups still see every committed holding.

Manual snapshots are verified through the same read-only path and remain one
standalone `.db` file.

### 🧾 DCA decisions stay inside the app

Apply all, undo applied, skip all, change amount, and delete plan depended on
browser-native confirm/prompt dialogs. WKWebView can fail to show those dialogs,
turning a click into a silent no-op. Each action now uses one in-app dialog with
plain consequences, inline amount validation, a focus trap, Escape-to-cancel,
and focus restoration to the control that opened it. The DCA ledger and its
apply/undo invariants are unchanged.

### 📱 Holdings reaches the table on a phone

The mobile Holdings toolbar inherited a 320 px desktop flex basis after it
switched to a vertical layout, stretching the header to roughly 386 px at a
375 px viewport and pushing the first row below the fold. The phone layout now
sizes that toolbar from its content.

### 👋 The first-run guide starts where the tour starts

On a 320 × 568 window the welcome guide focused its footer action, which scrolled
the panel more than 300 px down before the user saw it. It now resets to the top
and focuses the close button; its existing Tab trap, Escape behavior, inert
background, and focus return remain intact.

### 🧭 Every Review Orbit destination is visible

The compact tab strip hid Backups beyond a scrollbar-free horizontal overflow.
Phone-width tabs now wrap into a visible second row while retaining tablist,
tabpanel, arrow-key, and focus behavior.

## Notes

No schema changes and no migration. Installing over v5.10.0 preserves holdings,
trades, snapshots, DCA history, theses, settings, and API keys.

---

# FolioOrb v5.10.0 Release Notes

**Release date:** August 1, 2026

## Headline

An architecture pass. **52 endpoints came off the event loop**, so a slow
Claude call or Yahoo fetch no longer freezes the whole dashboard, and a
portfolio-scoping bug that let one portfolio edit another's holdings is closed.

## Fixes

### 🔒 Holdings can only be edited through the portfolio that owns them

`PUT` and `DELETE /api/portfolio/holdings/{id}`, and
`DELETE /api/portfolio/trades/{id}`, looked their row up by id alone. The
browser scopes every request with a `portfolio_id`, but the handlers ignored
it — so with more than one portfolio open, an edit or a delete could land on a
holding belonging to a different book, and the realized-sale it recorded went
into the wrong ledger. All three now resolve through the holdings repository,
which owns the ownership rule, and answer 404 when the holding isn't yours.

### ⚡ A slow endpoint no longer freezes the dashboard

The app runs one server worker, so one event loop. Fifty-two endpoints were
declared `async` while doing blocking work — yfinance fetches, SEC EDGAR calls,
synchronous Claude round-trips, unbounded table scans — and each one held that
loop for its whole duration while every other request queued behind it. The
portfolio switcher's dropdown, which is two indexed local queries, could inherit
a 30-second Claude wait. Those endpoints now run in the worker threadpool.

The guard that was supposed to catch this only listed endpoints by hand and had
never been told about the news router at all; it now sweeps every router and
fails any blocking endpoint by default.

### 📉 A single bad price can no longer blank every weight

If Yahoo returned `NaN` for one holding, the verdict pipeline's position-weight
calculation propagated it: `NaN` is truthy, so it slipped past the guard meant
to catch missing prices, and every holding in the book came back with a `NaN`
weight — into the concentration score and into what Claude was told. Prices now
go through one shared check that rejects `NaN`, infinities, and negatives.

### 🧭 The action plan sees your sectors again

The action-plan snapshot read three keys nobody produced — sector exposure,
country exposure and sector tilt were spelled differently by the code that
built them — so Claude received an empty exposure block on every request and
wrote around the gap. The keys now match, and the tests no longer fake a shape
the real code never emits.

### 🕐 Market hours are answered once

The status badge and the cache-expiry logic each computed "is the market open?"
separately, so they could disagree. One module now answers it.

### 📊 One concentration scale

An HHI of 0.30 was "high" on the action plan and "moderately concentrated" in
the analytics narration — same book, same page, two verdicts. There is now one
banding, shared by both.

## Under the hood

- New seams, each replacing a rule that was written out two or three times:
  `market_hours` (the trading calendar), `ticker` (symbol shape and
  normalisation, dependency-free so the request schemas can share it),
  `returns_math` (log-returns and annualisation, previously duplicated between
  analytics and projection), and `routers/deps` (portfolio resolution).
- The world-markets fan-out and its cache moved out of the stocks router into
  `world_markets`, so startup warmup no longer imports a private function out of
  an HTTP router. It gains request coalescing, and a briefly unreachable Yahoo
  is retried rather than cached as an all-zero strip for five minutes.
- Two response schemas that nothing had ever used are gone.
- `tests/conftest.py` gained shared `db` and `api_client` fixtures, replacing
  the in-memory-database block that had been copy-pasted across thirty files.
- 1393 tests pass (up from 1338); pylint stays at 10.00/10.

## Notes

No schema changes and no migration. Nothing to do on upgrade.

This release also carries the user-flow resilience work prepared as v5.9.3,
which was never cut as its own tag; its notes follow below.

---

# FolioOrb v5.9.3 Release Notes (shipped in v5.10.0)

**Prepared:** August 1, 2026 — folded into v5.10.0 rather than cut
as its own tag.

The Review Orbit, holdings, News, Manage, tooltips, and Analytics flows now hold
up under keyboard use, narrow windows, and transient failures—not just a
pointer on a desktop-sized dashboard.

## Fixes

### 🧭 Review Orbit stays above the whole dashboard

The global body-child stacking rule and sticky navbar could pull the full-screen
workspace behind app chrome, leaving its header obscured and fixed dashboard
utilities visible through it. Review Orbit now keeps its fixed viewport layer,
covers the navbar at phone widths, and suppresses the holding FAB and Senpai
while open. Escape still returns focus to the named Review trigger.

### ⌨️ Holding details are real disclosure controls

Ticker rows now expose native keyboard buttons with `aria-expanded` and
`aria-controls`. Enter and Space both open and close the matching detail row;
collapsed content becomes hidden from assistive technology and focus remains on
the trigger. Holding-intelligence lookups are scoped to the holdings table so
allocation rows with the same ticker cannot receive duplicate detail content.

### 🔁 News failures can recover in place

A transient feed failure no longer marks News as permanently loaded. The empty
state offers **Retry news**, announces progress, and refetches without reloading
the page. A successful retry restores the feed and moves focus to the first
article (or the News tab when there are no links).

### 🎯 Manage returns focus somewhere visible

Opening Manage from the one-time welcome guide used to return focus into that
now-hidden guide on Escape. FolioOrb now validates the opener and falls back to
the always-visible, explicitly named **Manage portfolios** control.

### 🔊 Icon-only help controls have useful names

Shared tooltip setup now names icon-only buttons from their tooltip headings,
including controls added after initial render. Decorative glyphs stay hidden
from assistive technology instead of becoming the button name.

### 📱 Analytics reads as a card, not a word rail

At 320 px the Portfolio Action Plan header now stacks its headline and metadata
instead of squeezing them into a narrow vertical strip. The compact layout has
no page-wide horizontal overflow.

## Notes

No portfolio math, trade behavior, schema, or migration changed. Installing over
5.9.2 preserves holdings, trades, snapshots, DCA history, theses, settings, and
API keys.

---

# FolioOrb v5.9.2 Release Notes

**Release date:** July 29, 2026

## Headline

Closes the known gap left open by 5.9.1: a cold load fetched three endpoints
twice. It now issues **26 requests across 26 endpoints — no duplicates.**

## Fixes

### 🔁 No duplicate requests on a cold load

A browser trace of a warm start measured 29 requests across 26 endpoints. Three
different causes, so three different fixes:

- **Sparkline history** — `renderPortfolioValueData` runs twice by design, once
  off the cached payload for the instant paint and again when the live fetch
  lands. Each pass requested trend history. It now goes through the shared
  endpoint cache, so the two renders share one request; a refresh drops the
  entry first, so the bars still update.
- **Benchmark comparison** — the pane loader and the post-render pass both asked
  for it. Moved off a raw `fetch` onto the same shared cache, with the refresh
  path invalidating it.
- **Analytics insights** — the dashboard re-applies the intelligence mode when
  the Claude heartbeat resolves, about six seconds after startup already applied
  the same mode. Too far apart to share a request, so the guard is on the
  handler: `onIntelligenceModeChanged` now returns early when the mode has not
  actually changed. A genuine switch still clears caches and refetches.

### 💸 One Claude call per payload, not two

While verifying the above, the AI insights loader turned out to have two callers
that can fire together on a switch into Claude mode, and — unlike its local
sibling — no in-flight guard. That meant one payload could cost two billed Claude
calls. It now has the same guard.

## Notes

No feature changes, no schema changes, nothing moves a position. Installing over
5.9.1 preserves all existing data and keys.

---

# FolioOrb v5.9.1 Release Notes

**Release date:** July 29, 2026

## Headline

A userflow audit of the first-run, add-holding, dashboard, and Review Orbit journeys —
run against a real browser rather than the source — turned up four fixable gaps. This
release closes them. No feature changes; nothing moves a position.

## Fixes

### ⌨️ The welcome guide is now a real modal

The first-run guide painted a full-viewport layer that blocked the mouse but left the
whole dashboard behind it in the tab order — its own buttons were the 93rd tab stop, and
focus never entered the dialog. It now does what Review Orbit and the portfolio manager
already did: marks the background `inert`, sets `aria-modal="true"`, moves focus to
**Add your first holding** on open, traps Tab in both directions, and returns focus to
where it came from on close. Escape and the one-time dismissal are unchanged.

### 💬 Senpai stops standing on the numbers

On desktop the quip bubble was pinned open bottom-right, permanently covering whatever
occupied that corner — at 1440×900 that was the per-holding dollar column of Today's
impact and part of the world-markets strip. The bubble now settles back to the orb about
nine seconds after it speaks, the way it already did on mobile. New quips still open it,
and clicking the orb brings the last line back; a second click hides Senpai as before.

### 🔤 Ticker validation works again

`pattern="[A-Za-z0-9.^-]{1,10}"` on the ticker field is not a valid regular expression
under the `v` flag browsers now use, so every page load logged a console error and the
attribute was dropped wholesale — taking the client-side character check with it. The
dash is now escaped. Tickers with dashes and carets (`BRK-B`, `^GSPC`) still validate;
junk no longer does. The JS and Python checks were always in place, so no bad data could
reach the database either way.

### 🔊 Add-holding errors are announced

The add-holding message is now a polite live region and is wired to the ticker field with
`aria-describedby`, so screen-reader users hear the specific error instead of only seeing
focus move.

## Known gap

A cold load still fetches three endpoints twice — `benchmark-comparison`,
`analytics-insights`, and the multi-ticker `history/batch`. It is real and measured
(29 requests, 26 distinct) but tracing the two initialisation paths safely did not fit
this release, and a rushed change to the data-loading path was not worth the risk. It is
queued for the next one.

---

# FolioOrb v5.9.0 Release Notes

**Release date:** July 27, 2026

## Headline

FolioOrb now has a review ritual, not just a dashboard. Review Orbit brings attention,
coverage, reports, research comparison, thesis cadence, and verified local recovery into
one workspace—without connecting a brokerage, inventing missing numbers, or moving a
position on your behalf.

## What's New

### 🧭 One Review Orbit

A new **Review** control opens a keyboard-accessible workspace with five connected views:
Inbox, Trust, Review Pack, Compare, and Backups. It traps focus, closes with Escape, returns
focus to its opener, fits narrow windows, and respects reduced motion.

The Inbox prioritizes unusable prices, simulated DCA buys awaiting approval, upcoming
earnings, verdicts still collecting calibration history, and thesis reviews. It is an
attention list, not an automation queue: nothing places a trade or changes a holding.

### 🛡️ Coverage before confidence

The Data Trust Center reports coverage and sources for position prices, quote metadata,
fund fees, dividend classification, top-holdings ETF overlap, local theses, and stored daily
history. Missing or implausible provider fields stay missing, and top-10 overlap remains
explicitly labeled as a floor rather than full-fund duplication.

### 💾 A verified Local Backup Vault

Create and verify SQLite snapshots while FolioOrb is running, inspect holding counts and
timestamps, and export a backup through a real Save dialog in the desktop app. API keys and
`.env` are excluded from manual vault snapshots.

A restore never swaps the live database underneath an open app. FolioOrb verifies the chosen
snapshot, queues it for the next clean start, takes and verifies a fresh safety copy of the
current database, then stages and re-verifies the replacement before the swap. A failed
restore leaves the live database untouched.

### 📝 Monthly and quarterly review packs

Build a local report from current valuation, stored snapshots, realized trades, the largest
current P&L contributors, and theses needing attention. Save the result as print-ready HTML
or CSV. Value change is deliberately labeled as cash-flow affected—not a time-weighted
investment return—and names the exact stored opening snapshot used.

### ⏱️ Thesis cadence

Theses can now be marked reviewed and placed on a 30-, 60-, 90-, 180-, or 365-day cadence
(or left uncadenced). Missing, due-soon, and overdue theses return to the Review Inbox. The
review timestamp and cadence are local workflow metadata only; they never change valuation
or verdict math, and Claude still never reads or writes the thesis.

### ⚖️ Type-aware Watchlist Compare

Select two or three research-mode stocks for a side-by-side fundamentals read, or two or
three ETFs for fund-specific fields, concentration, and published top-holdings overlap.
Owned positions cannot be smuggled into the research comparison, and mixed stock/ETF
selections are rejected rather than flattened into misleading common metrics.

## Under the hood

`portfolio_review.py` composes the existing valuation, fee, income, overlap, calibration,
and market-data interfaces rather than duplicating their financial math. `/api/review`
provides Portfolio-scoped endpoints, while `review-orbit.js` owns the single UI workspace.

Schema v5 adds two optional holding columns: `thesis_reviewed_at` and
`thesis_review_interval_days`. The migration is additive and runs through FolioOrb's existing
backup-first migration gate. Installing over v5.8.0 preserves holdings, trades, snapshots,
DCA history, thesis text, settings, and API keys.

---

# FolioOrb v5.8.0 Release Notes

**Release date:** July 21, 2026

## Headline

FolioOrb now comes back exactly where you left it, starts with less waiting, and keeps
research ideas rigorously separate from money you actually own. The portfolio manager is
also a real keyboard-accessible modal, and the complete workspace now fits a 320-pixel
screen without a sideways page scroll.

## What's New

### 🧭 Your workspace remembers

Light or dark mode and the last dashboard zone now survive a refresh, relaunch, or portfolio
switch. The saved theme is applied before the first paint, so a light-mode workspace no
longer flashes dark while the JavaScript catches up.

### ⚡ A calmer cold start

Bootstrap, icons, and chart libraries now ship inside the app instead of waiting on six CDN
round trips. Portfolio names and the world-markets strip paint from local cache while fresh
data arrives. If a cold start still has nothing truthful to show, a short compounding-curve
splash names the real work in progress; warm loads go straight to the dashboard.

### 🔬 Research means research

A research-only ticker is an idea, not a position. It no longer becomes the Overview's
largest holding, a mover in the portfolio briefing, or an Add / Trim / Exit action. If every
ticker is research-only, FolioOrb says there are no invested positions and explains how to
turn an idea into one by adding shares.

Growth projections follow the same contract. A research-only portfolio no longer invents a
$100,000 starting balance: the personalized scenario cards stay hidden and the chart shows
only the S&P 500 as an index, explicitly labeled **100 = start**.

### ♿ Manage Portfolio behaves like a modal

Opening the manager now moves focus into it, keeps Tab and Shift+Tab inside, marks the
background inert, closes on Escape, prevents background scrolling, and returns focus to the
exact control that opened it.

### 📱 The whole workspace fits narrow screens

At 320–375 pixels, the app bar keeps the portfolio switcher, Manage, and More controls usable
without pushing the page sideways. Status and update affordances remain available inside the
More menu, the API-key and portfolio menus are viewport-bound, zone tabs shrink cleanly, and
wide holdings data keeps its own horizontal scroller instead of widening the document.

## Under the hood

Shared cache misses now collapse into one fetch, blocking routes run off the event loop, DCA
pricing is skipped when no installment is due, and startup no longer repeats a one-time repair.
Eight backend/frontend seams were deepened so lifecycle, valuation, narratives, settings, and
shared market data each have one clearer owner.

The research-only rules are now enforced in the shared action-plan, briefing, valuation, and
projection services with router and rendered-UI regression coverage. Installing over v5.7.0
keeps the existing database, holdings, trades, DCA history, thesis notes, settings, and API
key. No schema migration is required.

---

# FolioOrb v5.7.0 Release Notes

**Release date:** July 18, 2026

## Headline

Two things the market can't tell you: *why* you bought something, and *when* it
pays you. This release adds both — your own thesis on every holding, and a
month-by-month calendar of the income your portfolio is due.

## What's New

### 📓 Your thesis, on every holding

Every expanded holding now has a **Your thesis** box: the reason you own the
thing, in your own words. Write it when conviction is cheap and easy to
articulate; read it back mid-drawdown, when it isn't.

The text is yours alone — Claude never reads or writes it, and it stays in your
local database like everything else. It already round-trips through CSV import
and export, so it survives a move between machines. Editing is inline and safe:
a background refresh can't clobber what you're typing, and a failed save leaves
your words on screen rather than eating them.

### 🗓️ When your dividends actually land

The income card told you how much a year. It now also tells you *which months*.
A twelve-month strip projects each payer's income into the months it actually
pays, so the lumpy reality of dividend timing — three quiet months, then three
payers at once — is visible instead of averaged away.

The schedule comes from each holding's real trailing ex-dates, not an assumed
quarterly rhythm: a monthly payer like a REIT shows twelve bars, a quarterly
payer shows four, in its own months. The amounts come from the same forward
dividend rate the rows above use, so a freshly raised dividend projects at the
new rate on the established schedule.

Two honesty rules carry over from the income view. The months shown are
**ex-dividend months** — the cutoffs to own each payer — and the card says so,
because the cash itself usually lands days to weeks later. And a payer whose
schedule can't be read from history is named as unscheduled rather than smeared
across months that were never observed.

## Under the hood

The dividend calendar's cadence inference is a pure function over injected
ex-date history — no network in the projection path — so it is fully covered by
offline tests. The one outside call reuses the same shape as the existing
history fetches: keyless, day-keyed cache, bounded concurrency, pruned so a
long-running desktop process can't accumulate stale entries. A calendar outage
clears only the strip and leaves the income card itself standing.

Thesis notes required no schema change — the `notes` column has existed since
early versions and was simply never surfaced. Installing over v5.6.0 preserves
the existing database, holdings, trades, DCA history, settings, and API key.

---

# FolioOrb v5.6.0 Release Notes

**Release date:** July 17, 2026

## Headline

FolioOrb now reads a company from the inside out — what its insiders are doing,
what it actually earns, and what it pays you — all from primary sources that are
public, keyless, and free.

## What's New

### 🕵️ Insider activity, straight from Form 4

Expand any stock and see recent open-market buys and sells by the company's own
officers and directors, pulled from SEC Form 4 filings. Only open-market trades
count as conviction: option exercises, grants, gifts, and tax withholding are
shown for completeness but never folded into the buy/sell headline, because they
aren't decisions to buy or sell at the market. Funds and ETFs have no insiders,
so they say so. Every row links to the filing on `sec.gov`.

### 📊 Financials over time

The same expanded view now charts revenue, net margin, and diluted EPS by fiscal
year, from the numbers a company actually filed (SEC XBRL). Revenue bars scale to
the window's own peak so the trend reads at a glance. A metric a company didn't
file shows an em dash, never a fabricated zero, and the revenue history stitches
across the GAAP tag change most large filers made around 2018.

### 💵 What your holdings pay you

A new Analytics card turns each holding's forward dividend rate into annual cash
at your position size, totals it, and shows the blended yield across your payers.
Holdings that pay nothing are named, never counted as $0 income. Each payer shows
its yield and an ex-dividend heads-up when a payment's cutoff date is near.

### 🏷️ Filings in plain English

The filings timeline now labels each 8-K by what it reports — "Results announced,"
"Officer or director change," "Shareholder vote" — instead of raw item codes.

## Fixed

### 🛡️ Dividend yields read 100× too high for low-yield stocks

Same class of bug as the v5.5.0 expense-ratio fix. yfinance reports dividend yield
in two fields with units 100× apart — `dividendYield` is a percent, the trailing
field a fraction — while everything downstream expected a fraction, so a sub-1%
yield rendered 100× too high (Apple showed a 32% dividend yield). Yield is now
normalized once, preferring the unambiguous rate-over-price, so Apple reads 0.32%.

## Under the hood

The SEC EDGAR client gained a throttled company-facts fetch (XBRL financials) and a
document fetch (Form 4), both behind the same contact-address and 10-requests-a-second
rules as the filings timeline. Every new outside call is still keyless and public;
`FOLIO_SEC_CONTACT` continues to let you speak for yourself. No schema migration is
required, and installing over v5.5.0 preserves the existing database, holdings, trades,
DCA history, settings, and API key.

---

# FolioOrb v5.5.0 Release Notes

**Release date:** July 17, 2026

## Headline

FolioOrb now reads the primary sources directly: what your companies filed with
the SEC, what the Treasury says the yield curve is doing, and what your funds
actually charge you. All of it public, keyless, and free — no account, no key,
no middleman.

## What's New

### 🗂️ Straight from the filings

The News tab now shows what your companies told the SEC — material events (8-K),
quarterly and annual reports (10-Q, 10-K), and proxy statements — pulled straight
from EDGAR and linked to the source document. A filing from the last few days
also shows up as a possible catalyst in that holding's move explanation.

Only operating companies file with the SEC. Funds, crypto, and most foreign
listings have no filing record at all, so they are named as non-filers rather
than displayed as companies that happened to file nothing. No Claude key is
needed; filings work the same on Local Intelligence.

### 📐 The curve, and where fear actually sits

The market backdrop now reads the US Treasury par yield curve — the 2s10s and
3m10y spreads, published every business day — and reports where the VIX sits in
its own five-year range, which says more than the number alone.

An inverted curve is the bond market pricing cuts ahead, and it is one of the few
signals allowed to shift verdict weights toward quality and away from momentum. A
flat, normal, or steep curve is reported and left at that. If the curve cannot be
reached, it says so and the rest of the backdrop carries on.

### 💸 What your funds cost you

A new Exposure card turns each fund's expense ratio into the number that matters:
dollars per year at your position size, and what that compounds to over a decade —
including the growth those fees never got to earn. The long-horizon figure is a
projection under a stated growth assumption, and the assumption is printed next to
it. A fund whose fee cannot be read is listed as fee-unknown, never charged $0.

### 🧬 Whether your ETFs are the same bet

Holding three funds is not diversification if they hold the same companies. A new
card compares each pair of your ETFs across their top 10 published holdings and
shows what they share. It says exactly what it measured: top-10 overlap is a floor,
not the whole book.

### 🎯 Earnings with the bar attached

The earnings radar now carries the consensus EPS estimate for the upcoming report
and how often the company beat that estimate over the last four quarters — so
"reports in 3 days" arrives with the bar it is expected to clear. When there is no
estimate, the date still shows and FolioOrb does not guess.

## Fixed

### 🛡️ Fund fees were reading 100× too high

Yahoo reports expense ratios in two units that are exactly 100× apart, and
FolioOrb used whichever arrived first. The result: an ETF's fee could be scored in
the most expensive tier when it was in fact among the cheapest — a 0.03% index fund
read as "High" cost, quietly dragging its quality score and its verdict. Expense
ratios are now normalized once, at the source, so the fee view, the ETF quality
score, and the dashboard all agree.

## Under the hood

Each outside source now sits behind exactly one module — Yahoo, SEC EDGAR, and the
Treasury curve — so a provider can be swapped, throttled, or degraded in one place
instead of at every call site. The EDGAR client owns the SEC's two hard rules: a
declared contact address and a ceiling of ten requests a second. Filings are fetched
only for a single holding on demand, never for every holding on a dashboard load.

FolioOrb now sends a contact address to the SEC because the SEC requires one. Set
`FOLIO_SEC_CONTACT` in your `.env` to speak for yourself; it goes to the SEC and
nowhere else, and creates no account. No schema migration is required, and
installing over v5.4.2 preserves the existing SQLite database, holdings, trades,
DCA history, settings, and API key.

---

# FolioOrb v5.4.2 Release Notes

**Release date:** July 16, 2026

## Headline

Portfolio math, recurring-investment history, and AI narration now agree on one
honest view of your holdings — even when a quote is missing or a position has
already been sold.

## What's New

### 📐 Total return now counts every invested dollar

Portfolio total-return percentage now uses both the cost basis still invested
and the cost basis of shares already sold. Realized and unrealized gains were
already combined; their denominator now matches, so partially sold positions no
longer make the percentage look larger than it really is.

### 🛡️ Missing prices stay missing

Zero, non-finite, and malformed quotes are treated as unavailable instead of a
real $0 price. An incomplete valuation cannot write a daily performance snapshot
or ask Claude to narrate a portfolio briefing, analytics read, or action plan as
though every position were priced. FolioOrb identifies the missing tickers and
waits for complete market data.

### 🔁 DCA history remains reversible

A DCA plan with applied buys can no longer be deleted while its holding changes
remain in place. Undo those buys first, then delete the plan, preserving the
audit trail and keeping the ledger aligned with the holding.

### ✨ A sharper public home

The landing page and documentation now share a more deliberate type system and
visual rhythm. The architecture page also documents the financial integrity
modules that keep lifecycle, valuation, DCA, and narrative-cache rules coherent.

## Under the hood

Portfolio lifecycle, valuation, DCA persistence, and AI narrative caching now
sit behind four focused service interfaces instead of being duplicated across
routers. Portfolio deletion includes verdict history and scoped narratives;
ticker and portfolio narratives share the same freshness and serialization
rules. No schema migration is required, and installing over v5.4.1 preserves the
existing SQLite database, holdings, trades, DCA history, settings, and API key.

---

# FolioOrb v5.4.1 Release Notes

**Release date:** July 11, 2026

## Headline

The last thing that wasn't per-portfolio now is: your verdict track record. The
Signals "how did my past calls age?" report card and the calibration stats are
scoped to the portfolio you're viewing, instead of mixing calls across all of
them.

## What's New

### 🎯 Verdict history is per-portfolio

Each portfolio now keeps its own record of the Add / Trim / Hold calls made for
it. Open the Signals tab in your IRA and you'll see how *its* calls aged — not a
blend of every portfolio's. New verdicts are tagged with the portfolio they were
logged for; verdicts recorded before this update are kept and attributed to your
default portfolio.

## Under the hood

Adds the additive `verdict_snapshots.portfolio_id` column (schema v4, backup-first
migration, existing rows backfilled to portfolio 1) and threads `portfolio_id`
through the verdict log, calibration buckets, and the `verdict-report` /
`verdict-calibration` endpoints. Installing over any 5.4.0 keeps everything in
place; new test proves no cross-portfolio verdict bleed.

---

# FolioOrb v5.4.0 Release Notes

**Release date:** July 11, 2026

## Headline

Multiple portfolios. Give your taxable account, your IRA, and your fun-money
experiments their own separate scoreboards — each with its own holdings, P&L,
analytics, DCA plans, and AI narratives.

## What's New

### 🗂️ More than one portfolio

A portfolio switcher now lives in the top bar. Create as many portfolios as you
like, rename them, delete the ones you're done with, and switch between them in a
click — the whole dashboard (value, P&L, holdings, every analytics chart, news,
DCA plans, and the AI briefings/action-plans) re-scopes to the one you're
viewing. The Manage panel names the portfolio you're editing so there's never any
doubt which book a change lands in.

Everything stays cleanly separated: each portfolio's data is its own, and — the
part that's easy to get wrong — the AI's cached briefings and action plans are
namespaced per portfolio, so switching never shows you another portfolio's
narrative. Your first portfolio ("My Portfolio") is always there and can't be
deleted; new ones start empty with a friendly "add your first holding" prompt.

## Under the hood

The frontend scopes every portfolio API call through a single chokepoint (so no
panel can leak the wrong portfolio's data), the AI router and analytics snapshot
take a `portfolio_id` throughout, and the portfolio-level AI cache is keyed
`BOOK:<id>`. New create/rename/delete endpoints delete every child row
explicitly (holdings, trades, snapshots, DCA plans + contributions, and the
portfolio's AI cache). Installing over any 5.3.x keeps your existing holdings as
the default portfolio. New tests for portfolio management and AI scoping; still
no brokerage connection and still not financial advice.

---

# FolioOrb v5.3.1 Release Notes

**Release date:** July 11, 2026

## Headline

Two of the gaps flagged in v5.3.0, closed: realized sales can now record the
*actual* price and date you sold at, and external links finally work in the
desktop app.

## What's New

### 💵 Record a sale at the real price and date

When you reduce a holding, the "record a sale" step now lets you enter the
**actual sale price** and **sale date** — pre-filled with today's market price
and today's date, but yours to change. Sold NVDA last month at $120? Enter it,
and the realized P&L and the year-end recap book it correctly, in the right tax
year — instead of always assuming today's price and today's date. Leave the
price blank to use the live market price, exactly as before.

### 🖥️ External links work in the desktop app

In the desktop window, links like **console.anthropic.com** (to grab a Claude
key) or the docs used to open a dead, chrome-less frame — or nothing. They now
open in your real browser. (In the web app they always worked; unchanged there.)

## Under the hood

`_record_reduction` takes an optional sale price/date; a new native `open_url`
bridge routes external links to the system browser. Static-asset cache-busters
were bumped so the fixes actually reach you on update. New tests for the sale
price/date path. Installing over any 5.3.0 keeps everything in place.

---

# FolioOrb v5.3.0 Release Notes

**Release date:** July 11, 2026

## Headline

A resilience-and-honesty pass across the whole app: when the internet drops or a
key is wrong, FolioOrb now tells you the truth instead of quietly showing $0,
corrupting your history, or dead-ending — and a few sharp edges got filed down.

## What's New

### 🛡️ Never a scary $0 on a bad connection

If market data can't be reached, the dashboard used to show **$0.00 with a green
"synced" checkmark** — and, worse, it wrote that $0 into your performance history,
leaving a permanent fake cliff in the P&L and drawdown charts. Now an unreachable
data provider is detected: the app keeps your **last-known values**, shows an
honest "market data unavailable" status, and **does not** persist a bogus $0 day.

### 🔑 Honest about your Claude key

Saving an API key now actually checks it can reach Anthropic before saying
"connected." A revoked or mistyped (but well-formed) key is saved with a clear
"couldn't reach Anthropic — double-check it" message instead of a false all-clear.
You can also **disconnect Claude** right from the key panel now, dropping back to
Local Intelligence without hunting down a file. And the offline setup steps point
you at the one-click key panel — no more "edit .env and restart in a terminal,"
which a desktop user can't do anyway.

### ✋ No more accidental "sales" from a typo

Correcting a holding's share count (e.g. fixing a fat-fingered 100 → 10) used to
silently book a "sale" of the difference into your realized P&L. Now reducing
shares asks first — "records a sale of N at today's price; correcting a typo?
Cancel" — and mid-typing keystrokes no longer book phantom sales.

### ✨ Smaller sharp edges, filed down

- A brand-new (or emptied) portfolio shows a friendly **"Add your first holding"**
  prompt instead of a blank table.
- Removing a holding, a stuck world-markets strip, and a failed news load now
  fail **loudly and clearly** instead of silently.
- Best/worst/largest tiles clear when the portfolio empties (no stale winner next
  to a $0 total).
- Browser/OS shortcuts (Cmd/Ctrl+R, etc.) no longer double-fire app shortcuts, and
  Escape now dismisses the welcome guide.

## Under the hood

The valuation endpoint reports a `degraded` flag (detected without an extra quote
fetch) and skips the snapshot write when quotes are down; the key-config endpoint
verifies reachability and gained a `DELETE` to disconnect. New tests cover the
degraded path and the key flow. Installing over any 5.2.x keeps everything in
place; still no brokerage connection and still not financial advice.

---

# FolioOrb v5.2.1 Release Notes

**Release date:** July 11, 2026

## Headline

A same-day polish pass on the new DCA plans: the bulk actions are now safe by
default, "undo" cleans up after itself, and pausing a plan finally does exactly
what it says.

## What's New

### 🛡️ Bulk actions that ask first — and undo in bulk

"Apply all" and "Skip all" now confirm before they touch anything, showing the
count and dollar total ("Apply all 12 VOO buys — $600 into your holding?"). And
applying a whole backfill is now reversible in one move: each plan gets an
**Undo applied** action that rolls every applied buy back at once.

### ⏸️ Pause means pause

Pausing a plan and resuming it later no longer retroactively books the buys you
skipped while it was paused. Resuming picks up from the day you resume — the
paused stretch stays skipped, as you'd expect.

### ✨ Smaller sharp edges, filed down

- Undoing a buy that empties a holding now retires that holding instead of
  leaving a $0 placeholder behind.
- Creating an exact-duplicate plan (same ticker, cadence, and amount) is blocked
  with a clear message, so you can't accidentally double-book — different amounts
  or cadences are still fine.
- Two plans on the same ticker are now told apart in the review bucket
  ("VOO · $50 weekly").
- A large backfill renders lightly (with a "…and N more — use Apply all" note),
  and a double-tap can no longer fire a duplicate action.

## Under the hood

Adds the additive `dca_plans.catchup_floor` column (schema v3, backup-first
migration) plus a bulk-undo endpoint. Installing over any 5.2.0 keeps every
plan, holding, and setting in place. Seven new tests; still no brokerage
connection and still not financial advice.

---

# FolioOrb v5.2.0 Release Notes

**Release date:** July 11, 2026

## Headline

v5.2.0 answers the most-asked question — *"can it sync my Robinhood/Fidelity
auto-invest?"* — the local-first way: it doesn't connect to your broker, it
**mirrors** the recurring buy on your own machine, and never touches your
holdings until you say so.

## What's New

### 🔁 DCA auto-invest plans, simulated locally

Set a plan once — a ticker, a dollar amount, and a cadence (daily, weekly, or
monthly) — and FolioOrb does what your broker's auto-invest does, but on-device.
Each interval it books a buy priced at that day's **real closing price**
(weekends and holidays snap to the next trading day, just like a real fill) into
a *pending review bucket*. Nothing changes in your portfolio until you review it.

For every booked buy you choose: **Apply** it (your holding's shares and average
cost update), **Skip** it, or leave it for later. Every Apply is fully
reversible with **Undo**, and a skipped buy can be **Restored**. Set a start date
in the past and it backfills the whole history from real closes — with a
double-count guard if you already hold that ticker.

Because the app isn't always running, it *catches up* on open: reopen after a
week away and it fills in every buy you missed, idempotently — never
double-booking an interval. A badge on the DCA button tells you how many buys
are waiting.

## Under the hood

New local endpoints under `/api/dca` (plan CRUD, catch-up, apply/skip/undo/
restore, bulk apply/skip) backed by two new tables (`dca_plans`,
`dca_contributions`) added additively as schema v2 — the backup-first migration
path means installing over any 5.1.x keeps every holding, setting, and `.env` in
place. The date/price/cost engine is a pure, fully-tested module; historical
closes come from the same yfinance layer the rest of the app uses. 40 new tests;
still no brokerage connection and still not financial advice.

---

# FolioOrb v5.1.0 Release Notes

**Release date:** July 11, 2026

## Headline

v5.1.0 adds two honest ways to look *backward*: a year-by-year recap of the gains
you actually locked in, and a report card that grades FolioOrb's own past calls
by how they've since aged.

## What's New

### 🧮 Year-end realized recap

The Realized gains tab (Analytics → Performance) now opens with a recap of your
closed trades, bucketed by calendar year. Pick a year and see the realized P&L and
return, how many sales and tickers it covered, your winners-vs-losers count, and
the single best and worst position of the year. It reads *every* stored trade —
not just the last hundred — straight from your local database, no live quotes
needed. Tax season, with slightly less dread.

### 🧾 A verdict report card

The Signals tab (Analytics) gets an honest look in the mirror: FolioOrb grades its
own past Add / Trim / Hold calls by how the holding has actually done *since* the
call. An Add that rose counts; a Trim that fell counts; a Hold that stayed within
±10% counts. You get an overall "aged well" rate, a per-action breakdown, and a
ledger of recent calls with their return-since and a ✓ or ✗. Calls need a few days
to mature before they're graded, and it's a look-back, not a forward bet — small
samples are noisy, and none of it is financial advice.

## Under the hood

Both features are new local endpoints (`/api/portfolio/realized-summary`,
`/api/ai/verdict-report`) with dedicated tests. The verdict card prices its tickers
through the shared cached-quote layer with a hard latency cap, so it can never stall
a refresh. Nothing about your data or configuration changes — installing over any
5.0.x keeps everything in place.

---

# FolioOrb v5.0.0 Release Notes

**Release date:** July 9, 2026

## ✦ FolioOrb

> *Local-first portfolio intelligence in a native desktop app, with calmer
> updates, clearer docs, and a cleaner home for the project.*

The product, the app window, the installers, the docs, and the repository are
now **FolioOrb**. The project lives at
[github.com/udhawan97/FolioOrb](https://github.com/udhawan97/FolioOrb) and the
website at [udhawan97.github.io/FolioOrb](https://udhawan97.github.io/FolioOrb/).
The in-app engine voice ("FolioOrb Intelligence") is now "FolioOrb
Intelligence".

**Data stays local.** FolioOrb stores its database, settings, update history,
and logs in the normal per-user data directory for your platform.

**Download assets and docs now use the FolioOrb name** —
`FolioOrb-macOS-arm64-v5.0.0.dmg` and `FolioOrb-Windows-x64-v5.0.0-Setup.exe`.

FolioOrb remains local-first, Claude-optional, and never places trades. It has
no telemetry or FolioOrb-hosted account; bounded provider requests and optional
Claude paths are documented in the current Privacy guide.

## Upgrade Notes

- **In-app update (macOS):** because the macOS app bundle is renamed
  (`FolioOrb.app` → `FolioOrb.app`), an existing install may report the
  in-app swap as "couldn't install" for this one release and leave your old app
  in place — your data is never at risk. If that happens, download
  `FolioOrb-macOS-arm64-v5.0.0.dmg` once from the releases page; your portfolio
  migrates automatically on first launch. Future updates swap seamlessly again.
- **In-app update (Windows):** upgrades in place; the installer keeps the same
  application id so your existing install is recognized.
- **From source:** `git pull` continues to work; your local `.env` and
  `database/` are untouched.

---

# FolioOrb v4.5.2 Release Notes

**Release date:** July 9, 2026

## Headline

v4.5.2 is a **reliability patch** — no new features, just a full-codebase bug
audit and the fixes it surfaced. The theme: your numbers stay honest and your
data stays safe, even when the market data feeding them doesn't.

## Fixes

### Analytics & verdicts — no more silently-wrong numbers

- **A bad price no longer poisons your risk math.** A zero or negative close from
  the data feed (a halted or delisted ticker, a data glitch) used to turn a
  logarithmic return into `-inf`/`NaN` and quietly contaminate annualized return,
  volatility, and correlation for the whole portfolio. Those bad days are now
  treated as flat, in both the risk analytics and the growth projection.
- **Correlation tells the truth when it can't compute.** A frozen or zero-variance
  price series makes correlation mathematically undefined; the matrix used to
  paper over that with a fake `0.0`. It now reports "no data" honestly instead.
- **Trim verdicts score the right way round.** The valuation confidence for a
  *trim* was using the *add* scale, so a cheap ("Bargain") stock could be handed
  a high-confidence trim. Trim now scores the mirror image — low confidence to
  trim something cheap, high to trim something rich.
- **Action Plan cache no longer confuses two different books.** Two portfolios
  with the same dominant verdict but a different secondary lean (e.g. "mostly
  hold, then add" vs "mostly hold, then trim") could share one cached plan. The
  cache key now accounts for the secondary action.

### Your data & the updater

- **A failed restore can never leave you with no database.** Rolling back now
  copies the backup to a staging file and re-verifies it *before* moving your
  live database aside — so an interrupted or out-of-space restore leaves your
  current data exactly where it was instead of half-swapped.
- **Honest rollback messaging.** If your data restores but the saved settings
  (`.env`) don't, you're told exactly that, instead of a misleading "nothing
  happened."
- **Watchlist edits never fabricate P&L.** Reducing shares on a research-mode
  (watchlist) holding no longer records a phantom realized trade — matching how
  deleting one already behaved.
- Unverified partial downloads are cleaned up on error, and a long-running
  desktop session no longer accumulates dead price-cache entries.

### Hardening

- The batch price-history endpoint validates its `period` like the single-ticker
  one does; an out-of-range value is rejected cleanly instead of quietly
  returning nothing.
- The in-app release-notes link is scheme-checked before it's used, and a
  rejected ticker is sanitized before it reaches the logs.

## Upgrade Notes

No database migration or `.env` change required. Update in-app from **Settings →
Software Update**, or download the installer from the releases page.

---

# FolioOrb v4.5.1 Release Notes

**Release date:** July 9, 2026

## Headline

v4.5.1 is a **polish patch** on the spreadsheet release: CSV export and the
import template now hand you a real file in the desktop app, instead of opening
as a wall of text with no way back.

## What's Fixed

### 📥 Export & template actually download in the desktop app

The packaged app is a native window, not a browser tab — and it has no download
chrome. So clicking **Export CSV** or **Download template** used to *navigate* to
the file and render it inline as raw text: no Save dialog, no download, no back
button. Both now route through a native **Save As…** dialog and write an actual
`.csv` (UTF-8 with the byte-order mark Excel likes). In a regular browser,
downloads work exactly as they always did. Either way you get a file, not a dead end.

## Also in this release

- **Website polish** — Senpai now gets his own animated spotlight above the
  footer, a refreshed one-liner pill, and CSV import is called out directly in
  the workflow walkthrough.

Nothing about your data, holdings, or configuration changes in this update.
Installing over v4.5.0 or earlier keeps everything in place.

---

# FolioOrb v4.5.0 Release Notes

**Release date:** July 9, 2026

## Headline

v4.5.0 is the **spreadsheet release**: your holdings move in and out as CSV, so
setting up FolioOrb no longer means retyping thirty tickers by hand — and
neither does backing them up.

## What's New

### 📤 Export your holdings as CSV

One click in the portfolio manager downloads your active holdings as a clean,
tidy CSV — positions and watchlist alike. It's UTF-8 with the columns Excel
expects, and every cell is escaped against spreadsheet formula injection. The
file you get *is* the import template, so it round-trips straight back in.

### 📥 Import holdings — two ways, one set of rules

- **Local (always available, no API key):** a strict, exact-schema parse of the
  template. Deterministic, free, offline. This is the default and it is never
  gated.
- **Claude assist (when a key is configured):** drop in almost any brokerage
  export — `Symbol`/`Qty`/`Cost`-style columns and currency symbols and all —
  and Claude maps the columns onto the FolioOrb format for you. Every mapped
  row still passes the *same* strict validation before it touches your book, and
  clean template files skip Claude entirely (zero tokens). If Claude is slow or
  unavailable, the import quietly falls back to the strict local parse and tells
  you it did — it never fails just because Claude did.

Either way you get a per-row report — added, skipped (duplicates are skipped,
never overwritten), or errored with a plain-English reason — plus, in Claude
mode, a short Senpai-narrated recap. The portfolio manager shows which mode
you're in and updates live when you connect or disconnect a key.

### Safety, as usual

Formula-injection escaping on export, a 256 KB / 200-row import cap, content-type
and encoding checks (UTF-8 BOM and Windows `cp1252` both welcome), ticker
shape-validation before any network call, duplicate-column and non-finite-number
rejection, and Claude only ever sees a small, capped sample of the file — never
the whole thing.

## Upgrade Notes

No database migration or `.env` change required. Existing holdings are untouched;
importing a file you exported earlier is a safe no-op (every row dup-skips).

---

# FolioOrb v4.4.1 Release Notes

**Release date:** July 9, 2026

---

## ✦ Fixed: the updater showing "You're offline" while online

The `v4.4.1` desktop app shipped with a bug in the very feature this release
introduces: the packaged macOS and Windows apps reported **"You're offline"**
when checking for updates, even on a fully connected machine. Root cause: the
frozen app's bundled OpenSSL pointed at a build-machine certificate path that
doesn't exist on a user's computer, so every HTTPS request to GitHub failed
certificate verification — and that failure was generically caught as
"offline" instead of being told apart from a real network outage.

This is fixed in the `v4.4.1` assets as published (the release was re-built and
re-published with the fix before wide distribution — if you downloaded before
today, grab it again from the same link, the version number is unchanged):

- **The real fix**: the update checker now verifies HTTPS against certifi's CA
  bundle, which ships inside the app. This is the actual root cause fix, not a
  copy change.
- **Failures are told apart, not lumped together**: "You're offline" is now
  reserved for a genuine network outage. A certificate problem says *"Couldn't
  securely check for updates,"* a GitHub rate limit says *"GitHub rate limit
  reached,"* and a malformed response or server hiccup gets its own message —
  each is also logged with a sanitized diagnostic reason for support.
- **A real in-app update on macOS.** Clicking **Update Now** no longer just
  opens the DMG for you to drag manually — the app downloads it, verifies its
  checksum (and signature, once minisign is enabled), backs up your data,
  quits, swaps in the new version, and relaunches itself automatically.
  Windows keeps its existing one-click silent install. Your portfolio database
  and `.env` live outside the app bundle entirely, so nothing in this flow can
  touch them, and a failed swap safely falls back to your current version with
  a clear "your data is safe" message.

---

## ✦ Software Update, done right

> *v4.4.1 adds a professional, consent-first update system. FolioOrb can now tell you when a new version is out, download and install it with your permission, and — most importantly — protect your holdings across every update, with a real way back if anything goes wrong.*

**Nothing updates without your say-so.** The app checks quietly for new versions (about 30 seconds after launch, then daily — you can turn this off) and, when one is available, shows a single calm indicator. Opening it reveals a Software Update sheet modelled on the macOS one: what's new, the download size, whether a relaunch is needed, and clear **Update Now / Later** actions. You can also check any time from the **Check for Updates…** menu item or **Settings → Software Update**.

**Your holdings are protected at every step.** Before an update installs, FolioOrb takes a verified backup of your portfolio database and your settings — and if that backup can't be made, the update is paused rather than risking your data. Backup verification checks the database's actual holdings count, not just that a file exists, so a backup that silently lost data is caught before it's ever trusted. Database migrations get the same protection: a version bump backs up first and, if a migration ever failed, automatically restores the last good state. After updating, a quiet confirmation notes that your holdings came through intact.

**A real way back.** If an update misbehaves, **Restore previous version…** (in Settings, and offered automatically after repeated failed launches) rolls back to the prior version. It always snapshots your current data first, so nothing is lost either way; you choose whether to also restore the pre-update data. Rolling back refuses to run while another update is already in progress, so the two can't collide.

**Trustworthy downloads.** Every update package is verified by SHA-256 against the checksums published with the release before it's installed; corrupted or interrupted downloads are rejected or resumed. Optional minisign signing (see `packaging/SIGNING.md`) adds cryptographic authenticity when enabled. Release notes are rendered as text, not raw HTML — a malicious link in a release body can't inject a script into the app.

**Verification:** the update system was built in eight phases, then put through two rounds of adversarial review and a dedicated pass on the frozen-app connectivity fix above — multi-angle code review plus live testing of every state (checking, available, downloading, verifying, backing up, ready, installing, offline, error, rollback) against the actual installed `.app`, not just source. Together these caught and fixed the TLS/offline root cause plus nine other real issues before wide distribution, including a data-loss gap in backup verification, an XSS path in release-notes rendering, two settings/rollback race conditions, and a macOS "quit unexpectedly" crash on every app exit. 256 dedicated offline tests cover backup/restore, migration safety, download/verify, rollback, signature checking, TLS/error classification, and the macOS bundle-swap install; `pylint` holds at 10.00 across every module.

No action is required on update: your holdings, settings, and `.env` are preserved.

---

## ✦ Quieter Hot Paths

> *v4.3.4 is a performance and hygiene release. No feature changes, no data migration — a handful of targeted fixes to the code that runs most often, so the dashboard stays smooth as portfolios and interactions scale up.*

The v4.3.1–v4.3.3 releases went after scrolling and range-switching. This one tightens the small, high-frequency paths that add up: number formatting that runs on every rendered value, and the correlation heatmap's hover behavior.

**Currency formatting no longer allocates per value.** Every dollar figure on the dashboard — holdings rows, tables, tiles, movers — was built with a freshly constructed `Intl.NumberFormat` on each call. Constructing that object is far more expensive than the formatting itself. The currency formatter (and the two world-market price formatters) are now built once and reused, so rendering a portfolio with many positions does proportionally less work. Output is byte-for-byte identical.

**The correlation heatmap stops rebuilding its canvas on hover.** Moving the mouse across the heatmap re-ran the full draw routine, which reassigned the canvas's pixel dimensions every time — and setting a canvas's width or height reallocates and clears its entire backing store, even when the size hasn't changed. The redraw now only touches the bitmap dimensions when they actually change; the per-frame clear is unchanged, so the picture is identical.

**Hover and resize work is coalesced to one pass per frame.** The heatmap's `mousemove` handler ran a layout read plus a possible redraw on every raw event; it's now throttled to `requestAnimationFrame`, doing at most one pass per frame with the freshest pointer position. The two dashboard-zone indicator handlers, which read and then write layout on every resize event, are throttled the same way.

**Also fixed two rough edges found during release verification:**

- **Misleading "AI failed" warnings when no Claude API key is configured.** Running key-free (the default "Local Intelligence" mode) made the Anthropic SDK raise a client-side `TypeError` on every portfolio briefing, analytics insight, and action plan request — an expected, harmless condition, but it was logged as `AI briefing failed`, `AI analytics insights failed`, etc. at warning level on every dashboard load, indistinguishable from a real failure. These three call sites now log at debug with an accurate "no Claude API key configured" message when no key is set, and still warn normally on a genuine failure with a key present. No change to what's returned to the dashboard — the deterministic local fallback was already correct.
- **The greyed-out "Local Intel" engine toggle opened the wrong panel.** With no API key configured, the Engine toggle in the menu correctly shows as disabled (dimmed, "not-allowed" cursor, a tooltip explaining why) — but tapping it opened the passive "Meet FolioOrb" intro card, which only tells you to hand-edit `.env` and restart the server. It now opens the actual **Connect Claude AI** panel directly — paste a key and hit **Save & Connect**, no restart needed — and closes the menu first so the panel isn't covered by it. Once a key is saved, the same control becomes a live toggle between Local and Claude AI, exactly as before.

**Verification:** the full 381-test suite passes, `pylint` holds at 10.00/10, the app boots and renders cleanly, and the currency/market formatters were confirmed to produce identical output after the change. The engine-toggle fix was verified end-to-end in a running build (disabled state → tap → key panel opens, unobstructed). The theme, spacing, typography, and animations are untouched — these changes are internal to how existing work is scheduled and routed, not what is drawn.

No holdings, settings, or `.env` changes are required — installing v4.3.4 over v4.3.3 or earlier keeps everything as-is.

---

# FolioOrb v4.3.3 Release Notes

**Release date:** July 8, 2026

---

## ✦ One Range, Every Section

> *v4.3.3 adds a 1W time range and makes range switching mean something everywhere on the dashboard — not just the P&L card.*

Until now, the Today / 1M / 3M / 6M / 1Y switcher on the Overview tab only drove the hero P&L number. Everything below it — the sector/movers panel, the portfolio briefing, the allocation focus read — stayed locked to "today," even after you'd switched to a longer view. v4.3.3 makes the whole dashboard follow your selection.

**Added a 1W option.** The switcher is now Today, 1W, 1M, 3M, 6M, 1Y, same chip style, same keyboard/hover/focus behavior.

**The range now drives four sections, not one.** Switch to 1M and "Today's impact" becomes "Past month impact" with real per-holding movers for that window, the portfolio briefing narrates the month instead of the day, and the allocation focus panel's "why it moved" read updates to match. All four read from one shared selected range instead of managing it independently.

**Fixed a real inconsistency this surfaced during testing.** The hero P&L card computed longer ranges from the app's own daily snapshot history, which needs weeks of actual usage to build up — so a newer portfolio would show "1M P&L: --" directly above a movers panel already showing a real number for that same month, pulled from actual market price history instead. The hero card now falls back to the same price-history calculation when snapshot history is too short, so the two numbers agree instead of one going blank.

**Performance:** all five non-day ranges are served by a single new endpoint in one request (not five), cached client-side per holdings set so re-selecting a previously-viewed range is instant with zero network calls. Rapid range switching cancels stale renders instead of flashing old data, each section fails independently with its own inline error/retry instead of taking down the dashboard, and the manual refresh button now refreshes range data too instead of only quotes.

No holdings, settings, or `.env` changes are required — installing v4.3.3 over v4.3.2 or earlier keeps everything as-is.

---

# FolioOrb v4.3.2 Release Notes

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

# FolioOrb v4.3.1 Release Notes

**Release date:** July 8, 2026

---

## ✦ Smooth Scrolling in the Desktop App

> *v4.3.1 is a performance release. The desktop app scrolled sluggishly on macOS; this fixes it — no feature changes, no data migration, just a much smoother dashboard.*

The native app (macOS DMG / Windows EXE) renders inside a system WebView — WKWebView on macOS, WebView2 on Windows — which pays a much steeper per-frame cost for certain effects than a desktop browser does. On slower machines that showed up as laggy, sluggish scrolling. v4.3.1 removes those hot spots:

**Fixed the two universal scroll killers.** The ambient page background used `background-attachment: fixed`, which forces the browser to repaint the entire glow gradient on *every* scroll frame; it now lives on a fixed, compositor-cached layer that's painted once. The drifting background "orbs" carried a heavy `blur(40px)` filter that had to be re-rasterized each frame while they animated; the blur is gone (the glows were already soft radial gradients) and the drift is now a cheap, GPU-composited transform. Both changes benefit the browser and from-source runs too.

**Added a desktop-app rendering profile.** Inside the native WebView, the app now switches to a lighter profile that drops `backdrop-filter` (frosted surfaces fall back to near-opaque fills, so the look holds up) and freezes a few always-on ambient animations. The in-browser and run-from-source experience is deliberately left at full fidelity — nothing was removed from the design.

**Measured result:** roughly a **3× improvement** in scroll frame rate on the overview and analytics views under CPU-throttled testing, with janky frames cut by about two-thirds. No holdings, settings, or `.env` changes are required — installing v4.3.1 over v4.3.0 keeps everything as-is.

---

# FolioOrb v4.3 Release Notes

**Release date:** July 7, 2026

---

## ✦ FolioOrb Goes Desktop

> *v4.3 is the release where FolioOrb stops being a thing you set up and starts being a thing you download. No Python, no terminal, no `pip install` — just a native app.*

Until now, running FolioOrb meant having Python on your machine and a comfortable relationship with a terminal. v4.3 removes that entirely. There are now real installers — a **`.dmg`** for macOS (Apple Silicon) and a clean per-user **`.exe`** for Windows — that drop a native app on your machine and open the dashboard in its own window. The FastAPI server still runs locally; it just runs *inside* the app now instead of a terminal tab you have to keep alive.

**One-click installers.** Download the [macOS DMG](https://github.com/udhawan97/FolioOrb/releases/latest) or [Windows installer](https://github.com/udhawan97/FolioOrb/releases/latest), launch it, and you're in. Your database and `.env` live in the per-user data directory (`~/Library/Application Support/FolioOrb` on macOS, `%APPDATA%\FolioOrb` on Windows) — never inside the app bundle — so updates and uninstalls leave your portfolio untouched.

**An automated, honest release pipeline.** Every version tag builds both platforms in GitHub Actions, smoke-tests that the frozen app actually boots, and only *then* publishes the installers plus a `SHA256SUMS.txt` to GitHub Releases. A broken build can never replace a good download. Every merge to `main` also refreshes a rolling `latest-main` prerelease for early testers, kept clearly separate from stable.

**A download-first website.** The [landing page](https://udhawan97.github.io/FolioOrb/) was rebuilt around real, retina screenshots of the actual dashboard — it detects your OS, links straight to the current installer, and shows the live release version, date, and commit. The docs gained a full Download & Install section with macOS Gatekeeper and Windows SmartScreen walkthroughs.

**Signing, honestly.** These early builds are not yet code-signed, so macOS and Windows will show a first-launch warning. That's expected for an open-source app without a paid certificate, and the install guides show exactly what you'll see and how to verify your download against the published checksums. Code signing and notarization are the planned next step.

v4.3 is the release that turns a project you clone into a product you install.

---

# FolioOrb v4.2 Release Notes

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

- Full rename across `templates/index.html`, `static/js/dashboard.js`, and `static/css/style.css` — every id, class, JS variable/function, CSS keyframe, and the `localStorage` key (now `folioorb-dashboard-senpai-visible`) says `senpai`, not `pet`.
- The one visible label, "Portfolio Butler," is now "Senpai."
- Pure naming pass — no behavior changed; `_HOLD_MODE_META` and every other tooltip are untouched.

### Tips & Tricks Quotes

- New `DASHBOARD_SENPAI_TIP_QUOTES` array — genuinely useful one-liners covering Research mode, the four hold-type modes, and the `M`/`?` shortcuts.
- Woven into the existing quote rotation in `showQuote()` at roughly a 1-in-4 chance per cycle (`SENPAI_TIP_QUOTE_CHANCE = 0.25`) without disturbing the underlying rotation index, so the regular commentary still cycles in order.

### First-Run Welcome Guide

- New modal (`#senpai-welcome-guide`), shown once when a fresh install has zero holdings, covering: adding a holding, what Research mode does, and the four hold-type icons — the hold-type list renders directly from `_HOLD_MODE_META` so it can never drift from the tooltips shown elsewhere in the app.
- Dismissal (close button or backdrop click) persists via `folioorb-senpai-welcome-seen` in `localStorage`; "Add your first holding" closes the guide and opens the portfolio manager directly.

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
curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioOrb/release-v4.2/scripts/install-mac.sh | bash
```

Downloads, installs, and places a **FolioOrb** shortcut on your Desktop. Browser opens automatically. Next time: double-click the Desktop shortcut.

### Windows — one command

Open PowerShell (Win+R → "powershell"), paste, and press Enter:

```powershell
irm https://raw.githubusercontent.com/udhawan97/FolioOrb/release-v4.2/scripts/install-win.ps1 | iex
```

Downloads, installs, and places a **FolioOrb** shortcut on your Desktop. Browser opens automatically. Next time: double-click the Desktop shortcut.

### Upgrading from v4.1

Run the same install command above — it detects your existing `database/` and `.env`, preserves them, and starts the updated app. No manual backup or file copying required.

No schema migration or `.env` change required. If you had toggled Senpai's visibility off before this update, it resets to visible once (the `localStorage` key changed names) — toggle it back off from menu → Dashboard → Senpai if you'd rather it stay hidden.

---

## Final Word

v4.2 is still not financial advice. It's just the release where the orb got a name, first launches got a map, and the docs stopped sending people into the void.

---

# FolioOrb v4.1 Release Notes

**Release date:** June 28, 2026

---

## ✦ The Dashboard Finally Knows Its Own Key

> *v4.1 is the release where setup stopped requiring a text editor. You can now hand Claude your API key from the dashboard itself — and watch it spend every token in real time.*

FolioOrb now has an **in-dashboard API key panel**. In v4.1 it opened from the brand mark; current releases use the dedicated key icon beside the brand. Paste your `sk-ant-*` key and the dashboard validates it, writes it to `.env`, and reconnects Claude without a restart. No terminal. No `.env` file hunting. Input is validated client-side and server-side against the canonical Anthropic key format before a single character touches disk.

The cost HUD in the nav got honest. Instead of estimating from cache occupancy, the dashboard now tracks **real token counts** across every Claude call made in the session. The nav breakdown shows actual input and output tokens, a live cost figure, and a predicted per-run annotation derived from backend constants — so you always know what a full scan costs before you click refresh again.

The holdings table got faster and more responsive. Rows now expand on the **first click**, latency on the expand path was cut, and an **auto-refresh** keeps prices current without manual intervention. The Overview sector graph was refactored to render weighted bars with proper proportional fills and a clean overflow note.

v4.1 is a tightening: the same cockpit, now easier to configure and harder to misread.

---

## What's New

### In-Dashboard API Key Configuration

- **`POST /api/ai/configure-key`** — accepts an `api_key` body, validates against `^sk-ant-[A-Za-z0-9_\-]{20,300}$`, writes a single `ANTHROPIC_API_KEY=…` line to `.env` (creating the file if absent), and reloads the Anthropic client in-process. No restart required.
- **API Key panel** — accessible from the key icon beside the brand in the nav. Password-type input with show/hide toggle, live keystroke validation (strips paste garbage, checks format character-by-character), a save button that activates only when the key is structurally valid, and an inline status message on success or failure. Closes on click-outside and Escape.
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
curl -fsSL https://raw.githubusercontent.com/udhawan97/FolioOrb/release-v4.1/scripts/install-mac.sh | bash
```

Downloads, installs, and places a **FolioOrb** shortcut on your Desktop. Browser opens automatically. Next time: double-click the Desktop shortcut.

### Windows — one command

Open PowerShell (Win+R → "powershell"), paste, and press Enter:

```powershell
irm https://raw.githubusercontent.com/udhawan97/FolioOrb/release-v4.1/scripts/install-win.ps1 | iex
```

Downloads, installs, and places a **FolioOrb** shortcut on your Desktop. Browser opens automatically. Next time: double-click the Desktop shortcut.

### Upgrading from v4.0

Run the same install command above — it detects your existing `database/` and `.env`, preserves them, and starts the updated app. No manual backup or file copying required.

No schema migration or `.env` change required. All v4.0 data carries over as-is.

---

## Final Word

v4.1 is still not financial advice. It is just the first version that will let you configure Claude from the dashboard while watching exactly how much each opinion costs.

---

# FolioOrb v4.0 Release Notes

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
curl -L -o FolioOrb-v4.0.zip https://github.com/udhawan97/FolioOrb/archive/refs/tags/release-v4.0.zip
unzip FolioOrb-v4.0.zip
cd FolioOrb-release-v4.0
./scripts/setup.sh
```

**Windows PowerShell**

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioOrb/archive/refs/tags/release-v4.0.zip" -OutFile "FolioOrb-v4.0.zip"
Expand-Archive -Path "FolioOrb-v4.0.zip" -DestinationPath .
cd FolioOrb-release-v4.0
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

# FolioOrb v3.1 Release Notes

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
curl -L -o FolioOrb-v3.1.zip https://github.com/udhawan97/FolioOrb/archive/refs/tags/release-v3.1.zip
unzip FolioOrb-v3.1.zip
cd FolioOrb-release-v3.1
./scripts/setup.sh
```

**Windows PowerShell**

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioOrb/archive/refs/tags/release-v3.1.zip" -OutFile "FolioOrb-v3.1.zip"
Expand-Archive -Path "FolioOrb-v3.1.zip" -DestinationPath .
cd FolioOrb-release-v3.1
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

# FolioOrb v3.0 Release Notes

**Release date:** June 27, 2026

---

## ✦ The Portfolio Stopped Pretending It Was Diversified

> *FolioOrb v3.0 is the release where your book gets treated like a system — overlap, mood, timelines, and three futures with probability bars — instead of a decorative pile of tickers wearing a diversification costume.*

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
curl -L -o FolioOrb-v3.zip https://github.com/udhawan97/FolioOrb/archive/refs/tags/release-v3.zip
unzip FolioOrb-v3.zip
cd FolioOrb-release-v3
./scripts/setup.sh
```

**Windows PowerShell**

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioOrb/archive/refs/tags/release-v3.zip" -OutFile "FolioOrb-v3.zip"
Expand-Archive -Path "FolioOrb-v3.zip" -DestinationPath .
cd FolioOrb-release-v3
.\scripts\setup.ps1
```

Open [http://localhost:8000](http://localhost:8000). Anthropic API key is optional.

### Upgrade from v2.x

1. Stop the app (`Ctrl+C`).
2. Back up `database/` and `.env`.
3. Download v3 into a **new folder** — do not overwrite in place.
4. Copy `database/` and `.env` into the new tree.
5. Run setup once, then `start.sh` / `start.ps1` going forward.

The `verdict_snapshots` table is created automatically on startup. No `.env` changes required. `force_local=true` still skips Claude and keeps deterministic evaluation on-device; it does not disable FolioOrb's separate bounded public-data lookups.

---

## Final Word

v3.0 still is not financial advice. It is a more honest briefing layer — overlap, mood, timelines, and futures with probability bars — for portfolios that stopped pretending five tech ETFs count as diversification.

---

# FolioOrb v2.4 Release Notes

**Release date:** June 25, 2026

## Headline

FolioOrb v2.4 is the mode-control release: Claude when you want the charm, Local Intelligence when you want deterministic quiet, and fresher-feeling market data without extra drama.

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
curl -L -o FolioOrb-v2.4.zip https://github.com/udhawan97/FolioOrb/archive/refs/tags/release-v2.4.zip
unzip FolioOrb-v2.4.zip
cd FolioOrb-release-v2.4
./scripts/setup.sh
```

---

# FolioOrb v2.3 Release Notes

**Release date:** June 2026

## Headline

FolioOrb v2.3 is the graceful-offline release: clearer no-key behavior, sharper local labels, and one less thing for CodeQL to side-eye.

## What's New

- Claude offline setup guidance in the brand callout
- **Local Intelligence Verdict** labels when Claude is disconnected
- Dynamic verdict kicker updates on reconnect
- Day-change rendering polish and timing-signal log sanitization

## Final Word

v2.3 still is not financial advice. It just stopped pretending Claude was whispering when he wasn't in the room.
