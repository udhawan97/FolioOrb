---
title: Privacy & Data Handling
description: What FolioOrb stores locally and what, if anything, leaves your machine.
---

FolioOrb is local-first, not cloud-hosted.

| Data | Handling |
| --- | --- |
| Holdings and portfolio snapshots | Stored in local SQLite under `database/` |
| Config and API keys | Stored in local `.env`; `.env` is excluded from git |
| Update and restore state | Stored in local `settings.json`, outside the portfolio database |
| Manual Backup Vault snapshots | Stored as verified SQLite files under the local data directory; `.env` and API keys are excluded |
| Browser cache | Uses `localStorage` for faster dashboard paint |
| Market data | Requested from Yahoo Finance through `yfinance` |
| Filings and the yield curve | Requested from SEC EDGAR and the US Treasury — public, keyless sources |
| Claude prompts | Sent to Anthropic only when Claude features are enabled and requested |
| Generated AI summaries | Cached locally in SQLite for reuse and cost control |

## Security-oriented defaults

- `.env` and `database/` are intended to stay untracked by git
- CORS defaults to local origins
- API key input is format-validated client-side and server-side before being saved
- Claude is optional; the local engine remains available without an AI provider
- A manual restore is applied only before the database opens on the next launch, after a
  verified safety copy of the current database is created

## What actually leaves your machine

Every outbound call, and nothing else:

1. **Yahoo Finance** — always, for prices, history, and headlines. Required for the
   dashboard to function.
2. **US Treasury** (`home.treasury.gov`) — the daily par yield curve behind the market
   backdrop. A public file; no key, and nothing about you is sent.
3. **SEC EDGAR** (`sec.gov`, `data.sec.gov`) — filings, financial statements, and insider
   (Form 4) records for the companies you hold. Public record, no key. See the
   contact-address note below.
4. **Anthropic Claude** — only when a key is configured and a Claude-backed feature is
   requested. No prompt is sent otherwise.
5. **GitHub** (`api.github.com`, `github.com`) — only to check for and download updates.

What every one of these has in common: the request carries a ticker or a date, never your
holdings, your share counts, or anything about your positions. There's no telemetry, no
analytics beacon, and no third service in between.

Creating, listing, exporting, or restoring a Backup Vault snapshot is local file work and
does not make an outbound request. Exporting a backup places a copy only at the location you
choose.

### The SEC contact address

The SEC requires software to identify itself with a contact address, and returns `403` to
anything that doesn't. FolioOrb sends its maintainer's address by default, so filings work
out of the box. If you'd rather speak for yourself, set `FOLIO_SEC_CONTACT` in your `.env`:

```bash
FOLIO_SEC_CONTACT=you@example.com
```

That address goes to the SEC and nowhere else. It is not a login, and no account is created.
