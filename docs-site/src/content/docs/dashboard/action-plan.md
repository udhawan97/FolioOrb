---
title: Action Plan
description: Bucketed portfolio moves synthesized from verdicts, analytics, and news.
---

The Action Plan pulls together everything else in the dashboard — holding verdicts,
exposure analytics, and news themes — into bucketed moves: what to hold, what to
consider adding to, what to trim, and what to consider exiting.

Each bucket includes:

- The positions in it and why
- A priority ordering within the bucket
- Regime context — what's driving the recommendation right now

## Local vs. Claude-enhanced

The bucketing logic itself is deterministic and runs locally. With Claude connected, each
bucket also gets narrative thesis text explaining the reasoning in plain language. Without
Claude, you still get the buckets and priority ordering — just without the prose.

Refreshing the Action Plan re-evaluates against current holdings and market data; Claude-
generated thesis text is cached, so a refresh doesn't automatically mean a new model call.
