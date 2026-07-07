---
title: Optional Claude Setup
description: Connect an Anthropic API key to unlock Claude-powered narration.
---

FolioSenseAI works fully without Claude. Local Intelligence handles verdicts, scenarios,
exposure, and fallback summaries on its own. Add an Anthropic key when you want richer
action plans, portfolio briefings, news themes, and insight copy.

## Add a key from the dashboard

1. Click the brand mark in the dashboard nav.
2. Paste a valid `sk-ant-*` key.
3. Save.

The dashboard validates the key format client-side and server-side, writes it to `.env`,
and reconnects Claude — no restart required.

## Add a key manually

Set the following in `.env` and restart the server:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

## What changes when Claude is connected

- Action plans get Claude-written thesis text on top of the local buckets
- Portfolio briefings and news themes become available
- The cost HUD starts tracking real token usage and live spend for the session
- [Senpai](/meet-senpai/) gets noticeably more pleased with itself

## What stays the same either way

- Verdicts, scenarios, exposure, and analytics — all computed locally, always available
- Your portfolio database and `.env` — both stay local regardless of whether Claude is connected
