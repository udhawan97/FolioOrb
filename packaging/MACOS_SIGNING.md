# macOS Developer ID signing — activation

FolioOrb's release pipeline includes dormant support for signing both the `.app`
bundle and its `.dmg` with an Apple **Developer ID Application** certificate.
Signing is deliberately disabled by default, so forks and ordinary `main` builds
continue to produce the same ad-hoc-signed artifacts without private credentials.

This is Phase 2 readiness, not proof that Phase 2 is live. Keep the README,
website, install guide, and release page labelled unsigned until a real workflow
run produces artifacts that pass the checks below.

## One-time activation

1. Join the Apple Developer Program and export the **Developer ID Application**
   certificate plus its private key as a password-protected PKCS#12 (`.p12`)
   file. Do not use a development or Apple Distribution certificate.
2. Store the base64-encoded `.p12` as the Actions secret
   `MACOS_DEVELOPER_ID_CERTIFICATE`:

   ```bash
   base64 -i DeveloperIDApplication.p12 | gh secret set MACOS_DEVELOPER_ID_CERTIFICATE
   ```

3. Store the export password as `MACOS_DEVELOPER_ID_PASSWORD`:

   ```bash
   gh secret set MACOS_DEVELOPER_ID_PASSWORD
   ```

4. Record the 10-character Team ID printed in the certificate identity as the
   repository variable `MACOS_DEVELOPER_TEAM_ID`:

   ```bash
   gh variable set MACOS_DEVELOPER_TEAM_ID --body ABCDE12345
   ```

Do not enable continuous signing yet. First run the build-only rehearsal below.
The workflow fails closed when signing is requested but either secret is absent,
the certificate cannot be decoded or imported, or the temporary keychain does
not contain exactly one valid `Developer ID Application` identity for that Team ID.

## What an activated credentialed run is designed to enforce

- The `.p12` exists only in the runner's temporary directory and is deleted by
  the importing step's exit trap.
- The signing identity lives in a temporary keychain that is deleted even when
  a later build step fails.
- PyInstaller signs collected Mach-O binaries with the hardened runtime and the
  checked-in minimal entitlements file.
- The final repaired `.app` is sealed again and must pass
  `codesign --verify --deep --strict` before its frozen smoke tests run.
- The generated `.dmg` is separately signed, passes `hdiutil verify`, and is
  mounted so its embedded app signature and Team ID are rechecked before upload.
- Developer ID signing alone still says **not notarized**. Notarization is a separate Phase 3
  gate and must not be inferred from a valid signature. The
  dormant [Phase 3 rehearsal](MACOS_NOTARIZATION.md) starts only after this
  signed-build gate passes.

## First signed-build gate

Run a manual build without publication. This works from a feature branch and
uploads ordinary workflow artifacts, but it cannot move `latest-main`:

```bash
gh workflow run release.yml \
  --ref main \
  -f sign_macos=true \
  -f publish=false
```

Download the exact macOS artifact from that run and verify on a clean Apple
Silicon Mac:

```bash
DMG=FolioOrb-macOS-arm64-*.dmg
MOUNT_POINT="$(mktemp -d)"
hdiutil attach -nobrowse -readonly -mountpoint "$MOUNT_POINT" $DMG
codesign --verify --deep --strict --verbose=2 "$MOUNT_POINT/FolioOrb.app"
codesign --display --verbose=4 "$MOUNT_POINT/FolioOrb.app"
codesign --verify --strict --verbose=2 $DMG
codesign --display --verbose=4 $DMG
hdiutil detach "$MOUNT_POINT"
rmdir "$MOUNT_POINT"
```

Confirm that the displayed authority and Team ID are expected and that both
frozen smoke paths already passed in Actions. Because Phase 3 is not active yet,
Gatekeeper can still require the documented Open Anyway flow.

Only after this exact-artifact check passes should continuous signing and its
public release-note claim be enabled:

```bash
gh variable set MACOS_SIGNING_ENABLED --body true
gh variable set MACOS_SIGNING_PUBLICLY_VERIFIED --body true
```

`MACOS_SIGNING_ENABLED` activates signing on normal release builds. The separate
`MACOS_SIGNING_PUBLICLY_VERIFIED` gate permits release notes to say Developer ID
signing is active. Setting only the first variable never emits that public claim.

To deactivate signing without deleting the secrets:

```bash
gh variable set MACOS_SIGNING_ENABLED --body false
gh variable set MACOS_SIGNING_PUBLICLY_VERIFIED --body false
```
