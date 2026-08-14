---
title: Optional Claude Setup
description: Connect an Anthropic API key to unlock Claude-powered narration.
---

FolioOrb works fully without Claude. Local Intelligence handles verdicts, scenarios,
exposure, and fallback summaries on its own. Add an Anthropic key when you want richer
action plans, portfolio briefings, news themes, and insight copy.

## Add a key from the dashboard

1. Click the **key icon beside the FolioOrb brand** in the dashboard nav.
2. Paste a valid `sk-ant-*` key.
3. Save.

The dashboard validates the key format client-side and server-side, writes it to `.env`,
and reconnects Claude — no restart required.
It then checks Anthropic. If that live check fails, the key remains saved, the panel stays
open with an unreachable message, and Local Intelligence keeps running.

Once a key is configured, FolioOrb sends a credentialed model-availability check to
Anthropic at startup and roughly every two minutes, even while the visible engine is Local.
That heartbeat contains no prompt or portfolio context. Use **Disconnect Claude** in the key
panel to clear the in-memory client and stop it immediately. If you remove the key manually
from `.env`, restart FolioOrb so the running client and heartbeat are also cleared.

## Add a key manually

Set the following in `.env` and restart the server:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

## What changes when Claude is connected

- Action plans, verdict cards, holding summaries, analytics tips, and portfolio briefings can
  add Claude-written narration on top of local calculations
- News themes can group the bounded headlines already supplied by the app
- ETF profile fallback can ask Claude for a ticker/name seed when Yahoo has no fund profile
- Messy CSV import can request bounded column mapping and a counts-only completion recap
- The cost HUD starts tracking real token usage and live spend for the session
- [Senpai](../../meet-senpai/) gets noticeably more pleased with itself

## What stays the same either way

- Verdicts, scenarios, exposure, and analytics — all computed locally, always available
- Your portfolio database and `.env` — both stay local regardless of whether Claude is connected
