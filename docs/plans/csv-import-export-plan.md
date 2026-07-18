# CSV Import & Export — Implementation Plan

**Status:** shipped (v4.5 — strict local template + Claude column remap; kept for design history)
**Effort:** Medium (~1 day)
**Confidence:** High — every moving part reuses an existing, tested pattern; the only new
concept is the column remapper, and it's a copy of the established `ai_service` call shape.

## Goal

Move holdings in and out of FolioOrb as CSV — the roadmap's "Spreadsheet in,
spreadsheet out" card (README.md:96, docs-site roadmap.mdx:17).

Three user-visible pieces:

1. **Export** (always available) — one click in the portfolio manager downloads the
   active holdings as a clean CSV that doubles as the import template.
2. **Local import** (always available, zero API key) — strict, exact-schema parse of
   that template. Deterministic, free, offline.
3. **Claude-assisted import** (only when a key is configured) — Claude remaps a messy
   third-party CSV (brokerage exports: `Symbol`/`Qty` headers, `$1,234.56` cells, junk
   columns) onto the template schema, then the rows go through the **same** strict
   local validation. Claude widens what's accepted; it never bypasses validation and
   never touches the DB.

## The one non-negotiable

Local Intelligence is the default and is never gated — same as everywhere else in this
app. Concretely for this feature:

- Local import fully works with a blank `ANTHROPIC_API_KEY`.
- Claude assist is additive: it only runs when a key is configured **and** the file
  doesn't already match the template (clean files never spend a token).
- If the Claude call fails for any reason — timeout, bad JSON, API down — the import
  **falls back to the strict local parse** and the UI says so honestly. A Claude
  failure must never error the whole import on its own.
- Claude emits *candidate rows only*. Every candidate still passes
  `HoldingCreate` → duplicate check → `validate_ticker_symbol` before any DB write.
  One choke point, both paths (structural guarantee, see `process_import_rows` below).

## Non-goals (do not build)

- No fuzzy/alias header matching in Local mode ("Symbol" ≠ "ticker" locally). Local
  stays exact-schema so the two modes are honestly different and locally predictable;
  Claude is the only widener.
- No XLSX/Google Sheets parsing — CSV only.
- No import of realized trades, snapshots, or price history — holdings only.
- No multi-portfolio picker in the UI (backend takes `portfolio_id`, UI uses 1, same
  as every other manager call).
- No drag-and-drop zone in v1 — file picker only.
- No new DB tables, no schema changes, no background jobs.
- No update of existing holdings from CSV (duplicates are skipped, not merged — see
  duplicate policy).

## What already exists (reuse, don't rebuild)

