# macOS notarization — activation

FolioOrb's release pipeline includes dormant Phase 3 support for submitting the
Developer ID-signed app and DMG to Apple's notary service, requiring an
`Accepted` result, stapling both tickets, and checking the stapled artifacts
with Gatekeeper before upload.

This is readiness, not proof that notarization is active. Public downloads and
documentation must continue to say **not notarized** until a real build-only
rehearsal passes and the exact downloaded artifact is accepted.

## Prerequisite

Complete the [Developer ID signing rehearsal](MACOS_SIGNING.md) first. A
notarization run fails before building when Developer ID signing is not active
in the same run. Phase 3 never accepts an ad-hoc-signed app.

## One-time activation

1. Create an App Store Connect team API key authorized for Developer ID
   notarization. Download its `AuthKey_<KEY_ID>.p8` file once and keep it out of
   the repository.
2. Store the base64-encoded `.p8` as the Actions secret
   `MACOS_NOTARY_PRIVATE_KEY`:

   ```bash
   base64 -i AuthKey_ABCDEFGHIJ.p8 | gh secret set MACOS_NOTARY_PRIVATE_KEY
   ```

3. Record the key ID (at least 10 uppercase alphanumeric characters) and issuer
   UUID as repository variables:

   ```bash
   gh variable set MACOS_NOTARY_KEY_ID --body ABCDEFGHIJ
   gh variable set MACOS_NOTARY_ISSUER_ID \
     --body 01234567-89ab-cdef-0123-456789abcdef
   ```

Each submission decodes its own private-key copy into the runner's temporary
directory, rejects empty or non-PKCS#8 PEM content, parses it with OpenSSL,
removes the secret from the child process environment, and trap-deletes the
file as soon as that submission finishes. Build, smoke, Homebrew, and DMG
packaging steps never receive the decoded key.

## First notarized-build gate

Run both credentialed phases together without publication:

```bash
gh workflow run release.yml \
  --ref main \
  -f sign_macos=true \
  -f notarize_macos=true \
  -f publish=false
```

The workflow must, in order:

1. sign and verify the app with the expected Developer ID Team ID;
2. pass both frozen smoke paths;
3. submit a ZIP containing the app and require Apple's `Accepted` result;
4. require an `Accepted` submission log with no reported issues, staple and
   validate the app, then require Gatekeeper's
   `source=Notarized Developer ID` assessment;
5. place that stapled app in the DMG, sign and verify the DMG, and require a
   second `Accepted` result;
6. staple and validate the DMG, mount it read-only, and recheck the embedded
   app's ticket and Gatekeeper assessment.

Record the successful workflow run ID, then download its named artifact on a
clean Apple Silicon Mac. Resolve exactly one DMG and verify the raw-DMG checksum
that the macOS build job recorded alongside it:

```bash
RUN_ID="1234567890" # Replace with the exact successful workflow run ID.
ARTIFACT_DIR="$(mktemp -d)"
gh run view "$RUN_ID" --json headSha,event,status,conclusion,url
gh run download "$RUN_ID" --name macos-dmg --dir "$ARTIFACT_DIR"

DMG_COUNT="$(find "$ARTIFACT_DIR" -maxdepth 1 -type f \
  -name 'FolioOrb-macOS-arm64-*.dmg' | wc -l | tr -d ' ')"
test "$DMG_COUNT" = "1"
DMG="$(find "$ARTIFACT_DIR" -maxdepth 1 -type f \
  -name 'FolioOrb-macOS-arm64-*.dmg' -print -quit)"
(cd "$ARTIFACT_DIR" && shasum -a 256 --check macos-SHA256SUMS.txt)
shasum -a 256 "$DMG"

MOUNT_ROOT="$(mktemp -d)"
MOUNT_POINT="$MOUNT_ROOT/mounted"
mkdir "$MOUNT_POINT"

xcrun stapler validate "$DMG"
spctl --assess --type open --context context:primary-signature --verbose=4 "$DMG"
hdiutil attach -nobrowse -readonly -mountpoint "$MOUNT_POINT" "$DMG"
xcrun stapler validate "$MOUNT_POINT/FolioOrb.app"
spctl --assess --type execute --verbose=4 "$MOUNT_POINT/FolioOrb.app"
hdiutil detach "$MOUNT_POINT"
rmdir "$MOUNT_POINT" "$MOUNT_ROOT"
```

Record the displayed run URL, source SHA, DMG filename, and SHA-256. Confirm
both assessments say `source=Notarized Developer ID`, both frozen smoke paths
passed in that same workflow run, and the recorded checksum verifies the exact
DMG. Only then enable continuous notarization and its public claim:

```bash
gh variable set MACOS_SIGNING_ENABLED --body true
gh variable set MACOS_SIGNING_PUBLICLY_VERIFIED --body true
gh variable set MACOS_NOTARIZATION_ENABLED --body true
gh variable set MACOS_NOTARIZATION_PUBLICLY_VERIFIED --body true
```

`MACOS_NOTARIZATION_ENABLED` controls submission on normal release builds. The
separate `MACOS_NOTARIZATION_PUBLICLY_VERIFIED` variable permits release notes
to say notarization is active only when the signing acceptance gate is also
enabled. A manual rehearsal never publishes unless `publish=true` is separately
selected from `main`.

To deactivate notarization without deleting its credential:

```bash
gh variable set MACOS_NOTARIZATION_ENABLED --body false
gh variable set MACOS_NOTARIZATION_PUBLICLY_VERIFIED --body false
```

This phase changes no Windows trust claim. The separate
[Windows Authenticode signing path](WINDOWS_SIGNING.md) remains dormant until
its own exact-artifact acceptance gate passes.
