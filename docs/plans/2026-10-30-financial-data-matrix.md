# Phase 4: financial-data consistency matrix

Owner: `capo-phase4-20261030`. Base: `88c8ef4b7ada91faeb128df6b7c923bea4322d29`.
The authoritative queue and run ledger remain at
`/Users/umang/developer/github/FolioOrb/docs/plans/scheduled-update-phases.md`.

## User problem and reproduced gaps

A fictional book with one fully priced USD position and two unsupported realized
records has a known value of $40 and partial valuation. The valuation service
already excludes and counts those realized records. Trust Center, the target
plan, review report and their receipts did not explain the partial result;
report copy incorrectly blamed price coverage.

A second probe captured identical financial inputs at two generation times.
Report payload times differed, but their standalone CSVs were identical because
the CSV omitted generation time. Generation time cannot establish quote freshness.

Baseline probes used new disposable profiles and fictional in-memory databases.
All table snapshots remained unchanged. Initial timestamp/cache rows in the broad
probe were placeholders; controlled-clock and cache acceptance are separate tests.

## Bounded implementation

- Add an executable matrix across valuation, Trust Center, target plan, review
  report and the actual four bundle receipts. Reuse the existing shared services.
- Propagate `excluded_realized_trade_count` and `realized_data_quality` from the
  existing valuation result. The count is **all-time**, not period-specific.
- Explain unsupported realized currency or price provenance in Trust Center,
  review and target screens and CSV/HTML receipts. Label the combined quality
  "Valuation coverage" and preserve all availability, drift and snapshot gates.
- Add existing report generation time to standalone report CSV. Preserve bundle
  format v1, member names, manifest schema, hashing and integrity verification.
- Preserve older payloads: absent coverage fields remain absent, rather than
  becoming an invented zero or complete result.

No financial math, foreign exchange conversion, tax lots, scoring, stored facts,
schema, dependency, version, workflow or signing changes are in scope.

## Acceptance matrix

| Case | Required evidence |
| --- | --- |
| Complete USD | Same known total and complete valuation across surfaces; snapshot eligible |
| One missing quote | Named missing position; subtotal only; no drift/full metrics or snapshot |
| All missing | Known subtotal zero remains distinct from unavailable full value |
| Foreign including GBp | Preserve pence spelling/native values; exclude foreign prices from USD totals |
| Mixed realized evidence | Retain trusted USD gains; disclose all-time exclusions, including an old fact outside the period |
| Watchlist only | Research rows stay outside owned-position totals and target eligibility |
| Empty | Genuine zero/empty semantics; no invented missing positions |
| Unavailable timestamp | Report generation never becomes quote observation or fetch time |
| Cached older value | Controlled cache clock reuses a fictional quote while capture time changes |
| Portfolio switch during refresh | Navigation and cache identity keep an old response out of the new book |

Freeze identical database and quote inputs for comparisons. The bundle obtains one
quote response set and stamps all receipts consistently. Separate captures must
remain distinguishable in report CSV, HTML, Trust CSV and target CSV. Current quote
contracts do not provide reliable observation/fetch timestamps; those remain
unavailable. Coverage is not freshness evidence.

Every read-only surface must preserve the complete database snapshot. A separate
explicit snapshot test permits the existing write only for complete valuation.
Other-portfolio distractors and an excluded sale older than the period guard scope.
Tests deny sockets, HTTP and AI calls and use the existing fake market-data fixture.

## Gates and recovery

Both plan council rounds have four independent roles, with capture metadata,
all-time labels, legacy-field semantics and fresh-profile requirements reconciled.
The reviewed private plan digest is
`35485294e3de0d4ca0387c7fe3aae53caa631536f194e8112b358dda01e2c37c`.
This document restates the same accepted scope in readable form.

Before integration: fresh implementation council with two four-role rounds;
full isolated Python tests, Node tests, compileall, Pylint 10 with no messages,
diff-check, four ordinary dependency audits, generated-lock verification,
Python 3.11/3.12 and Node 22 hosted gates, docs build/audit, Graphify update/query,
and actual Safari acceptance against verified disposable source state.

Recheck exact head, current main, required checks, protections and deployment
triggers before a normal protected PR merge. Verify ancestry and post-main checks
and verify existing Pages delivery separately. Never approve publication automatically.
No native installer, physical-keyboard or VoiceOver acceptance is implied.

Recovery reverts adapter/presentation changes without deleting imported holdings,
rewriting history or restoring an old database. If a gate fails, preserve the
candidate and its evidence. Native acceptance and software publication stay separate.
After verified Phase 4 delivery, Phase 5A must establish safely comparable fields
from v1 receipts under its own plan and council; no historical comparison is added here.