| Piece | Where | Notes |
| --- | --- | --- |
| Holding fields | `app/models.py:31` | `ticker, shares, avg_cost, is_watchlist, hold_class, notes` (+ `company_name` which stays derived — never export/import it). |
| Row validation | `app/schemas.py:32` `HoldingCreate` | Ticker regex + uppercase, `hold_class` ∈ {auto, anchor, trade, core}, notes ≤ 500, "shares > 0 unless watchlist" model validator. Feed every CSV row through it — free validation, zero reimplementation. |
| Ticker network check | `app/services/stock_service.py:396` `validate_ticker_symbol` | Shape check (`ticker_shape_is_safe`:71) before any network call, then quote resolution, plus suggestions. The exact check `add_holding` uses. |
| Add-holding flow | `app/routers/portfolio.py:383` | Dup query (389–401) + `validate_ticker_symbol` (405) + `Holding(...)` construction (415–423). The import loop mirrors this row-by-row. |
| Portfolio scoping | `app/routers/portfolio.py:68` `_get_portfolio_or_404` | Both new endpoints call it first. |
| Parallel quote warm | `stock_service.py:435` `get_all_quotes` (thread-pool `_parallel_fetch`:429) | Warm the quote cache once for all candidate tickers so per-row `validate_ticker_symbol` hits cache, not the network. |
| Claude call shape | `ai_service.py:219` `generate_etf_profile_seed` | The template to copy: `temperature=0`, `_cached_system` (58), fence-strip regex (251), `json.loads` + shape check, `_track_usage` (41), deterministic empty/raise on failure. |
| Key presence check | `ai_service.py:65` | `settings.ANTHROPIC_API_KEY.strip()` — the backend's "is Claude configured" idiom. |
| Cached heartbeat | `ai_service.py:95` `get_cached_claude_heartbeat` | Cheap "is Claude reachable" — skip a doomed remap call when it says down. |
| Client-swap gotcha | `ai_service.py:33` `reinitialize_client` | Rebinds `ai_service.client`. The new service must call `ai_service.client.messages.create(...)` via the module, **never** `from ai_service import client` (stale reference after a runtime key swap). |
| Frontend mode | `static/js/dashboard.js:685` `isLocalIntelligenceMode()` | `_isClaudeApiLive === false \|\| _forcedLocalMode`, driven by `/api/ai/heartbeat` polling (`loadClaudeHeartbeat`:8985). |
| Live mode flip | `dashboard.js:702` `setEngineScopedVisibility` | Elements tagged `data-engine-claude-only` / `data-engine-local-only` show/hide automatically on mode change — the import panel copy uses exactly this, no new state. |
| force-local precedent | `dashboard.js:698` `intelligenceSignalsUrl` (`?force_local=true`), `app/routers/ai.py` action-plan `force_local` param | Same pattern for the import endpoint: user in forced-local mode ⇒ server skips Claude. |
| Post-mutation refresh | `dashboard.js:8829` `refreshPortfolioMutationInBackground()` | Fire after any import that added rows; also `loadManageHoldings({preserveExisting:true})` + `showToast` (11009), same as the add-holding handler (10892). |
| Error-with-suggestions UI | `dashboard.js:10839` `renderAddHoldingError` | Style reference for row-error rendering. |
| Manager modal markup | `templates/index.html:2284–2386` | `manage-add-card`, `manage-list-toolbar` (2360), `manage-*` CSS — the import/export UI lives here and copies these classes. |
| Log hygiene | `app/services/log_safety.py` `sanitize_for_log` | Any user-derived value in a log line. |
| Router HTTP tests | `tests/test_earnings_radar_router.py` | Bare FastAPI + portfolio router + in-memory SQLite (`StaticPool`) + `dependency_overrides` + monkeypatching names in the router namespace. |
| Claude mock pattern | `tests/test_ai_service.py:42` `_mock_response` | MagicMock content block + usage; patch the client, never call the API. |
| Wiring tests | `tests/test_analytics_dashboard.py` | Assert strings/ids exist across html/js/css. |
| Senpai voice | `docs-site/src/content/docs/meet-senpai.mdx`, `dashboard.js:7976` tip quotes | Dry, precise, a little smug with Claude; matter-of-fact in local mode. The recap and panel copy follow it. |

## CSV format (locked)

Header row, exact names, **any column order** (via `csv.DictReader`), lowercase after
trim; only `ticker` is mandatory as a column:

```csv
ticker,shares,avg_cost,is_watchlist,hold_class,notes
VOO,10,412.5,false,auto,
NVDA,0,,true,auto,Watching for a pullback
```

| Column | Required | Local-mode value rules |
| --- | --- | --- |
| `ticker` | column + value required | `^[A-Z0-9.^-]{1,10}$` after trim/uppercase (the `HoldingCreate` regex, schemas.py:20). |
| `shares` | optional column | Plain decimal (`10`, `2.5`). Blank ⇒ `0.0`. Must be > 0 unless the row is watchlist (pydantic enforces). |
| `avg_cost` | optional column | Plain decimal > 0, or blank ⇒ none. |
| `is_watchlist` | optional column | `true/false/yes/no/y/n/1/0`, case-insensitive; blank ⇒ `false`. |
| `hold_class` | optional column | `auto\|anchor\|trade\|core` (case-insensitive); blank ⇒ `auto`. |
| `notes` | optional column | ≤ 500 chars (pydantic). Commas/quotes/newlines fine — the `csv` module handles quoting. |

Locked decisions:

- **Local mode is strict**: any header column outside this set ⇒ file-level error (that
  unrecognized-header set is also the "messy file" trigger for Claude mode). Plain
  numbers only — `$1,234.56` is a row error locally (Claude path cleans it).
- **Round-trip guarantee**: export writes exactly these six columns in exactly this
  order, so export → local import re-adds identical holdings (dup-skipped if still
  present). A dedicated test locks this.
- **Encoding**: import decodes `utf-8-sig` first (strips the BOM Excel writes), then
  `cp1252` as fallback (Windows broker exports); neither works ⇒ file-level error.
  Export is UTF-8 **with** BOM (`﻿`) so Excel opens it correctly — the importer
  strips it right back.
- **Row numbering in reports**: header is row 1; first data row is row 2 (what users
  see in Excel). Multi-line quoted notes count as one row (position among parsed data
  rows, not physical lines).
- `company_name` is intentionally absent — it's derived live from quotes everywhere.
- Export includes **active** holdings only (positions + watchlist), sorted by ticker.

## Backend

