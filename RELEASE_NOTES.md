# FolioSenseAI v3 Release Notes

Release date: June 27, 2026

## Headline

FolioSenseAI v3 is the "your portfolio is a system, not a bag of tickers" release: richer local intelligence, Claude that can disagree on purpose, and a dashboard that finally learned negative space. Exposure overlap, market mood, peer context, earnings risk, three scenarios, and — when Claude is connected — a probability bar for which future is least delusional.

## What's New

- **Look-through portfolio exposure**: sector, country, theme overlap, duplicate detection, and HHI concentration via `/api/ai/portfolio-exposure`.
- **Market regime context**: SPY/TLT/VIX/UUP backdrop with cached daily component weight shifts.
- **Peer-relative positioning**: own-range percentile vs peer median on each verdict card.
- **Earnings event awareness**: names with earnings inside 14 days get capped confidence and a risk note.
- **Time horizons**: `auto` / `trade` / `core` / `anchor` with a cycle pill on the verdict card and Manage Holdings support.
- **Confidence ranges**: `range_low` / `range_high` beside the headline score.
- **Base / Bull / Bear scenarios**: local paths plus Claude probability splits (`likely`, `sc_p`, `sc_w`) when AI is connected.
- **Claude tension gating**: nudges only when inputs conflict (`agrees`, `tension`, `flip_if`); agreement does not get performative drama.
- **Verdict calibration snapshots**: logged to SQLite with bucket summaries via `/api/ai/verdict-calibration`.
- **Deep intelligence on expand**: `/api/ai/intelligence/{ticker}/deep` loads richer holding context async when a row opens.
- **Navbar overflow menu**: theme, text size, pet mode, and AI-cost controls in one settings sheet.
- **Semantic color tokens**: `--color-gain/loss/neutral/state/brand` so green always means money up.
- **Global state hardening**: mode toggles, sync HUD, and verdict rendering no longer step on each other.

## Developer Notes

- Bumped FastAPI metadata version to `3.0.0`.
- Updated the dashboard intro badge to `v3`.
- Added services: `portfolio_exposure.py`, `market_regime.py`, `peer_relative.py`, `event_calendar.py`, `verdict_calibration.py`, `verdict_ai_enhancement.py`.
- Extended `investment_signal.py` with horizon weights, confidence ranges, scenario builders, and modifier hooks.
- Extended Claude prompts in `ai_service.py` for disagreement and scenario-probability fields.
- Added `VerdictSnapshot` model and startup migration for `verdict_snapshots`.
- Extended `hold_class` schema to accept `trade` and `core` alongside `auto` and `anchor`.
- Extended `/api/ai/investment-signals/all` with `portfolio_exposure`, `regime`, `calibration_summary`, and per-signal context fields.
- Large `dashboard.js` / `style.css` pass for exposure strips, regime chips, scenario UI, and nav overflow.
- Bumped static asset cache keys to `v=77`.
- **247 tests passing**, including new coverage for nav overflow, semantic tokens, scenario normalization, and calibration logging.

## Upgrade Notes

Existing installs pick up a new `verdict_snapshots` table automatically on startup via `ensure_startup_migrations()`. No `.env` change is required.

`force_local=true` still skips Claude; all local intelligence features work offline.

Install v3 from the latest `main` branch:

```bash
curl -L -o FolioSenseAI-main.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/heads/main.zip
unzip FolioSenseAI-main.zip
cd FolioSenseAI-main
./scripts/setup.sh
```

