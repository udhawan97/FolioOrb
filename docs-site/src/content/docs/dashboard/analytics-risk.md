---
title: Analytics & Risk
description: Performance, risk, exposure, and signal analytics across five sub-tabs.
---

The Analytics tab covers the questions Overview doesn't have room for:

| Sub-tab | What it shows |
| --- | --- |
| Performance | Historical portfolio value, benchmark comparison, drawdown |
| Risk | Volatility, beta, and risk decomposition across holdings |
| Exposure | Sector tilt, concentration, and how "diversified" your portfolio actually is |
| Signals | Aggregated verdict and confidence spectrum across all holdings |
| Market Context | Regime classification and how it's shaping the rest of the analytics |

Charts are rendered with Chart.js and loaded lazily, so the Analytics tab doesn't cost
anything until you actually open it.

## Reading the confidence spectrum

Verdicts aren't binary. A "Hold" with high confidence and a "Hold" with low confidence
mean different things — the confidence spectrum view is where that distinction actually
becomes visible instead of getting flattened into one label.

## Reading exposure

Exposure analytics exist specifically to answer the "is this actually diversified"
question. A portfolio can look balanced by position count and still be one sector-wide
bet — this is the view that will tell you if that's what's happening.
