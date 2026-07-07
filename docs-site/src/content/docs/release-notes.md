---
title: Release Notes
description: What's new in FolioSenseAI, release by release.
---

The full changelog lives in
[`RELEASE_NOTES.md`](https://github.com/udhawan97/FolioSenseAI/blob/main/RELEASE_NOTES.md)
in the repository. Highlights of the current release below.

## v4.1 — The Dashboard Finally Knows Its Own Key

- **In-dashboard API key configuration** — paste a Claude key from the nav, validated and
  written to `.env`, reconnected without a restart
- **Live token cost tracking** — the cost HUD now shows real accumulated input/output
  tokens and actual spend instead of a cache-based estimate
- **First-click holding expand** — rows expand their intelligence panel on the first
  click, with auto-refresh keeping prices current
- **Overview sector graph rework** — proportional weighted fills instead of absolute
  percentage bars, plus an overflow note when more sectors are held than the strip can show
- Assorted fixes: font resize regression, a scroll-interception bug, and ticker
  management now triggering a fresh quote load without a full reload

See the full [`RELEASE_NOTES.md`](https://github.com/udhawan97/FolioSenseAI/blob/main/RELEASE_NOTES.md)
for prior versions and complete technical detail on each change.
