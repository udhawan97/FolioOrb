# Release candidate acceptance

With this workflow version, main and version-tag pushes build candidates without publishing. Source changes can land through
protected PRs once their source and behavioral gates pass. Native release acceptance is separate.
The existing stable release and `latest-main` remain available until an accepted publication.

## Request a release candidate

Use the Release workflow on `main` for a development release, or a version tag on main history
for a stable release. Before creating a new tag, require its candidate commit to descend
from the integrated Phase 1 release-control commit recorded in the phase ledger. Verify
that ancestry with `git merge-base --is-ancestor <control-sha> <candidate-sha>` and inspect
the candidate workflow before tagging. Historical commits carry their historical workflow
and can still auto-publish when tagged; never create a release tag at those commits.
The tag must match `app/version.py`. Credentialed macOS signing remains
restricted to protected `main`; this change does not activate signing or expand that boundary.

For a build-only rehearsal, leave `publish=false`. For intended publication, explicitly choose
`publish=true`. That run builds both platforms, stages one candidate, and waits at the
`release-publication` environment. The owner must accept that run's bytes before approving it.
A prior build-only rehearsal is useful evidence but cannot authorize a fresh build.

```sh
gh workflow run release.yml --ref main -f publish=true
```

Select signing/notarization inputs only under the corresponding signing runbooks. This command
requests a candidate; it does not establish acceptance. Automated runs must never approve their
own deployment, infer approval from silence, or waive missing native evidence.

## Inspect and test the exact candidate

1. In the **Stage exact release candidate** job summary, record the source SHA, run ID,
   run attempt, candidate artifact ID, download URL, and manifest SHA-256.
2. Download that artifact using its displayed immutable ID or URL. Its name is
   `release-candidate-<run-id>-1`. Keep it in an isolated acceptance directory.
3. Independently verify `candidate.json` against the summary digest and verify both installers
   against `SHA256SUMS.txt`. The directory must contain exactly the manifest, checksum list,
   one DMG, and one EXE. Do not execute artifacts before checking their identity.
4. Test those exact installers on macOS and Windows using disposable profiles and controlled
   installation destinations. Record OS/runtime, install/start, relevant changed workflows,
   update/rollback, data preservation, accessibility, and signature/notarization outcomes when
   claimed. Use fictional data and dummy credentials. A successful CI smoke or hash check is
   not evidence of native acceptance.
5. Save a sanitized acceptance record tied to the source SHA, run ID/attempt, artifact ID,
   manifest digest, and both installer hashes. Include exact expected/actual outcomes and
   blockers; attach or link that record when the owner approves the pending environment.

The checked-out `packaging/release_candidate.py` can verify the downloaded directory. Set
`GITHUB_SHA`, `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT=1`, `CHANNEL`, `APP_VERSION`, and `ASSET_TOKEN`
to the values independently read from that run's summary, then run:

```sh
python packaging/release_candidate.py verify /path/to/candidate --digest <summary-manifest-sha256>
```

Do not derive the expected digest from the downloaded file itself. Approval authorizes
publication; the acceptance record supplies the test evidence.

## Publish without rebuilding

After owner approval, the protected job downloads the same artifact ID and checks the accepted
manifest digest, live run identity, exact file allowlist, installer sizes/hashes, and current
successful source checks. No installer is rebuilt, repackaged, or re-signed after acceptance.
An optional Minisign signature may be added to the unchanged checksum list.

Stable publication also re-resolves the remote tag after approval, including annotated tags,
and requires it to identify the accepted source SHA. Existing stable releases cannot be
overwritten. Development publication updates the established rolling `latest-main` channel.

After publication, verify the tag, release metadata, downloaded installer hashes, optional
signatures, and public download surface. Source merge, native acceptance, publication, and
website verification are separate ledger entries.

## Reject, expire, or retry

Reject or cancel if any required acceptance fails. Candidates expire after 30 days; unavailable
or modified bytes fail closed. A pending publication run occupies its release concurrency group;
cancel a declined or abandoned run so subsequent runs can proceed.

Do not use **Re-run jobs** for candidate staging or publication. Build-only staging also
requires attempt 1; start a fresh workflow for any transport rehearsal retry. Both the publish job gate and the verifier reject
attempts after 1, including a failed-job rerun that reuses earlier successful preparation outputs.
Start a fresh workflow, record its new identity, and repeat acceptance for its newly built bytes.
A changed commit, installer hash, manifest, or run is a new candidate.

## Repository protection

Before publication, verify `release-publication` has the owner as a required reviewer, admin
bypass disabled, and deployment policies limited to the `main` branch and `v*` tags. Self-review
is permitted for this solo-owner repository; agents must not exercise that permission. Preserve
existing signing environments. Missing or changed protection is a release blocker.

GitHub documents [environment approval rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
and [immutable uploaded artifacts](https://github.com/actions/upload-artifact).