Windows PowerShell:

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioSenseAI/archive/refs/heads/main.zip" -OutFile "FolioSenseAI-main.zip"
Expand-Archive -Path "FolioSenseAI-main.zip" -DestinationPath .
cd FolioSenseAI-main
.\scripts\setup.ps1
```

Prefer a frozen zip? [release-v2.4](https://github.com/udhawan97/FolioSenseAI/releases/tag/release-v2.4) still works — you just miss everything above.

## Final Word

v3 still is not financial advice. It is a more honest briefing layer that treats your portfolio like a system with overlap, mood, and timelines — not a bag of tickers wearing a diversification costume.

---

# FolioSenseAI v2.4 Release Notes

Release date: June 25, 2026

## Headline

FolioSenseAI v2.4 is the mode-control release: a polished Claude AI / Local Intel toggle, deterministic verdict quips on demand, faster repeated quote reads, and a last-sync HUD that stays graceful when refreshes fail. Claude gets the charm. Local Intelligence gets the quiet competence. You get to choose. Flirty? Only in the most professionally documented way.

## What's New

- **Claude AI / Local Intel toggle**: switch verdict quips into deterministic local mode for the session without removing your Anthropic API key.
- **Forced-local verdict path**: `/api/ai/investment-signals/all?force_local=true` skips Claude quip generation and uses fallback/local quips for holdings and portfolio health.
- **Persistent mode preference**: the dashboard remembers your local-mode choice in browser storage and updates verdict labels/kickers in place.
- **Smarter offline state**: the mode toggle disables cleanly when Claude is offline and opens the setup guidance instead of pretending a network problem is a personality trait.
- **Quote caching**: live quote reads are cached for 60 seconds in `stock_service`, cutting repeated Yahoo Finance calls during tight dashboard refresh loops.
- **Last-sync resilience**: the HUD keeps the last good sync timestamp when a refresh fails, marks the state clearly, and avoids replacing usable data with panic confetti.
- **Sync state before render**: HUD timestamp and loaded-state are committed as soon as data arrives from the API, so a Chart.js or rendering error cannot flip the sync indicator back to "failed."
- **In-flight guard**: a `_portfolioValueInFlight` flag prevents overlapping `loadPortfolioValue` calls from racing to create duplicate chart canvases and triggering false refresh failures.
- **% column polish**: the percentage column in the target-trend list is wider and `white-space: nowrap`; `formatSignalPct` drops the decimal when the value hits triple digits so the string stays compact for any holding.
- **Toggle polish**: placement, labels, title text, and dashboard pet copy now make the Claude/local relationship clearer and a little more charming.

## Developer Notes

- Bumped FastAPI metadata version to `2.4.0`.
- Updated the dashboard intro badge to `v2.4`.
- Added `force_local: bool = False` to `get_all_investment_signals()`.
- Updated dashboard signal fetches to append `?force_local=true` when Local Intel mode is active.
- Added `_QUOTE_CACHE` and `_QUOTE_TTL = 60` to `app/services/stock_service.py`.
- Added HUD sync failure handling so stale-but-valid data remains visible after a failed refresh.
- Moved HUD DOM update (timestamp, `_hasLoadedOnce`) to run immediately after API response, before any rendering — rendering errors can no longer affect sync display.
- Added `_portfolioValueInFlight` guard to `loadPortfolioValue` to prevent concurrent calls from racing on the chart canvas.
- Wrapped all rendering code in an inner `try/catch`; a render error now warns to the console instead of surfacing "Refresh failed" to the user.
- Widened `.target-trend-list` percentage column (`2.7rem → 3rem`), added `white-space: nowrap` to `.target-trend-line strong`, and updated `formatSignalPct` to drop the decimal at ≥100.
- Added `.pet-mode-toggle` CSS and related state styling.
- Bumped the dashboard script cache key to load the new frontend behavior.

## Upgrade Notes

No database migration or `.env` change is required. Existing installs continue to run as before.

The new Local Intel mode is client-side selectable. With Claude configured, users can switch between Claude-backed quips and deterministic local quips. Without Claude configured, the app continues in offline/local mode and shows setup guidance.

If you use GitHub release archives, install v2.4 with:

```bash
curl -L -o FolioSenseAI-v2.4.zip https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v2.4.zip
unzip FolioSenseAI-v2.4.zip
cd FolioSenseAI-release-v2.4
./scripts/setup.sh
```

Windows PowerShell:

```powershell
Invoke-WebRequest -Uri "https://github.com/udhawan97/FolioSenseAI/archive/refs/tags/release-v2.4.zip" -OutFile "FolioSenseAI-v2.4.zip"
Expand-Archive -Path "FolioSenseAI-v2.4.zip" -DestinationPath .
cd FolioSenseAI-release-v2.4
.\scripts\setup.ps1
```

## Final Word

v2.4 still is not financial advice. It is a more controllable, more resilient dashboard that lets Claude bring the sparkle when invited and lets Local Intelligence keep working when you prefer the numbers without the perfume.
