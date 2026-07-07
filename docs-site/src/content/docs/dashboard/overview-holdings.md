---
title: Overview & Holdings
description: The core dashboard workflow for tracking and understanding your holdings.
---

## Overview

The Overview tab is the first thing you see: portfolio value, daily P&L, sector
breakdown, and a market regime briefing. It's built for a five-second read — is the
portfolio up, down, and by roughly how much, before you've even decided to look closer.

## Holdings

The Holdings tab is where the verdict engine lives. Each position gets:

- A **Hold / Add / Trim / Exit**-style verdict
- A **confidence** level and **time horizon**
- **Scenario context** — what would need to change for the verdict to flip

Rows expand on the first click (no more double-clicking out of habit) and auto-refresh
keeps prices current without a manual reload.

## Holding intelligence

Expanding a ticker surfaces deeper context:

- Peer-relative positioning within its sector
- Event flags (earnings, dividends, and other calendar items)
- Contribution breakdown — how much of your P&L this position is actually responsible for
- Equity or ETF-specific detail depending on the holding type

None of this requires Claude. It's all part of Local Intelligence, running deterministically
against live market data. Claude, when connected, adds narration on top — not a replacement
for the underlying numbers.