### 1. New service — `app/services/holdings_csv.py`

One module for both directions (round-trip logic and its tests live together). Pure
logic + the Claude calls; **no DB access, no FastAPI imports**. Module-level constants:

```python
CSV_COLUMNS = ("ticker", "shares", "avg_cost", "is_watchlist", "hold_class", "notes")
MAX_IMPORT_BYTES = 256 * 1024
MAX_IMPORT_ROWS = 200
MAX_HEADER_COLUMNS = 30      # above this, don't even ask Claude
REMAP_SAMPLE_ROWS = 5
REMAP_CELL_CHARS = 40
REMAP_TIMEOUT_S = 15.0
```

Functions (signatures locked, bodies obvious):

```python
def decode_csv_bytes(raw: bytes) -> str            # utf-8-sig → cp1252 → ValueError; rejects b"\x00"
def parse_csv_text(text: str) -> tuple[list[str], list[dict]]   # csv.DictReader; skips blank lines
def unrecognized_columns(header: list[str]) -> list[str]        # [] == clean template file
def strict_row_to_create_kwargs(row: dict) -> dict # local mode: plain-value parsing only
def clean_cell_number(value: str) -> str           # Claude path: "$1,234.56"→"1234.56", "(50)"→"-50", "12%"→"12"
def clean_cell_bool(value: str) -> str
def escape_csv_cell(value: str) -> str             # prefix ' when cell starts with = + - @ \t \r
def build_export_csv(holdings: list[Holding]) -> Iterator[str]  # yields BOM+header, then rows
def remap_columns_with_claude(header: list[str], sample_rows: list[dict]) -> dict[str, str | None]
def apply_mapping(mapping: dict, rows: list[dict]) -> list[dict]  # + deterministic cell cleaning
def narrate_import_summary(report: dict) -> str | None
def process_import_rows(raw_rows, existing_tickers, validate_fn) -> tuple[list[dict], list[HoldingCreate]]
```

`process_import_rows` is the single choke point both modes share — it takes already
template-shaped raw dicts (from the strict parser *or* from `apply_mapping`) and runs,
per row, in this order (cheap → expensive):

1. `HoldingCreate(**kwargs)` — pydantic shape/rules → `error` with the validation message.
2. In-file dedupe — later occurrence of a ticker already accepted from this file →
   `skipped`, reason `duplicate of row N in this file`.
3. Portfolio dedupe against `existing_tickers` (active tickers, passed in by the
   router) → `skipped`, reason `already in portfolio`.
4. `validate_fn(ticker)` — the router passes `validate_ticker_symbol`; injected so the
   service stays offline-testable. Invalid → `error` with its message (suggestions
   included in the reason when present).

Returns `(report_rows, holdings_to_insert)`; it never touches the DB.

Excel-mangled tickers get a nicer reason: when a ticker value fails shape/quote checks
**and** matches a date-ish pattern (`^\d{1,2}[-/][A-Za-z]{3}` or `^[A-Za-z]{3}[-/]\d{1,2}$`),
append `— this looks like a date; Excel may have reformatted the ticker. Re-export with
the column formatted as Text.` No auto-un-mangling (guessing `MAR26` back from `26-Mar`
is unsafe).

### 2. The Claude remapper (same service)

Runs **only** when: key configured (`settings.ANTHROPIC_API_KEY.strip()`, the
ai_service.py:65 idiom) **and** `force_local` is false **and** the header is not clean
**and** `len(header) <= MAX_HEADER_COLUMNS`. Optional cheap pre-check: if
`get_cached_claude_heartbeat()["live"] is False`, skip straight to fallback (don't
burn 15 s on a known-down API).

Call — a faithful copy of `generate_etf_profile_seed` (ai_service.py:219):

```python
from app.services import ai_service   # module import — never `from ai_service import client`

message = ai_service.client.messages.create(
    model=ai_service.MODEL,           # Haiku
    max_tokens=500,
    temperature=0,
    timeout=REMAP_TIMEOUT_S,
    system=ai_service._cached_system(_REMAP_SYSTEM),   # "…JSON only, no prose or markdown."
    messages=[{"role": "user", "content": compact_payload}],
)
ai_service._track_usage(ai_service.MODEL, message.usage)
raw = ...text block...
raw = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
mapping = json.loads(raw)
```

(If pylint gripes about the private helpers, export tiny public aliases from
`ai_service` instead of reaching for `_`-names — decide at implementation; either is a
one-liner.)

**Input** (token-capped by construction — the whole file is never serialized):

