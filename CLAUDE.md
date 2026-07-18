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
app/models.py       9 tables (portfolios, holdings, price_snapshots, verdict_snapshots, dca_*, ...)
app/routers/        6 routers, all /api/*: ai, portfolio, news, stocks, dca, system
app/services/       51 modules — market data, portfolio math, signals/AI, EDGAR, updater, backups
static/js/          dashboard.js (~14k lines), analytics-charts.js, updates.js — plain JS, no build
templates/index.html  served as a pre-read string; no Jinja
docs-site/          separate Astro 7 + Starlight site (npm), deploys to GitHub Pages
```

`app/routers/ai.py` and `app/services/investment_signal.py` are the two largest files — prefer extracting into `app/services/` over growing them.

## Gotchas

**Frontend cache-busting.** `templates/index.html` loads local JS with hand-bumped query strings (`dashboard.js?v=99`). Edit a JS file → bump its `?v=` or users get the stale file.

**Frontend edits break Python tests.** Several tests (`test_csv_import_ui.py`, `test_dividend_calendar_ui.py`, …) assert on literal strings inside `dashboard.js` / `index.html`. Run pytest after touching the UI.

**No Alembic.** Migrations are two hand-rolled layers: `Base.metadata.create_all()` for new tables, then idempotent raw `ALTER TABLE` / `CREATE INDEX IF NOT EXISTS` in `ensure_startup_migrations()`. Bumping `SCHEMA_VERSION` in `app/schema_meta.py` triggers a verified backup-then-restore-on-failure path. Don't reach for `alembic revision`.

**`app/version.py` is the release gate.** One line, `__version__`. `release.yml` hard-fails if a `v*` tag doesn't match it. Bumping a release also means hand-syncing hard-coded version strings in `RELEASE_NOTES.md` and several `docs-site/src/content/docs/*` pages.

**Caching is in-process dicts with market-hours-aware TTLs** — no Redis. Pattern: module-level `dict[ticker] = (expiry_monotonic, payload)`. See `stock_service.py:55` (info 300s open / 3600s closed). AI narratives cache 24h. Restarting the server clears everything.

**yfinance is not funneled through `stock_service.py`.** Routers call it directly in places, bypassing that module's TTL cache and `TICKER_PATTERN` validation. New market-data code should go through `stock_service.py`.

**`peewee` is pinned in requirements.txt but unused.** SQLAlchemy is the ORM.

## Testing

pytest only, flat `tests/` (~95 files), **no `conftest.py` and no pytest config file** — defaults apply. Fixtures are file-local; external I/O is stubbed with `monkeypatch` (`monkeypatch.setattr("requests.get", ...)`). The suite is fully offline — never add a test that hits the network. Routes are tested via `fastapi.testclient.TestClient`.

## Environment

`.env` lives in `data_dir()` (repo root in source, per-user dir when frozen). See `.env.example`. Blank `ANTHROPIC_API_KEY` disables AI endpoints by design. Undocumented but read in code: `APP_SECRET_KEY`, `FOLIO_UPDATE_REPO`, `FOLIO_DISABLE_UPDATE_SCHEDULER`, `FOLIO_SEC_CONTACT`.

## External services

Yahoo Finance (yfinance), SEC EDGAR (`data.sec.gov`, requires a contact User-Agent), US Treasury yield-curve XML, GitHub API (update checks), Anthropic API (default model `claude-haiku-4-5-20251001`).
