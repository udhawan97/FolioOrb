# Phase 5A: saved-review comparison contract

A saved Review Orbit ZIP can be verified but could not be compared with an earlier
capture. This slice supplies the pure comparison service for the later Phase 5B
picker. It adds no UI, route, database write, provider request, migration or bundle
format change. The existing v1 exporter and verifier remain compatible.

```python
from app.services.review_comparison import compare_review_bundles

result = compare_review_bundles(
    before_bytes, after_bytes, same_portfolio_confirmed=True,
)
```

Callers must obtain explicit confirmation that both files describe the same
portfolio. Matching local IDs alone cannot establish that across independent
profiles. Both IDs must also match. Inputs are bytes already supplied by the
caller; the service never opens paths or extracts files.

## Supported facts

- Both recorded periods and UTC capture times remain visible. V1 month/quarter
  means a 31/92-day review window. Reversed capture chronology requires swapping
  the inputs; the service never silently reorders them.
- `known_value` compares the recorded USD amount from `current/known_value` in the
  review CSV. The target receipt must agree. An explicit decimal context isolates caller precision, exponent limits and traps.
  Decimal strings preserve cents; a
  missing value is `null`. Gains, cost basis, returns, FX and forecasts are outside
  this schema. Value changes can include holdings/cash changes and **are not a
  return, tax gain or trading recommendation**.
- A numeric delta requires complete, matching price coverage with non-null equal
  counts and explicit empty price-exclusion lists. Manifest qualities, the prices
  area, both CSV valuation receipts, and price-specific exclusions must agree.
  Missing evidence makes the delta unavailable/incomparable; contradictory
  present evidence rejects the input. Both recorded values remain visible when
  coverage differs. Non-price coverage changes are reported independently.
- Saved targets join by ticker and use whole basis points. Added, removed or
  unassigned weights have no numeric delta; absent values never become zero.
- `coverage` preserves semantic trust areas and quality. A missing field/area is
  unavailable, never inferred complete. Aggregate missing tickers can describe
  thesis/fundamental gaps and are not treated as missing prices.

Successful results have `ok: true`, `comparison_schema_version: 1`, `before`,
`after`, `known_value`, `targets`, `coverage`, and `changed`. The last flag concerns
compared facts, not a different capture timestamp. `integrity_only`,
`integrity_note` and `value_note` must remain visible in Phase 5B. Valid hashes prove
internal consistency, not authorship or financial truth. Use text-only rendering
and normal output escaping; never render embedded HTML.

Failures have `ok: false`, a stable `code`, and a sanitized `message`. Input-specific
failures identify `bundle: before|after`. Codes are `confirmation_required`,
`identity_mismatch`, `unsupported_format`, `unsupported_currency`,
`unsupported_period`, `period_mismatch`, `reversed_chronology`, `invalid_bundle`,
`invalid_receipt`, and `size_limit`. Archive failures also provide a bounded
`validation_code`; for example a noncanonical ZIP envelope maps to `invalid_bundle`
with `validation_code: unsupported_envelope`. Valid but incomparable values are
successful parsing results, not invalid files.

## Parsing envelope

The shared verifier retains its existing 8 MiB compressed and aggregate expanded
limit per bundle and exactly five fixed members. Comparison adds a 64 KiB central
directory bound **before** `ZipFile` allocates directory entries. It accepts the
v1 exporter's conventional single-disk, comment-free, non-ZIP64 envelope and checks
both declared entry counts and actual members. Declared counts alone are not safe.

Comparison further caps manifest JSON at 64 KiB before parsing; each interpreted
CSV at 2 MiB, 4,096 rows, eight cells per row and 4,096 characters per cell; targets
and ticker lists at 2,000 entries. JSON duplicate keys/nonfinite values, duplicate
interpreted CSV keys, invalid ticker shapes, and malformed present facts fail
closed. USD text is at most 32 characters, two decimal places and magnitude
1 quadrillion; weights are integers from 0 to 10,000 bps. Counts are integers from
0 to 1 billion or unavailable. General history counts may be null.

The two-input byte limits are separately 16 MiB compressed and 16 MiB expanded,
plus parser/result overhead. Snapshots are parsed sequentially; unused member
bytes are released before loading the second file. Tests measure accepted pairs
and rejected metadata/CSV/JSON amplification against a 96 MiB traced-allocation
budget including caller-owned inputs. This is regression evidence, not an OS
process-memory guarantee. Unusually large or noncanonical legacy bundles can
remain verifiable while being unsupported for comparison.

## Verification, delivery and rollback

The plan received two four-role council rounds before implementation; reviewed
plan SHA-256: `fda878f8c2e783c939203e4e80ffff9df16f64c05d988850159795f1c2c7f011`.
Use only disposable profiles and fictional fixtures. Run comparison and legacy
bundle/router tests, the full Python 3.11/3.12 suites, compileall, Node contracts,
Pylint, lock reproduction, dependency audit, refreshed Graphify and exact-head
hosted checks. The implementation council and protected integration are separate
from the plan gate; current delivery evidence belongs in the canonical queue/PR.

Rollback is a reviewed source revert. No data migration or financial-write replay
is needed. Phase 5B must still provide accessible local file selection, explicit
identity confirmation, safe text rendering, all error/unavailable states and
actual Safari acceptance. Native macOS/Windows artifact acceptance and protected
owner publication approval remain independent release gates.