- The 6 target column names with one-line semantics.
- The raw header list.
- Up to `REMAP_SAMPLE_ROWS` data rows; every cell truncated to `REMAP_CELL_CHARS`
  chars and control-chars stripped; a cell that isn't short/ticker-ish/numeric
  (doesn't match `^[\w .,$%^()/:'"-]{0,40}$` after strip) is replaced with `"…"` — so
  Claude sees ticker-ish and numeric cells plus header names, not free-text noise.

Worst case ≈ 30 cols × 6 rows × a few tokens ≈ 3–4k input tokens. Bounded.

**Output contract** — exactly this JSON, strictly validated:

```json
{"mapping": {"ticker": "Symbol", "shares": "Quantity", "avg_cost": "Cost Per Share",
             "is_watchlist": null, "hold_class": null, "notes": "Description"}}
```

Validation: `mapping` is a dict; keys ⊆ `CSV_COLUMNS`; every non-null value is an
exact member of the actual header; `ticker` is non-null. Any violation → treated as
failure.

**Fallback ladder (deterministic, mandatory):** any exception, timeout, unparsable
JSON, or invalid mapping ⇒ run the strict local parse on the original file and set
`mode = "claude_fallback"`. The import never hard-fails because Claude did.

`apply_mapping` then extracts mapped cells for **all** rows locally, runs
`clean_cell_number` / `clean_cell_bool` on numeric/bool targets, and hands the results
to the same `process_import_rows`. Claude never sees rows 6+, and no Claude output
reaches the DB unvalidated.

### 3. Import narration (Claude mode only)

After the report is built and `mode == "claude"`, one more tiny call: same shape,
`max_tokens=120`, default temperature (it's voice, not data), plain text out (no JSON).
System prompt: *"You are Senpai, FolioOrb's dry-witted portfolio companion. In 1–2
sentences, recap this CSV import for the user. Use only the supplied counts and
reasons. Precise, warm, lightly amused; no financial advice; no markdown; no invented
numbers."* User content: compact JSON `{added, skipped, errors, top_reasons[≤3],
unmapped_columns}`. Any failure ⇒ `summary = null` and the UI just shows counts —
narration is garnish, never a blocker.

### 4. `GET /api/portfolio/holdings/export`

In `app/routers/portfolio.py`, **defined above** the `/holdings/{holding_id}` routes
(route-order hygiene). Thin: `_get_portfolio_or_404` → query active holdings →
`StreamingResponse(build_export_csv(holdings), media_type="text/csv; charset=utf-8")`
with

```
Content-Disposition: attachment; filename="folioorb-holdings-p{portfolio_id}-{YYYY-MM-DD}.csv"
```

Every cell goes through `escape_csv_cell` (see Security). Empty portfolio ⇒ header-only
CSV, still 200.

### 5. `POST /api/portfolio/holdings/import`

```python
@router.post("/holdings/import")
async def import_holdings(
    file: UploadFile = File(...),
    portfolio_id: int = 1,
    force_local: bool = False,
    db: Session = Depends(get_db),
):
```

Requires the new dependency **`python-multipart`** (pin current release in
`requirements.txt`) — FastAPI's `File(...)` needs it and the repo has no `UploadFile`
usage today. CI and the desktop build both install from `requirements.txt`
(release.yml:74/94/148), so it flows everywhere automatically.

Pipeline (thin router; steps 4–7 are service calls):

1. `_get_portfolio_or_404`.
2. Reject by content type: allow `text/csv`, `application/vnd.ms-excel`, `text/plain`,
   `application/octet-stream` — but only when the filename ends `.csv` for the last
   two. Otherwise **415**.
3. `raw = await file.read(MAX_IMPORT_BYTES + 1)`; over the cap ⇒ **413**. NUL byte or
   undecodable ⇒ **415**/**400**.
4. `decode_csv_bytes` → `parse_csv_text`. No data rows ⇒ **400**. More than
   `MAX_IMPORT_ROWS` ⇒ **400** (message states the cap).
5. Mode decision: header clean ⇒ local path (even with a key — zero tokens on clean
   files). Header messy + key + not `force_local` ⇒ remap; on remap failure ⇒
   fallback ladder. Header messy + (no key or `force_local`) ⇒ file-level **400**
   with guidance (below).
6. Warm quotes once: `get_all_quotes(sorted(set(candidate_tickers) - existing))` — the
   thread-pooled fetch fills the cache so step 7's per-row checks are near-instant.
7. `process_import_rows(...)` with `validate_ticker_symbol` injected.
8. Construct `Holding(...)` per accepted row exactly as `add_holding` does
   (portfolio.py:415–423), `db.add_all`, **one** `db.commit()` at the end. Partial
   success is the design: bad rows never block good rows; good rows commit together.
9. `mode == "claude"` ⇒ `narrate_import_summary`.
10. Return the report.

**Response contract (200 — file was readable):**

```json
{
  "portfolio_id": 1,
  "mode": "local",                 // "local" | "claude" | "claude_fallback"
  "added": 3, "skipped": 1, "errors": 2,
  "rows": [
    {"row": 2, "ticker": "VOO",  "status": "added",   "reason": null},
    {"row": 3, "ticker": "MSFT", "status": "skipped", "reason": "already in portfolio"},
    {"row": 4, "ticker": "26-MAR", "status": "error", "reason": "Couldn't find ticker 26-MAR — …"}
  ],
  "summary": "Three tickers aboard, one polite duplicate skipped…",   // Claude mode only, else null
  "column_mapping": {"ticker": "Symbol", "shares": "Qty"}             // Claude mode only, else null
}
```

`column_mapping` is included for transparency — the UI can show "mapped `Symbol` →
ticker" on request, and tests assert Claude's work is inspectable.

**File-level errors are 400 with a structured detail** (never a silent failure, never
all-or-nothing on row problems — those are 200 + report):

```json
{"detail": {"message": "Some columns weren't recognized: Symbol, Qty. Match the template
             (Export CSV shows it) or connect Claude in Settings and I'll map almost any
             brokerage export.",
            "mode": "local",                      // or "claude_fallback"
            "unrecognized_columns": ["Symbol", "Qty"],
            "expected_columns": ["ticker","shares","avg_cost","is_watchlist","hold_class","notes"]}}
```

Status map: 200 report · 400 file-level (empty/no-data/row-cap/header-mismatch/undecodable)
· 404 portfolio · 413 size · 415 content type/binary · 422 missing multipart field (free
from FastAPI).

**Duplicate policy (decision): skip + report.** Justification: non-destructive (an
import can never alter an existing position's shares/cost), idempotent-ish (re-importing
yesterday's export is a no-op with a readable report instead of a wall of errors), and
consistent with `add_holding`'s existing "already in portfolio" rejection — we just
soften the per-row 400 into a reported skip. Updating existing rows from CSV is a
different feature (explicit non-goal).

## Security & safety checklist

- **CSV injection (export):** any cell starting with `=`, `+`, `-`, `@`, tab, or CR is
  prefixed with `'` (`escape_csv_cell`, OWASP formula-injection guidance). Applied to
  every field defensively — the ticker regex technically admits a leading `-`, and
  notes are free text. The `csv` writer's quoting handles commas/quotes/newlines.
- **Import caps:** 256 KB byte cap enforced by bounded read; 200-row cap; both
  surfaced in UI copy and error messages, never silently truncated.
- **Content-type allowlist + binary sniff** (NUL check) before any parsing.
- **BOM/encoding:** `utf-8-sig` then `cp1252`; no `errors="replace"` mojibake into the DB.
- **Ticker safety ordering:** shape check (`HoldingCreate` regex / `ticker_shape_is_safe`)
  runs **before** any yfinance call — injection-shaped strings never reach the network
  layer. Log lines use `sanitize_for_log`.
- **Claude sees the minimum:** header + ≤5 sample rows, cells ≤40 chars, non-ticker-ish/
  non-numeric cells replaced with `…`, ≥6th row never serialized. No file names, no
  portfolio values.
- **Claude cannot write:** remapper output is a column mapping validated against the
  actual header; mapped rows re-enter the exact same validation pipeline as local rows
  (`process_import_rows` is the only path to `holdings_to_insert`).
- **No temp files:** the upload is processed in memory (fits comfortably under the cap).
- **Packaging:** `python-multipart` is pure Python; starlette imports it via a guarded
  top-level import that PyInstaller normally picks up. Verify the frozen smoke boot;
  if the import route 500s in a frozen build, add it to `hiddenimports` in
  `packaging/pyinstaller/FolioOrb.spec:31`.

## Frontend

### Placement

All in the portfolio manager modal (`templates/index.html:2284`):

- **Toolbar buttons** in `manage-list-toolbar` (2360), right of the search box, matching
  the ghost-button style: `#export-csv-btn` (anchor →
  `/api/portfolio/holdings/export?portfolio_id=1`, download icon, tooltip "Download your
  holdings as CSV — it's also the import template") and `#import-csv-btn` (upload icon,
  `aria-expanded` toggle).
- **Import panel** `#import-csv-panel`: a collapsible card styled like `manage-add-card`,
  inserted between the add card and the holdings list. Contains the mode copy, a hidden
  `<input type="file" id="import-csv-input" accept=".csv,text/csv">`, a "Choose CSV…"
  button, a "Download template" link, and the result area `#import-result`.

### AI mode vs Local mode — what the user sees (the explicit requirement)

**Detection & live flip.** Frontend truth is `isLocalIntelligenceMode()`
(dashboard.js:685) — already fed by the `/api/ai/heartbeat` poll (`loadClaudeHeartbeat`,
8985) and the user's forced-local toggle. The panel's two copy blocks are tagged with the
existing attributes `data-engine-claude-only` / `data-engine-local-only`, so
`setEngineScopedVisibility()` (702) flips them **live** when the key connects or drops —
zero new mode state. Backend truth is `settings.ANTHROPIC_API_KEY.strip()`
(ai_service.py:65 idiom). The two are bridged the same way signals do it
(dashboard.js:698): when `isLocalIntelligenceMode()` is true the upload URL gets
`&force_local=true`, so a user who forced local mode is never surprised by a Claude call.

**Panel copy — Local mode** (pill: `Local Intelligence` with the cpu icon, matching the
`tip-variant="local"` styling):

> **Import holdings — template mode.**
> Uses the exact FolioOrb format — the same columns Export CSV gives you:
> `ticker, shares, avg_cost, is_watchlist, hold_class, notes`. Plain numbers, no
> currency symbols, up to 200 rows.
> *Have a raw brokerage export instead? Connect Claude in Settings and I'll map the
> columns for you.*

**Panel copy — Claude mode** (pill: `Claude assist`, stars icon):

> **Import holdings — Claude assist.**
> Drop in almost any brokerage CSV — I'll map `Symbol`/`Qty`/`Cost`-style columns onto
> the FolioOrb format. Every row still passes the same strict checks before it
> touches your book. Clean template files skip Claude entirely — zero tokens.

Honest and witty, no overpromising: "almost any", and the strict-checks sentence keeps
the trust story straight. This copy is the answer to "what does turning Claude on buy
me for imports": *wider input, same rules*.

**Messy CSV in Local mode** (the 400 with `unrecognized_columns`): the result area shows
non-scary guidance, not a failure wall —

> **Some columns weren't recognized:** `Symbol`, `Qty`, `Market Value`.
> Two ways forward: match the template (Export CSV or Download template shows the exact
> format), or connect Claude in Settings — Claude maps almost any brokerage export onto
> it. Nothing was imported.

**Claude fallback** (`mode === "claude_fallback"`, amber note above the results):

> Claude assist didn't answer in time, so I ran the strict template check instead — the
> results below follow the exact-format rules.

### Import flow (dashboard.js)

New functions near the manager code (~10300): `initCsvImport()` (bind buttons, wire the
file input), `handleImportFile(file)`, `renderImportResult(report)`,
`downloadHoldingsTemplate()` (JS `Blob` — header + one position row + one watchlist
row; no new route). Upload:

```js
const fd = new FormData();
fd.append("file", file);
const url = "/api/portfolio/holdings/import?portfolio_id=1"
    + (isLocalIntelligenceMode() ? "&force_local=true" : "");
const res = await fetch(url, { method: "POST", body: fd });   // browser sets the boundary
```

Single-flight guard (`_importInFlight`) + busy button ("Importing…" with the
`manage-lucide--spin` loader, mirroring `setAddHoldingBusy` 10881). Clear the file
input's value after each attempt so re-selecting the same file re-fires `change`.

### Result summary

- **Both modes:** headline counts line — `3 added · 1 skipped · 2 errors` — then a
  per-row list (`row 4 · 26-MAR — Couldn't find ticker…`), first ~8 rows with a
  `+N more` expander; `escapeHtml` everything (values are user CSV).
- **Claude mode adds** the Senpai recap above the counts when `summary` is non-null:
  an `.import-senpai-note` line with the orbit icon, quiet italic styling. Local mode
  shows counts only — that's the visible difference, and it matches the rest of the
  app (Local = the facts, Claude = the narration on top).
- `added > 0` ⇒ `showToast("Imported 3 holdings", "success")`,
  `loadManageHoldings({ preserveExisting: true })`, and
  `refreshPortfolioMutationInBackground()` — identical post-mutation choreography to
  the add-holding handler (10981–10982).
- Optional garnish (cheap, on-brand): one new line in `DASHBOARD_SENPAI_TIP_QUOTES`
  (7976): `"Export CSV backs up your book; Import brings one home — with Claude
  connected I'll read almost any broker's export."`

### CSS (`static/css/style.css`)

`.manage-import-card` (clone `manage-add-card` tokens), `.import-mode-pill`
(local/claude variants reusing the existing local/claude accent colors),
`.import-result-row` with status coloring (`added` green / `skipped` muted / `error`
red), `.import-senpai-note`. Static layout, no animation (snappiness rule).

## Watch-outs (called out, with chosen mitigations)

1. **Per-row network validation is slow for big files.** Mitigations, in order: dedupe
   before validating (in-file + already-in-portfolio rows never hit the network); warm
   the quote cache once with the thread-pooled `get_all_quotes` (10 workers) so
   per-row `validate_ticker_symbol` reads cache; hard `MAX_IMPORT_ROWS = 200` clearly
   surfaced in panel copy and the 400 message. Worst realistic case (~200 unknown
   tickers) ≈ a few tens of seconds — acceptable for a rare bulk action, and the
   button shows a busy state throughout.
2. **Excel mangles tickers** (`MAR26` → `26-Mar`, stripped leading zeros, scientific
   notation) when users edit CSVs by hand. Decision: import stays strict — no guessing
   the original back. Mitigation: date-shaped failed tickers get the targeted error
   reason ("Excel may have reformatted the ticker — re-export the column as Text"),
   and the docs page mentions it. Claude can't fix it either (it maps columns, and
   cell corruption survives any mapping) — say so honestly if asked.
