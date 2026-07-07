---
title: Privacy & Data Handling
description: What FolioSenseAI stores locally and what, if anything, leaves your machine.
---

FolioSenseAI is local-first, not cloud-hosted.

| Data | Handling |
| --- | --- |
| Holdings and portfolio snapshots | Stored in local SQLite under `database/` |
| Config and API keys | Stored in local `.env`; `.env` is excluded from git |
| Browser cache | Uses `localStorage` for faster dashboard paint |
| Market data | Requested from Yahoo Finance through `yfinance` |
| Claude prompts | Sent to Anthropic only when Claude features are enabled and requested |
| Generated AI summaries | Cached locally in SQLite for reuse and cost control |

## Security-oriented defaults

- `.env` and `database/` are intended to stay untracked by git
- CORS defaults to local origins
- API key input is format-validated client-side and server-side before being saved
- Claude is optional; the local engine remains available without an AI provider

## What actually leaves your machine

Two categories of outbound calls, both explicit:

1. **Yahoo Finance** — always, for prices, history, and headlines. Required for the
   dashboard to function.
2. **Anthropic Claude** — only when a key is configured and a Claude-backed feature is
   requested. No prompt is sent otherwise.

Nothing else leaves. There's no telemetry, no analytics beacon, and no third service
in between.
