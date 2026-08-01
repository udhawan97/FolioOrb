# FolioOrb

Local-first portfolio dashboard. **FastAPI + SQLAlchemy 2.0 + SQLite**, vanilla-JS frontend, shipped as a PyInstaller desktop app. Not Flask, not Django.

## Commands

```bash
source venv/bin/activate                     # scripts/setup.sh creates venv + .env
python run.py                                # dev server, http://localhost:8000 (reload=True)
python -m pytest -q                          # full suite, offline
python -m compileall -q app run.py tests     # CI runs this before pytest
python -m pylint $(git ls-files '*.py')      # exactly what CI runs
```

`pytest` and `pylint` are **not** in `requirements.txt` — `pip install pytest pylint` separately.
Desktop deps are separate too: `pip install -r requirements-desktop.txt`.

Local URLs: `/` dashboard, `/docs` Swagger, `/health` health check.

## CI gates (must pass before pushing)

- **Pylint has no `--fail-under`.** Any single message fails the build. The bar is 10.00/10, not "good enough". Config in `.pylintrc`: `max-line-length=100`, `max-args=8`, docstring + `broad-exception-caught` + `import-error` checks disabled.
- Tests run on Python 3.11 **and** 3.12 with `ANTHROPIC_API_KEY=""` — AI paths must degrade gracefully with no key.
- `security-hygiene.yml` fails if any `.env`, `*.db`, `*.sqlite`, `*.bak`, or `.DS_Store` is git-tracked. Never commit `database/portfolio.db`.
- `pip-audit` on `requirements.txt`; CodeQL `security-extended`; dependency-review fails on moderate+.

## Architecture

```
run.py              dev entry (uvicorn, auto-opens browser)
desktop/main.py     frozen entry: in-process uvicorn on loopback + pywebview; --smoke for CI
app/main.py         app factory; lifespan runs migrations + background cache warmup
app/paths.py        resource_dir()/data_dir() — the source-vs-frozen split. Read this first.
app/config.py       Settings singleton, loads .env from data_dir()
app/database.py     engine, SessionLocal, get_db(), SQLite PRAGMAs, ensure_startup_migrations()
app/schema_meta.py  schema_version + backup-first migration wrapper
app/models.py       8 tables (portfolios, holdings, realized_trades, verdict_snapshots, dca_*, ...)
app/routers/        7 routers, all /api/*: ai, portfolio, news, stocks, dca, system, review
app/routers/deps.py shared router helpers (require_portfolio → 404)
app/services/       64 modules — market data, portfolio math, signals/AI, EDGAR, updater, backups
static/js/          dashboard.js (~14k lines), analytics-charts.js, core.js, review-orbit.js,
                    updates.js — plain JS, no build
templates/index.html  served as a pre-read string; no Jinja
docs-site/          separate Astro 7 + Starlight site (npm), deploys to GitHub Pages
```

`app/routers/ai.py` and `app/services/investment_signal.py` are the two largest files — prefer extracting into `app/services/` over growing them.

## Gotchas

**Frontend cache-busting is automatic.** `templates/index.html` writes every local asset as `?v=0`; `_stamp_static_assets()` in `app/main.py` rewrites that to a SHA-1 of the file's bytes when the template is read at import. Edit a JS or CSS file and the URL changes by itself — nothing to bump. Keep the `?v=0` placeholder on new asset tags (a tag with no `?v=` is never stamped).

**Frontend edits break Python tests.** Several tests (`test_csv_import_ui.py`, `test_dividend_calendar_ui.py`, …) assert on literal strings inside `dashboard.js` / `index.html`. Run pytest after touching the UI.

**No Alembic.** Migrations are two hand-rolled layers: `Base.metadata.create_all()` for new tables, then idempotent raw `ALTER TABLE` / `CREATE INDEX IF NOT EXISTS` in `ensure_startup_migrations()`. Bumping `SCHEMA_VERSION` in `app/schema_meta.py` triggers a verified backup-then-restore-on-failure path. Don't reach for `alembic revision`.