3. **Claude latency/failure mid-import.** `timeout=15.0` on the create call; any
   exception/invalid mapping ⇒ automatic strict-local fallback (`mode:
   "claude_fallback"`), UI states the fallback plainly. Cached heartbeat short-circuits
   a known-down API. The import endpoint therefore has a worst-case latency of
   ~15 s + validation, never an indefinite hang.
4. **Cost.** The remapper only fires for messy headers with a key configured — clean
   template/export files never spend a token (tested). Bounded input (≤30 cols × ≤5
   sample rows × ≤40 chars) + `max_tokens=500` + optional 120-token narration ⇒
   roughly 3–5k tokens per messy import, on Haiku. `_track_usage` feeds the existing
   cost HUD, so spend is visible, not hidden.
5. **Double-submit.** `_importInFlight` guard + disabled button; the backend is also
   naturally safe (second run dup-skips).
6. **New dependency in the frozen app.** `python-multipart` must reach the PyInstaller
   bundle; requirements.txt flows into the release build, but smoke-test an import in
   the frozen build and add a `hiddenimports` entry (spec:31) if needed.

## Tests (offline, Claude always mocked — no live API calls)

**Service — `tests/test_holdings_csv.py`:**

1. Strict parse happy path, all six columns, shuffled column order.
2. Optional columns omitted ⇒ defaults (`is_watchlist=false`, `hold_class=auto`).
3. BOM (`utf-8-sig`) stripped; cp1252 fallback decodes; NUL bytes rejected.
4. Blank lines skipped; blank-and-whitespace file ⇒ no rows.
5. `unrecognized_columns`: clean header ⇒ `[]`; `Symbol`/`Qty` listed; case/space trims.
6. Local strict numbers: `"$1,234.56"` is a row error; plain `2.5` parses.
7. `clean_cell_number`: currency symbols, thousands separators, `(50)` ⇒ `-50`,
   trailing `%`; `clean_cell_bool` variants (`Yes`, `TRUE`, `0`…).
