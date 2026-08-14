---
title: Privacy & Data Handling
description: What FolioOrb stores locally and what, if anything, leaves your machine.
---

FolioOrb is local-first, not cloud-hosted.

| Data | Handling |
| --- | --- |
| Holdings and portfolio snapshots | Stored in local SQLite under `database/` for a source run, or the OS per-user FolioOrb data directory for the desktop app |
| Config and API keys | Stored in the same local data root as `.env`; `.env` is excluded from git and never bundled into an installer |
| Update and restore state | Stored in local `settings.json`, outside the portfolio database |
| Automatic-backup preference and daily claims | Stored in local `backup-policy.json` and claim files, separate from app settings |
| Manual Backup Vault snapshots | Stored as verified SQLite files under the local data directory; `.env` and API keys are excluded |
| Portable records ZIP | Created only when requested; contains readable Portfolio data and checksums but no settings, keys, AI caches, backups, or SQLite database |
| Browser cache | Uses `localStorage` for faster dashboard paint |
| Market data | Requested from Yahoo Finance through `yfinance` |
| Filings and the yield curve | Requested from SEC EDGAR and the US Treasury — public, keyless sources |
| Anthropic connectivity and Claude prompts | A configured key enables credential-only availability checks; Claude-backed actions send the bounded payloads described below |
| Generated AI summaries | Cached locally in SQLite for reuse and cost control |

## Security-oriented defaults

- `.env` and `database/` are intended to stay untracked by git
- CORS defaults to local origins
- API key input is format-validated client-side and server-side before being saved
- Claude is optional; the local engine remains available without an AI provider
- A manual restore is applied only before the database opens on the next launch, after a
  verified safety copy of the current database is created
- Automatic backup is off by default; when enabled it attempts at most once per local day,
  keeps seven verified automatic snapshots, and never prunes manual/update/restore backups

## What actually leaves your machine

FolioOrb has no telemetry, analytics beacon, FolioOrb cloud account, or brokerage
connection. It does make the following direct outbound requests:

1. **Yahoo Finance** — ticker, date/range, and provider query parameters for prices,
   history, company/fund fields, and headlines. FolioOrb does not send your share count or
   local database to Yahoo.
2. **US Treasury** (`home.treasury.gov`) — a public daily par-yield file used for the market
   backdrop. The request contains no portfolio context.
3. **SEC EDGAR** (`sec.gov`, `data.sec.gov`) — company ticker/CIK lookups for filings,
   financial statements, and Form 4 records. The SEC-required contact header is explained
   below; share counts and local notes are not sent.
4. **Anthropic Claude** — only after you configure a key, in two distinct cases:
   - **Availability heartbeat:** at dashboard startup and roughly every two minutes, FolioOrb
     makes a credentialed model-list request—even while the visible engine is Local. It sends
     the key for authentication but no prompt or portfolio context. **Disconnect Claude**
     clears the running client and stops this request immediately; manually removing the key
     from `.env` requires an app restart to clear the in-memory client.
   - **Prompted features:** when you invoke a Claude-backed action, the path sends only its
     bounded input:
     - Portfolio briefings, action plans, verdict cards, and analytics narration can include
       tickers, allocations, total/position value or return metrics, risk/exposure fields,
       verdict signals, and market context.
     - Per-security summaries can include the ticker/name, security type or sector, current
       market fields, range, valuation, dividend, analyst, and fund-profile metrics available
       for that security.
     - An ETF profile fallback sends the ticker, fund name, and requested constituent limit
       when Yahoo has no usable fund profile.
     - News themes send the bounded holding/headline snapshot needed to group supplied news.
     - A messy CSV remap sends column names and at most five sampled rows; each sampled cell is
       capped at 40 characters and sanitized. Its optional completion narration sends only
       added/skipped/error counts, up to three reasons, and unmapped column names. Use the exact
       FolioOrb template or Local mode if a brokerage export contains text you do not want
       sampled.
   - These are derived values, so Claude can receive portfolio context even though the SQLite
     database itself stays local. The key is not placed in a prompt. The database, `.env`,
     backups, settings files, and stored thesis text are not part of normal prompt snapshots.
5. **News thumbnail hosts** — Yahoo-supplied article thumbnails can lazy-load directly in your
   browser from a publisher or CDN. The request reveals your IP address and the requested asset
   URL to that host; FolioOrb sets `referrerpolicy="no-referrer"` so it does not send the local
   dashboard URL as an HTTP referrer. Opening an article also navigates to its publisher.
6. **GitHub** (`api.github.com`, `github.com`) — release metadata, checksums, and installer
   downloads when update checks are enabled or you request an update.

Generated Claude output and usage totals are cached locally. Local mode sends no Claude
prompts, but the credential-only heartbeat above continues until you disconnect the running
client or remove the key and restart FolioOrb.

Creating, listing, exporting, or restoring a Backup Vault snapshot—and creating a portable
records ZIP—is local file work and does not make an outbound request. Listing and verification
open closed snapshots read-only and do not create SQLite WAL/SHM sidecars. Exporting a backup
or records ZIP places a copy only at the location you choose.

A portable records ZIP is intentionally human-readable and therefore sensitive. It is not
encrypted by FolioOrb, it may include notes and thesis text, and it is not a restorable
database backup. Vault snapshots and automatic backups also remain on the same device by
default; copy a verified manual backup to separately protected storage if device loss is in
your threat model.

### The SEC contact address

The SEC requires software to identify itself with a contact address, and returns `403` to
anything that doesn't. FolioOrb sends its maintainer's address by default, so filings work
out of the box. If you'd rather speak for yourself, set `FOLIO_SEC_CONTACT` in your `.env`:

```bash
FOLIO_SEC_CONTACT=you@example.com
```

That address goes to the SEC and nowhere else. It is not a login, and no account is created.
