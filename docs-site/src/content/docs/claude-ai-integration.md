---
title: Claude AI Integration
description: How the optional Claude layer works, what it costs, and how it falls back.
---

FolioSenseAI treats Claude as an enhancement layer, not a dependency. The distinction
matters enough that it's worth spelling out exactly how it works.

## What Claude adds

- Action plan thesis text on top of the deterministic buckets
- Portfolio briefings summarizing overall state in plain language
- News themes synthesized across headlines
- Richer per-holding insight copy

## What never depends on Claude

Verdicts, scenarios, exposure, analytics, and fallback summaries all run on **Local
Intelligence** — a deterministic engine that's always on, whether or not a key is
configured. If Claude is unreachable or unset, the dashboard degrades to local output
rather than showing an error.

## Cost visibility

Once a key is connected, the dashboard tracks live token usage for the running process:

- Actual input/output tokens accumulated this session
- Actual cost in USD
- A predicted per-run cost so you know what a full scan costs before you click refresh

## Caching

Claude responses are cached in SQLite where appropriate. Refreshing a tab does not
automatically mean paying for another model call — cached output is reused until it's
stale enough to warrant a fresh one.

## Model

FolioSenseAI currently calls `claude-haiku-3-5` via the Anthropic SDK, chosen for the
latency and cost profile of a dashboard that expects frequent refreshes.
