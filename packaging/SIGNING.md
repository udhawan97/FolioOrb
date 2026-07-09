# Update signing (minisign) — activation

The in-app updater always verifies downloads against `SHA256SUMS.txt` (integrity).
To also verify **authenticity** — that a release was published by you, not just
that the bytes are intact — the release workflow can sign `SHA256SUMS.txt` with a
[minisign](https://jedisct1.github.io/minisign/) key, and the app verifies that
signature with an embedded public key.

Until the steps below are done, releases ship SHA-256 checksums only and the app
verifies integrity without authenticity — no behavior changes, nothing breaks.

## One-time setup

1. **Create a passwordless signing key** (passwordless so CI can sign headless):

   ```bash
   minisign -G -W -p minisign.pub -s minisign.key
   ```

2. **Add the private key as a repo secret** named `MINISIGN_SECRET_KEY`:

   ```bash
   gh secret set MINISIGN_SECRET_KEY < minisign.key
   ```

   The release workflow's "Sign checksums (minisign)" step runs only when this
   secret exists.

3. **Embed the public key in the app.** Open `minisign.pub` — it has a comment
   line and a base64 line. Copy the **base64 line** (not the comment) into
   `app/services/signature_service.py`:

   ```python
   UPDATER_MINISIGN_PUBLIC_KEY = "RWQ...the base64 line..."
   ```

4. **Keep `minisign.key` offline** (a password manager / secure store). Never
   commit it. `minisign.pub` is safe to keep in the repo if you like.

## What happens after activation

- CI publishes `SHA256SUMS.txt.minisig` alongside each release's assets.
- On update, the app fetches the signature and requires it to be valid **before**
  trusting the checksums. A missing or invalid signature aborts the update and
  discards the download; the user keeps their current version and data.
- Verification is dependency-free (`app/services/ed25519_pure.py`, RFC 8032), so
  it adds nothing to the PyInstaller bundle's dependency surface.

## QA when activating

Cut a test release after embedding the key and confirm an in-app update verifies
end to end (the reference Ed25519 matches minisign/libsodium, but validate the
real CLI-produced signature once). Then confirm a deliberately corrupted
`SHA256SUMS.txt.minisig` is rejected.
