# FolioOrb scheduled implementation phases

Prepared October 20, 2026, America/Chicago. Planning baseline: `224fdac37b7860ce9d20d658ab9c38f2d91f4c26`.

Advance FolioOrb through six bounded phases: compatibility, import preview, import confirmation, data-quality explanations, review comparison, and recovery acceptance. Scheduled runs should finish one useful slice at a time, preserve financial records, and leave reproducible evidence for the next run.

This is the canonical implementation queue for this initiative. Existing shipped plans remain design history. Phase 1 source integration and acceptance-bound publication controls landed in PR 99; later product phases remain unimplemented. See the exact integration and transport receipts below. This queue alone does not authorize a release. CAPO retains its existing repository-selection priorities and release authority, subject to all gates below.

## Planning baseline evidence

- Local main and remote main matched the baseline above. The inspected recent CI, Pylint, CodeQL, Security Hygiene, Docs, and Release workflow runs succeeded at that SHA. This is historical CI evidence, not a fresh local test run or native acceptance.
- There were no open issues. Open dependency PRs [85](https://github.com/udhawan97/FolioOrb/pull/85) and [87](https://github.com/udhawan97/FolioOrb/pull/87) had failing checks. Run `38346261722` rejects NumPy 2.5.3 on Python 3.11 and shows generated-lock drift; run `38346268414` reports Pydantic 2.13.5 requiring core 2.46.5 while the PR requests core 2.50.0. Recheck before acting.
- CSV import already validates, reconciles concurrent duplicates, and commits accepted rows in `app/routers/portfolio.py:342`. A separate preview-and-confirm API is not present in the inspected route. Preserve its existing partial-success and duplicate-skip semantics.
- `portfolio_review.build_trust_center`, `portfolio_valuation.evaluate`, target plans, review exports, and verified bundles already exist. Extend these contracts; do not build a second valuation engine.
- `review_bundle.py` already freezes database/quote inputs, verifies four bounded receipts, and distinguishes integrity from authenticity. The existing `/api/review/compare` compares watchlist securities, not historical review bundles.
- Backup, restore, migration, recovery barriers, and updater tests already exist. Phase 6 extends actual journey evidence rather than claiming these mechanisms are absent.
- `.github/workflows/release.yml` runs on every main push and version tag and sets publication true for non-manual events. A documentation merge can therefore start rolling prerelease publication. Never equate a source-only intent with a source-only effect.
- The discovered local recurring job is weekly CAPO, Sunday noon America/Chicago. No independently editable Elf/Mobster configuration was found in the local automation inventory; this plan does not claim to update those systems.

## Execution rules for every scheduled run

1. Verify ownership, current instructions, worktree status, remote main, existing PRs, and the ledger below. Preserve dirty and unrelated work. Reuse an existing phase branch/PR. If another worker owns it, report the conflict instead of starting a competing implementation.
2. Read the earliest ready slice. Confirm its limitation still exists. If already satisfied, attach exact evidence and advance without manufacturing a change. A deferred dependency upgrade does not block unrelated product work on healthy main.
3. Record the base SHA, selected slice, expected changed files, acceptance cases, and recovery plan before editing. Use one slice and one PR per run by default. Estimates below are run counts for planning, not deadlines.
4. Use disposable profiles with fictional data only. Set `FOLIOORB_DATA_DIR` to a fresh temporary directory, keep `DATABASE_URL` beneath it, blank `ANTHROPIC_API_KEY`, and set `FOLIO_DISABLE_UPDATE_SCHEDULER=1` before importing the app. Use `FakeMarketData` and mocked provider/AI clients. Stub other external I/O explicitly: the market-data fixture does not disable every network path. Never inspect or mutate the user's portfolio, installed app profile, credentials, or real exports.
5. Do not invoke installers, migrations, restore, updater, or UI automation against real state. Native testing uses a disposable installation/profile and loopback server whose isolation is verified before launch. Stop if isolation cannot be established.
6. Run the phase-specific checks plus the applicable common gates. Update Graphify after code edits and corroborate its scoped query with source. Its generated files remain ignored.
7. Review the concrete slice plan before material implementation, then review the exact implementation before integration using the council procedure below. A reviewed roadmap is not approval of code that does not yet exist.
8. Inspect current branch protections and all merge/deployment triggers before pushing or merging. Use protected PR integration; never bypass checks or force-push. If merging would publish an artifact whose acceptance gates are incomplete, hold the PR. Do not weaken release workflows to get this plan through.
9. Update this ledger with commands, outcomes, SHA, PR, limitations, and next action. Distinguish planned, implemented, tested, source-merged, native-accepted, and released. No phase is complete merely because a PR exists.
10. On failure, preserve the candidate, record the root cause and next experiment, and stop that slice. On a later run, retry only with changed evidence or a materially different approach. If a blocked slice has no safe independent successor, stop useful work for this repository and report the exact dependency.

### Council procedure

Use the installed Council Review skill: exactly two full rounds with four independent reviewers per round—Evidence, Coverage, Risk, and Outcome. With limited concurrency, run reviewers sequentially. Each receives the same sanitized packet and no other reviewer's comments.

The packet must include every affected phase/slice, current source SHA, plan/diff digest, invariants, proposed interface changes, acceptance cases, test evidence, rollback, and the proposed completion report. Require a phase-by-phase verdict of APPROVE, APPROVE_WITH_NITS, or BLOCK. Round 1 challenges; revise; Round 2 confirms. Resolve valid blockers, obtain targeted acceptance for material blocker corrections, and record the reviewed digest. Re-review materially changed scope; never reuse approval across a changed implementation.

Unavailable reviewers mean the gate is blocked; do not self-certify four roles or silently waive the requirement. Retain the candidate and request an explicit user waiver or changed requirement. Review consensus supplements executable evidence.

## Phase 1 Dependency compatibility and a reliable starting point

**Value:** stop recurring incompatible dependency proposals and leave future runs a reproducible baseline. **Effort:** one or two bounded runs. **Dependency:** none.

**Slice 1A:** investigate whether current release controls can stage, accept, and publish identical artifact bytes; record the verified path or the integration/publication blocker. Refresh PR 85/87 evidence, identify constraints from package metadata and resolver output, and document each disposition. Keep Python 3.11 support. Do not simply accept NumPy 2.5.x or remove a supported matrix entry to make checks pass. Investigate Pydantic and core as one compatible pair, not independent pins. An unsupported upgrade may be explicitly deferred; closure requires proven redundancy and applicable authority.

**Slice 1B, only if justified:** group coupled dependency updates in the existing Dependabot configuration and regenerate all three desktop/release locks using the repository's pinned `uv`. Preserve unrelated resolved versions. The normal lock-generation script uses broad `--upgrade`; inspect its resolution diff and use a separately reviewed targeted refresh if needed to avoid unrelated upgrades. Do not add a new bot or rewrite dependency policy without evidence that the existing configuration causes the recurrence.

**Files:** `requirements.txt`, `requirements-*.lock`, `scripts/lock_desktop_dependencies.sh`, `.github/dependabot.yml` if present, existing CI definitions only if a genuine verification gap requires it.

**Acceptance:** fresh resolution on Python 3.11 and 3.12; all four dependency audits; lock check reproduces without diff; full offline Python and Node tests; desktop dependency installation on macOS/Windows where affected. Record the decision for each existing PR. Passing main alone does not clear either PR.

**Recovery:** revert a dependency candidate and its generated locks as a unit. Never change a published asset to repair a dependency experiment.

**Done:** compatible changes pass exact-candidate gates, or incompatible proposals are explicitly deferred with their failure evidence. Product work can proceed on a verified unchanged baseline.

## Phase 2 Read only CSV import preview

**Value:** users can inspect what a file would add before any holding changes. **Effort:** one or two runs. **Dependency:** Phase 1 baseline disposition, not completion of every possible dependency upgrade.

**Design:** extract reusable preparation from the existing import route into a service. Add a bounded preview contract containing portfolio identity, input digest, parsing/mapping mode, normalized candidate rows, per-row validation/duplicate reasons, and counts. Names are proposed; settle the precise API in the slice council. Preserve the single shared validation choke point in `holdings_csv.process_import_rows`. Translate its legacy `added` statuses/counts to `would_add` or equivalent preview language; never imply rows were saved.

Start with strict local CSV only. Here local means parsing, not necessarily ticker validation: the existing validator contacts a quote provider. If preview retains that behavior, disclose that symbols leave the device, send no notes or complete CSV, and keep provider failure explicit. Do not remove authoritative ticker validation merely to claim offline operation. Show the selected portfolio, valid additions, skipped duplicates, invalid rows, shares, cost, watchlist status, classification, and notes as escaped text. Do not silently switch to Claude. Messy-file mapping remains on the existing path until a separately reviewed preview contract can preserve its privacy boundary.

**UI:** accessible preview table/summary, keyboard focus, clear cancel/back action, bounded rendering for large files, explicit “nothing saved” state. This phase can ship as an inspect-only action with no apply button; the existing import action stays clearly labeled as immediate import.

**Tests:** existing CSV fixtures plus empty file, duplicate headers, BOM/encoding errors, size/row caps, repeated tickers, decimals/nonfinite numbers, malformed symbols, formula-like notes, wrong portfolio, empty/watchlist portfolios, provider unavailable, and cancel/reload. Verify zero holding/trade/target/snapshot writes and zero AI calls. Separate unavoidable quote-provider behavior from the no-write guarantee; local mocked acceptance must be offline.

**Files:** `app/routers/portfolio.py`, `app/services/holdings_csv.py`, a small proposed import-preview service if needed, `static/js/dashboard.js` or a focused new module, template/CSS, `tests/test_holdings_csv.py`, `tests/test_csv_import_ui.py`, runtime JS tests.

**Recovery:** remove the new inspect-only entry point; leave the existing import contract intact.

**Done:** a user can inspect and cancel a fictional CSV in actual Safari, with preserved portfolio state and clear unavailable/invalid cases.

## Phase 3 Confirm exactly the reviewed import

**Value:** a user confirms a known set of additions without stale previews, accidental replay, or silent remapping. **Effort:** two or three runs. **Dependency:** Phase 2.

**Design decisions required before code:** keep preview payloads process-local and bounded; use an opaque random token bound to the portfolio, normalized input digest, normalized proposed rows, and relevant active-holding fingerprint. Initial limits: 15-minute expiry, at most 16 outstanding previews per local process, and existing upload/row caps. Expiry/restart invalidates a preview; token material and row content never enter logs. Bind tokens to a profile/database generation that changes on restore or replacement, and invalidate all outstanding previews and receipts when that generation changes. Expired or evicted tokens are permanently non-executable; their absence must never create a new confirmation request.

Confirmation runs under the existing financial-write serialization discipline. Revalidate the portfolio, token, expiry, and fingerprint within the transaction boundary. No network or AI work occurs while holding the write lock. If relevant holdings, mapping, or proposed rows differ, reject without writes and require a fresh preview. Do not silently apply only the changed subset.

Preserve partial success deliberately: rows marked invalid/skipped during preview remain so; only the exact reviewed valid additions commit together. An unexpected conflict or failure at confirmation rolls back that confirmation and requires review again. Keep the database unique index as the final defense.

After success, retain a bounded in-process receipt for the token so same-process replay returns the same outcome without adding rows. After process restart or an unknown response, do not auto-retry or claim exactly-once across crashes. Show “outcome needs reconciliation” and compare persisted fields before allowing a new reviewed import. Before implementation, specify the reconciliation screen and user action: refresh the selected portfolio, compare every reviewed persisted field (ticker, shares, average cost, watchlist state, classification, notes, and thesis cadence), show matching/mismatching/unknown rows, and allow a new explicit preview only after the state is known. Matching records do not prove this request created them. Mismatch/unknown retains uncertainty and blocks automatic action; recovery requires the user to inspect the records before explicitly starting a new preview. A durable idempotency ledger would require a separate schema/migration decision, not an implicit addition.

**UI:** explicit confirm button, one in-flight request, progress/error states, retained preview on recoverable failure, stale-preview explanation, truthful “saved but refresh failed,” and protection against portfolio-switch responses painting another portfolio.

**Acceptance:** concurrent confirm twice; lost response before/after commit; process restart; preview and receipt eviction; profile replacement or database restore; ambiguous commit outcome; token expired/tampered/wrong portfolio; holding changed between preview and confirm; database busy; injected insert/commit failure; identical CSV re-import; saved-but-unrefreshed UI; cancellation does not promise to undo a committed request. Confirm unrelated portfolio mutations do not invalidate the selected portfolio unnecessarily.

**Files:** Phase 2 seams plus `write_serialization`, `holdings_repository`, holding-add/reconciliation logic where reusable, and focused concurrency/runtime tests. Preserve the legacy API until compatibility is explicitly resolved; do not silently change existing clients.

**Recovery:** disable the new confirm entry point without deleting holdings. Roll back source if needed; do not automatically delete successfully imported rows or restore an old database. Reconciliation is not an undo operation.

**Done:** the reviewed rows and committed rows agree, duplicates/replays are safe, and uncertain results remain explicit under injected failure.

## Phase 4 Consistent explanations for incomplete financial data

**Value:** users can tell why a displayed total excludes positions and whether two surfaces describe the same inputs. **Effort:** one or two runs. **Dependency:** verified baseline; independent of Phases 2/3 if they are blocked.

**First slice:** build a synthetic cross-surface matrix for valuation, Trust Center, target plan, review report, and exported receipts. Identify actual inconsistencies before editing. Existing coverage displays are not automatically defective.

**If a demonstrated gap exists:** reuse the valuation result and existing quality enums to expose included/expected positions, missing quotes, foreign-currency exclusions, realized-ledger exclusions, and observed timestamps where available. Keep quote observation time, fetch time, and report generation time distinct. Never invent a vendor timestamp, infer completeness from metadata alone, or treat stale data as fresh.

Use the existing Trust Center as the detailed destination from concise metric explanations. Preserve USD-only totals, GBp versus GBP distinction, watchlist exclusions, null/unknown semantics, and snapshot suppression. Do not add FX conversion, tax-lot accounting, or a new scoring algorithm.

**Acceptance matrix:** complete USD; one missing quote; all missing; foreign quotes including GBp; mixed realized currency evidence; watchlist only; empty portfolio; changed portfolio during refresh; unavailable timestamp; stale cached value. For frozen identical inputs, shown totals, exclusions, and exported receipts must agree. Different capture times must be visible rather than forced into artificial equality.

**Files/tests:** `portfolio_valuation.py`, `portfolio_review.py`, `portfolio_planning.py`, `review_bundle.py`, relevant dashboard/Review Orbit rendering; existing valuation, foreign-currency, review, planning, and bundle tests plus runtime cases. No schema change expected.

**Recovery:** revert presentation/adapter changes without rewriting history or recalculating stored facts.

**Done:** demonstrated discrepancies are resolved or the matrix proves existing behavior sufficient. A passing evidence slice can complete without a cosmetic rewrite.

## Phase 5 Compare two saved review bundles

**Value:** explain what changed between two local review records without claiming portfolio value change is investment performance. **Effort:** two or three runs. **Dependency:** Phase 4's explanation contract.

**Slice 5A:** define a narrow comparison schema and implement a pure read-only comparator on two verified local bundles. Inspect the actual v1 receipt fields first. Prefer manifest semantic keys over human-readable CSV labels. Compare financial fields only with stable semantic keys, known units, and compatible coverage; show unavailable fields explicitly. Coverage differences are independently reportable. If changed coverage prevents like-for-like numeric comparison, show both recorded values and their coverage but mark the delta unavailable/incomparable. If v1 lacks the necessary data, stop this slice and council-review a backward-compatible versioned export proposal before implementation.

Require an explicit same-portfolio confirmation: numeric portfolio IDs alone cannot establish identity across independently created profiles. Reject unsupported versions/currencies/period semantics. Permit differently dated captures only with both periods and capture times visible; do not label overlapping periods as a performance return.

Reuse bounded ZIP validation; cap each input at the current 8 MiB budget and apply a combined resource bound. Bounds must cover compressed input, per-member and aggregate decompressed bytes, member/row counts, and parsed allocations. Reuse and test existing limits rather than introducing a second archive parser; define any extra parsing limits before implementation. Never extract archive members to disk, execute embedded HTML, or render it in an iframe. Parse known CSV/JSON data defensively, validate shapes and numeric finiteness, and escape all displayed strings. Valid hashes prove internal consistency, not trustworthy authorship or true financial values.

**Slice 5B:** a file-picker comparison view in Review Orbit showing changed coverage, target allocations in basis points, and supported recorded totals with units. Include zero/one file, identical files, reversed chronology, missing fields, and invalid archive states. No automatic portfolio import, persisted local file history, provider calls, or AI uploads.

**Acceptance:** identical bundles produce no changes; expected changed fixtures produce exact deltas; foreign/missing data never become zero; different currency/identity/version fails closed; malicious archive and CSV payloads remain inert; memory bounded under maximum inputs; no DB writes or network calls. Label value delta as a value delta, never return, tax gain, or a trading recommendation.

**Files/tests:** `review_bundle.py`, a proposed pure `review_comparison.py`, `app/routers/review.py` if a local API is needed, focused Review Orbit logic/UI; existing bundle adversarial corpus plus comparison tests.

**Recovery:** remove comparison UI/service while preserving all user files and v1 verification/export compatibility.

**Done:** two compatible fictional bundles can be compared locally in Safari with truthful units, quality, identity confirmation, and failure states.

## Phase 6 Recovery journeys and release acceptance

**Value:** prove the updated workflows remain usable through upgrade, interruption, and recovery. **Effort:** one or two local runs plus platform access as needed. **Dependency:** each feature candidate individually; do not wait for the entire roadmap to evaluate a useful completed phase.

**Applicability:** define a checklist for the selected candidate. Test introduced/affected workflows and relevant existing recovery paths. Confirmation and bundle comparison are required only when implemented in that candidate. Record absent future features as `Not applicable—phase not implemented`; never classify an applicable untested gate as not applicable. Rehearse the combined journey once all corresponding features exist.

**Slice 6A:** rehearse fresh install, existing disposable-profile upgrade, applicable CSV/export/bundle journeys, manual verified backup, interrupted restore, failed update, restart, and preserved portfolio selection. Use a controlled candidate/update feed and verify the installation destination as well as profile isolation; never let a live updater feed replace an uncontrolled installation. Reuse existing migration/backup/updater mechanisms. Check that restored records, targets, trades, settings, and notes match expected fictional fixtures; compare secret file permissions using dummy values, never real credentials.

**Slice 6B:** exact artifact acceptance on macOS desktop/WKWebView and Windows/WebView2, plus actual Safari for browser workflows. Exercise keyboard-only use, focus return, readable errors, narrow layouts, reduced motion, and VoiceOver where required. Browser emulation and CI smoke do not stand in for native or assistive-technology acceptance.

**Evidence:** source SHA; dependency lock digests; artifact SHA-256; OS/runtime; synthetic scenario; expected/actual result; relevant sanitized logs/screenshots; rollback evidence. A changed artifact digest invalidates that artifact's acceptance. If Windows, signing credentials, or an accessible GUI is unavailable, mark the respective gate blocked and preserve the candidate.

**Integration and publication infrastructure gate:** Phase 1 separates source integration from publication; see [Release acceptance](../../packaging/RELEASE_ACCEPTANCE.md). Once its workflow is merged, main/tag pushes only stage candidates and do not publish. Before any explicit publication, establish a verified path to accept and publish the same artifact bytes. A branch rehearsal or matching source tree does not qualify a newly rebuilt artifact. Current builds can create fresh bytes after merge, and credentialed macOS work is restricted to protected main. If the workflow cannot safely stage, accept, and publish the same bytes, mark `Release/integration infrastructure blocked`, preserve the PR, and propose a separately council-reviewed release-control change. Do not weaken acceptance or silently equate source checks with artifact acceptance. Phase 1 establishes the staging and protected same-run acceptance path; preserve its publication-time checks in later work.

**Publication:** apply CAPO's existing release criteria only after all required gates pass. Refresh Graphify and verify a scoped query before any release build/tag/publish step; update failure blocks publication. Validate both platform assets, checksums and any claimed signatures, channel/version alignment, upgrade/rollback, README/release notes, and the actual existing Pages site. Before creating any release tag, require the candidate to descend from the integrated Phase 1 control commit recorded below and inspect its workflow; tagging historical pre-control commits can execute the old auto-publishing workflow. Never overwrite immutable stable assets or claim signing/notarization that was not verified.

**Recovery:** use the established source/artifact rollback procedure with a verified disposable safety backup. No production restore or installed-app replacement is authorized by this rehearsal.

**Done:** source integration, native acceptance, release publication, and Pages verification each have separate evidence. A release can remain blocked after successful implementation.

## Common verification gates

Use repository-defined environments and commands, refreshed from current CI at execution time:

```sh
python -m compileall -q app run.py tests
python -m pytest -q
node --test tests/js/*.test.cjs
python -m pylint $(git ls-files '*.py')
scripts/lock_desktop_dependencies.sh --check
git diff --check
```

Set the disposable-profile variables above before all Python imports or test commands. CI currently tests Python 3.11 and 3.12 and uses Node 22. Pylint accepts no messages. Dependency changes require the current four `pip-audit` runs and lock verification with pinned `uv==0.11.30`; docs-site changes require `npm ci`, build, and `npm audit --audit-level=low`. Run focused tests first, then applicable full gates once on the final candidate; rerun when changed code or unresolved failures justify it.

UI changes require actual Safari acceptance through the installed Safari Browser Use skill; native desktop changes require their target runtime. Test requirements are prospective, not claims that this planning task executed the suite.

## Run ledger

Update in place; use one row per bounded slice. Qualify recurring acceptance slices by candidate, for example `6A—<candidate SHA>` and `6B—<artifact digest>`, retaining earlier acceptance records separately. Keep evidence in the linked PR or a sanitized local run artifact, not duplicate competing roadmaps.

| Slice | State | Depends on | Next action |
| --- | --- | --- | --- |
| 1A | Source merged; transport verified | None | Preserve exact-artifact native acceptance before publication |
| 1B | Source merged; incompatible upgrades deferred | 1A | Revisit NumPy only with a Python-minimum decision; validate grouped Pydantic proposals |
| 2 | Ready for a bounded implementation run | 1A disposition satisfied | Review strict local preview contract on current main |
| 3 | Planned | 2 | Review confirmation token, transaction, and reconciliation contract |
| 4 | Planned | 1A baseline disposition | Run cross-surface synthetic quality matrix |
| 5A | Planned | 4 | Establish fields safely comparable from v1 receipts |
| 5B | Planned | 5A | Add bounded accessible comparison UI |
| 6A | Planned | Selected completed feature slice | Rehearse complete disposable-profile journey |
| 6B | Planned | 6A and exact platform artifacts | Verify native acceptance and publication gates |

For every completed attempt append: run date/time and owner; base/candidate SHA; phase and scope; plan/diff digest; two-round verdict summary; exact commands and outcomes; PR/integration state; artifact/native state; blocker/root cause; next ready action. Use `Blocked`, `Deferred with evidence`, or `Satisfied by existing behavior` when those are more accurate than `Done`.

## Schedule handoff

Append a FolioOrb-only instruction to the existing weekly CAPO prompt to read this absolute local file when FolioOrb is selected, preserve global priorities, execute one ready slice, and update the ledger. Preserve the saved cadence, active state, target chat, and notification policy. Do not modify Elf/Mobster prompts or create duplicate schedules.

The original absolute file remains the canonical queue and writable ledger even when implementation uses another checkout; read an exact committed copy only for reference and synchronize ledger changes to the original. Before updating it, re-read and preserve concurrent changes. If the canonical file is only readable, save sanitized evidence and a proposed ledger update beside the candidate, report the synchronization blocker, and do not create a second canonical roadmap. If neither the original nor a verified exact reference copy is available, report the missing plan instead of inventing its contents. Do not force a documentation merge that would trigger unaccepted release publication merely to distribute the queue.

## Planning validation

Roadmap council status: complete, with no remaining blockers. Round 1: Evidence, Risk, and Outcome approved with clarifications; Coverage blocked the future-feature acceptance dependency and artifact-publication gap. Both were corrected. Round 2: Evidence, Coverage, and Risk approved; Outcome approved with two small ledger-clarity corrections, now applied. Every reviewer assessed all six phases and the schedule handoff. The Round 2 reviewed content SHA-256 was `7c97de1856043603cc7280400fdc474808dca3e5f0c01e6ae668f187a6f82a48`; subsequent changes only surfaced the already-required Phase 1 infrastructure check, qualified candidate-specific ledger rows, and recorded this review outcome. Council approval covers the roadmap, not future implementation or releases. Source and GitHub inspection support the starting scope; implementation tests and native acceptance remain future work. The local Graphify AST index covers 314 code files; 73 non-code files were deliberately excluded, one potentially sensitive file was skipped, and diagnostics show one self-loop. Graph traversal is navigational evidence only; source was checked for the key contracts above. No graph HTML was rendered.

## Phase 1 implementation record

October 20, 2026: preserve NumPy 2.4.6 for Python 3.11 and the compatible Pydantic
2.13.5/core 2.46.5 pair. PR 85 is deferred because NumPy 2.5.3 requires Python 3.12;
PR 87 is deferred because its isolated core update conflicts with Pydantic. Dependabot
now groups the Pydantic pair and excludes NumPy version updates at 2.5+ pending an explicit
minimum-Python decision. Required checks and security auditing remain unchanged.

The release candidate separates main/tag push builds from publication. A manual publication
request stages checksummed native installers, then waits for owner review in
`release-publication`. The publishing job retrieves the immutable candidate ID, verifies the
accepted manifest and exact bytes, rejects reruns, rechecks current source checks and stable
tag identity, and refuses replacement of an existing stable release. No signing was activated.

Repository environment configuration was read back: owner `udhawan97` required, administrator
bypass disabled, deployment policies limited to the `main` branch and `v*` tags. Existing
signing protections remain unchanged. See the [acceptance checklist](../../packaging/RELEASE_ACCEPTANCE.md)
for candidate identity, native evidence, rejection, expiry and retry. Automated workers must
never approve the pending publication environment.

### Integration receipt

The control commit is `75ef9d9d6d9aff730abe7067a9491f0192b58391`, merged through
[PR 99](https://github.com/udhawan97/FolioOrb/pull/99) at `2026-10-20T05:33:29Z`.
Local main was fast-forwarded to the verified remote commit. Future release candidates must
descend from this control commit; historical commits can retain auto-publication behavior.
The PR's final head was `adbcaa8d6efa3a9296432ab22d82a38f1563a83a`, with all eight
required PR check names successful. All seven main-source check names also passed at the
control commit: Python 3.11/3.12 tests, Dependency Audit, Python 3.11/3.12 Pylint builds,
Analyze Python and repository hygiene. The publication verifier accepted their fresh
GitHub check-run JSON. PR-only Dependency Review is separately covered by PR 99.
Main CI run `39375535500`, Pylint `39375535396`, CodeQL `39375535412`, hygiene
`39375535616` and Docs `39375535404` all completed successfully.

Both design and implementation completed exactly two independent four-role council rounds,
with no unresolved blockers. The implementation review covered
`e6ba31dc88a37fb6375d7b1fdbc8d6704a28dfb5`; its baseline-to-candidate binary diff digest was
`56e48b9b4dc0e9fc928ef91a8311e0f89cb0f5c7e34b1e54df3e95508b4bceb8`.
The subsequent documentation-only correction qualified publication behavior by workflow version.
This delivery record adds evidence and queue state, not new application or release behavior.

PR 85 and PR 87 are closed with their incompatible upgrades deferred. Fresh diffs contained
only their respective single dependency-pin change; neither included independent product work.
The NumPy PR was already closed when explicit closure was attempted after integration.
The Pydantic-core PR was then closed. No manual branch deletion was requested or performed.
The four audits and ordinary required checks remain mandatory for future grouped proposals.

### Validation receipt

- Full offline `python -m pytest -q`: **1,980 passed** on Python 3.11 and again on 3.12,
  with one pre-existing Starlette deprecation warning in each. Disposable profiles, blank AI
  key, disabled updater scheduler and mocked market data were used.
- `node --test tests/js/*.test.cjs`: **115 passed**.
- `python -m compileall -q app run.py tests packaging/release_candidate.py`: passed.
- Full tracked-source Pylint plus the new helper/tests: **10.00/10**, no messages.
- `actionlint .github/workflows/release.yml` and `git diff --check`: passed.
- `scripts/lock_desktop_dependencies.sh --check`: reproduced all locks without changes.
- Four pinned-file dependency audits: no known vulnerabilities. The normal local
  `pip-audit -r requirements.txt` encountered a managed-Python `ensurepip` subprocess failure;
  the normal hosted audit and all lock audits subsequently passed in the required PR checks.
- Docs `npm ci`, `npm run build` and `npm audit --audit-level=low`: passed, 23 pages and
  zero reported vulnerabilities. The final wording correction was rebuilt successfully.
- Graphify incremental refresh succeeded; the scoped `release_candidate verify_checks verify_tag`
  query was corroborated against the helper. Generated graph files remain ignored.

### Candidate transport receipt

Build-only [run 39375069843](https://github.com/udhawan97/FolioOrb/actions/runs/39375069843)
used source `e6ba31dc88a37fb6375d7b1fdbc8d6704a28dfb5`, attempt 1. Both native builds,
the test gate and staging succeeded; signing and **publication were skipped**. The only later
source change in PR 99 was the documentation qualification above. This receipt proves the
transport path for that recorded candidate, not acceptance of newly rebuilt installers.

The immutable candidate artifact ID is `12243565524`. It was downloaded by ID and verified
against manifest digest `e9e3eb40f1d77f76b6259816a3049afdf88985278f2b1a7bf9a0e122caf6f47a`
read independently from the staging job log. The verifier accepted the exact file allowlist,
source/run identity, sizes, manifest, checksum list and both installer hashes:

| Installer | SHA-256 | Bytes |
| --- | --- | --- |
| `FolioOrb-macOS-arm64-main-e6ba31d.dmg` | `e2d7a6d838ed61650f9efb207536b9b45138b06b2e5e7f4aacef93439ac4c7d7` | 43,871,073 |
| `FolioOrb-Windows-x64-main-e6ba31d-Setup.exe` | `6cc9a1247b6c6043a0706ea5a3bda87d914bea277b18a2ecdad672b214e709b1` | 42,209,913 |

Existing release IDs, publication timestamps, asset IDs and asset update timestamps were
unchanged after the rehearsal. The artifact expires after its configured 30-day retention;
this durable receipt does not grant acceptance to a future replacement.

### Scheduled handoff and remaining gates

The existing weekly CAPO FolioOrb appendix now records control commit
`75ef9d9d6d9aff730abe7067a9491f0192b58391`, the historical-tag ancestry restriction,
protected same-run acceptance and the prohibition on automatic deployment approval.
Readback confirmed all saved fields except prompt/update timestamp were preserved, including
Sunday-noon cadence, active state and target chat; other repository routing was preserved.
The next ready slice is Phase 2, read-only CSV preview, subject to a fresh plan council and
current-main checks. Phase 4 remains independently eligible under the queue's priorities.

No Phase 2+ product feature, native installer acceptance, signing activation or software release
was performed. The publication path is configured and its transport verified; actual publication
has not been exercised. Native/OS/accessibility evidence and owner approval remain required
for any intended release. A source merge never substitutes for those gates.