8. `escape_csv_cell`: `=SUM(A1)`, `+1`, `-X`, `@cmd`, tab/CR get `'`-prefixed; benign
   cells untouched.
9. Export builder: exact header order, BOM present, watchlist row, note containing
   comma + quote + newline survives quoted.
10. **Round-trip:** build export from model rows → strict parse → identical values.
11. Remapper happy: patched client returns ```-fenced mapping JSON ⇒ fences stripped,
    mapping applied to *all* rows, numbers cleaned.
12. Remapper garbage: non-JSON ⇒ fallback signal (exception/sentinel).
13. Remapper invalid mapping: `ticker: null`, or value not in header ⇒ fallback.
14. Remapper API exception/timeout ⇒ fallback; `_track_usage` not corrupted.
15. Token caps: >30 columns ⇒ Claude not called; sample cells truncated to 40 chars;
    prompt contains ≤5 rows (assert row 6's marker value absent from the payload).
16. No key ⇒ remapper never touches the client (assert mock not called).
17. `process_import_rows`: in-file dup skip (with `duplicate of row N`), portfolio dup
    skip, pydantic error rows, injected-validator error rows (suggestions in reason),
    good rows returned as `HoldingCreate`s; date-mangled ticker gets the Excel hint.
18. Narration: happy ⇒ text; API failure ⇒ `None`.

**Router — `tests/test_holdings_csv_router.py`** (mount pattern of
`test_earnings_radar_router.py`: bare FastAPI + portfolio router + in-memory SQLite +
`dependency_overrides`; monkeypatch `portfolio_router.validate_ticker_symbol`,
`portfolio_router.get_all_quotes`, and the remap/narrate names in the router namespace):

19. Export 200: Content-Disposition filename, BOM + exact header line, escaped
    formula-note, watchlist row present; 404 unknown portfolio.
20. Import happy, **no key (local path)**: template CSV ⇒ 2 added, statuses/reasons in
    report, DB rows persisted with `hold_class`/`notes`/`is_watchlist` intact,
    `mode == "local"`, `summary is None`.
21. Dup-skip: pre-seeded MSFT ⇒ `skipped`; in-file second VOO ⇒ `skipped`; still 200.
22. Bad-rows report: bad ticker shape, non-watchlist `shares=0`, bad `hold_class` ⇒
    per-row errors while good rows are added (partial success, one commit).
23. Header mismatch, local ⇒ 400 with `unrecognized_columns` + `expected_columns`.
24. Oversize ⇒ 413; 201 data rows ⇒ 400 mentioning the cap; PNG content-type ⇒ 415;
    empty/header-only ⇒ 400; unknown portfolio ⇒ 404.
25. **Claude path (key mocked in):** messy header, remap mocked ⇒ `mode == "claude"`,
    rows added, `column_mapping` echoed, narration mocked ⇒ `summary` present.
26. Clean file **with** key ⇒ remapper not called, `mode == "local"` (zero-token path).
27. Remap raises ⇒ strict fallback: messy header ⇒ 400 with
    `detail.mode == "claude_fallback"`.
28. `force_local=true` with key ⇒ remapper not called.

**Wiring — `tests/test_csv_import_ui.py`** (style of `test_analytics_dashboard.py`):

29. `dashboard.js` contains `/api/portfolio/holdings/import`,
    `/api/portfolio/holdings/export`, `handleImportFile`, `renderImportResult`,
    `downloadHoldingsTemplate`; `index.html` contains `import-csv-panel`,
    `import-csv-input`, `export-csv-btn` and the `data-engine-claude-only` /
    `data-engine-local-only` pair inside the panel; `style.css` contains
    `.manage-import-card`, `.import-senpai-note`; `requirements.txt` contains
    `python-multipart`; `app/routers/portfolio.py` contains `"/holdings/import"` and
    `"/holdings/export"`.

## Implementation order + quality gate

1. `requirements.txt`: add pinned `python-multipart` (current release).
2. `app/services/holdings_csv.py` — constants, decode/parse, strict rows, cleaners,
   escape, export builder, `process_import_rows` + unit tests → green.
3. Router: `GET /holdings/export` (above the parameterized routes) → curl check.
4. Router: `POST /holdings/import` local path + router tests → green.
5. Remapper + narration in the service (mocked tests), wire into the import path with
   the fallback ladder + `force_local`.
6. Frontend: toolbar buttons, import panel with mode-tagged copy, result rendering,
   refresh hooks; CSS.
7. Wiring test; then the full gate — the bar is **stays green + stays 10/10** (repo is
   currently 504 tests / pylint 10.00):

```bash
python -m compileall -q app run.py tests && python -m pytest -q && python -m pylint $(git ls-files '*.py')
```

8. Manual pass: `python run.py` → export; re-import the export (all dup-skipped);
   hand-edit a messy header and import with no key (400 guidance, non-scary); with a
   key: messy file maps (cost HUD ticks up), clean file stays zero-token; kill the
   network mid-Claude to see the honest fallback note.

Style notes for the implementing session: thin router (logic in the service), module
docstrings, ≤100-col lines (.pylintrc), comment-light idiomatic code, broad excepts only
around the Claude/network boundaries with the repo's
`# pylint: disable=broad-except` pattern, `sanitize_for_log` on user-derived log values.

## Ship

Per standing workflow: verify green, commit to `main`, push (rebase-first). Suggested
message: `feat: CSV import/export — strict local template + Claude column remap`.
After shipping: move "Spreadsheet in, spreadsheet out" from "next up in the lab" to
shipped in README.md:96 and `docs-site/src/content/docs/roadmap.mdx:17`, add a release-notes
entry, and delete the CSV row from the `folio-future-upgrades` memory per that file's
instructions.