**`app/version.py` is the release gate.** One line, `__version__`. `release.yml` hard-fails if a `v*` tag doesn't match it. Bumping a release also means hand-syncing hard-coded version strings in `RELEASE_NOTES.md` and several `docs-site/src/content/docs/*` pages.

**Caching is in-process, market-hours-aware, no Redis.** Use the `@ttl_cache` decorator in `app/services/ttl_cache.py` — it owns expiry, eviction, the `force_refresh` bypass, and single-flight coalescing so concurrent misses on one key fetch once. TTL may be a callable read at store time (that is how `stock_service` gets 60s open / 900s closed). Don't hand-roll a module-level `dict[key] = (expiry, payload)`; a handful of those survive (`portfolio_analytics`, `portfolio_projection`, `dividend_calendar`, `update_service`, `news.py`) and are the exception, not the pattern. Restarting the server clears everything.

**Blocking endpoints must be `def`, not `async def`.** One uvicorn worker means one event loop; an `async def` handler that calls yfinance, EDGAR, the sync Anthropic client, or an unbounded query holds it and every other request queues behind it. FastAPI threadpools plain `def` handlers. `tests/test_event_loop_safety.py` enforces this by sweeping every router and failing any `async def` not listed in its `GENUINELY_ASYNC` table.

**Market data goes through `market_data.py`; symbols through `ticker.py`.** `app/services/market_data.py` is the only module that imports yfinance — no router touches the vendor. `stock_service.py` decides what a *quote* means (which price field to believe, TTLs, `usable_price`); `app/services/ticker.py` decides what a *symbol* is (`TICKER_PATTERN`, `normalize_ticker`, `ticker_shape_is_safe`) and is dependency-free so `app/schemas.py` can share it. Nine services call `market_data` directly and own their own caching — check before adding a tenth.

**Portfolio-scoped mutations must filter on `portfolio_id`.** Look holdings up via `holdings_repository` (`active`, `active_by_ticker`, `in_portfolio`), never by primary key alone — id-only lookups let a request scoped to one portfolio mutate another's row. `holdings_repository` is the single owner of `portfolio_id == X AND is_active IS TRUE`.

**Portfolio totals are dollars only.** `TICKER_PATTERN` accepts foreign listings (`VOD.L`, `SHOP.TO`), and Yahoo prices them in their home currency — London in *pence*. `portfolio_valuation.evaluate()` keeps any row whose quote currency isn't USD out of every total, names it in `foreign_currency_tickers`, and suppresses that day's snapshot. There is no FX conversion; don't add one without deciding what a total means when the rate is stale.

## Testing

pytest only, flat `tests/` (~120 files), **no pytest config file** — defaults apply. `tests/conftest.py` is suite-wide only: it forces market data offline (`FakeMarketData`), clears TTL caches around every test, and provides `db` (in-memory SQLite seeded with portfolio 1) and `api_client` (mounts routers on a bare app wired to `db`). Most files still carry their own `_make_db()` copy — prefer the fixtures in new tests. External I/O is stubbed with `monkeypatch`. The suite is fully offline — never add a test that hits the network. Routes are tested via `fastapi.testclient.TestClient`.

## Environment

`.env` lives in `data_dir()` (repo root in source, per-user dir when frozen). See `.env.example`. Blank `ANTHROPIC_API_KEY` disables AI endpoints by design. Undocumented but read in code: `APP_SECRET_KEY`, `FOLIO_UPDATE_REPO`, `FOLIO_DISABLE_UPDATE_SCHEDULER`, `FOLIO_SEC_CONTACT`.

## External services

Yahoo Finance (yfinance), SEC EDGAR (`data.sec.gov`, requires a contact User-Agent), US Treasury yield-curve XML, GitHub API (update checks), Anthropic API (default model `claude-haiku-4-5-20251001`).
