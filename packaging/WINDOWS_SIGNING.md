# Windows Authenticode signing — activation

FolioOrb's release pipeline includes dormant Phase 4 support for signing both
the frozen application executable and the final Inno Setup installer with
Azure Artifact Signing. Each signature uses SHA-256, receives an RFC 3161
timestamp, and must validate against one exact expected publisher subject
before the artifact can be uploaded.

This is readiness, not proof that Windows signing is active. Public downloads
and documentation must continue to say **unsigned** until a real build-only
rehearsal and then a separately published signed `latest-main` are independently
accepted.
Signing establishes publisher identity and file integrity; SmartScreen
reputation warnings can still appear, especially for a new certificate.

## Why this path

Artifact Signing keeps the code-signing private key out of GitHub. The workflow
uses GitHub's short-lived OpenID Connect token to authenticate to a narrowly
scoped Microsoft Entra workload identity. FolioOrb stores only non-secret Azure
identifiers and the expected public certificate subject as GitHub configuration
variables scoped to the protected environment; only the two activation switches
are repository variables. No PFX, certificate password, or long-lived Azure
client secret is accepted by this workflow.

Azure Artifact Signing was selected over SignPath for the checked-in path
because Microsoft supplies the GitHub action and OIDC integration, the signer
role can be scoped to one certificate profile, and the resulting public-trust
certificate carries FolioOrb's verified publisher identity. At the time this
phase was prepared, Microsoft's Basic tier was advertised at about USD 9.99
per month for 5,000 signatures, and individual public-trust onboarding was
limited to the United States and Canada; verify current eligibility and pricing
before activation.

SignPath remains a credible fallback for an eligible open-source project, but
its free program requires project acceptance, defined team/approver roles, and
manual release approval, and its certificate is issued to the SignPath
Foundation rather than the individual project publisher. FolioOrb has not
claimed or completed that external acceptance. This phase therefore prepares
one provider without purchasing or activating it.

Current references:
[Artifact Signing availability and pricing](https://learn.microsoft.com/windows/apps/package-and-deploy/code-signing-options),
[Azure product pricing](https://azure.microsoft.com/products/artifact-signing),
and [SignPath open-source terms](https://signpath.org/terms.html).

## One-time Azure setup

1. Create an Azure Artifact Signing account, complete the required identity
   validation, and create a public-trust certificate profile.
2. Create the protected GitHub environment `windows-signing`. Store the Azure
   identifiers listed below as environment variables there; keep the two
   activation switches as repository variables. Configure its deployment
   branch/tag restrictions to allow only `main` and authorized `v*` version
   tags. The Azure federated subject authenticates the environment name and
   does not encode the selected ref, so GitHub must enforce ref eligibility.
   The workflow also rejects a manual signed run from any other ref. Add a
   reviewer gate only when an independent authorized reviewer is actually
   available.
3. Create a Microsoft Entra application for the release workflow. Grant its
   service principal only the **Artifact Signing Certificate Profile Signer**
   role at the certificate-profile scope.
4. Add one GitHub OIDC federated credential for the exact environment subject
   `repo:udhawan97/FolioOrb:environment:windows-signing`. This subject stays the
   same for `main` and version-tag builds; the environment deployment rules
   above provide the separate ref boundary. Do not authorize branch,
   pull-request, or other-repository subjects.
5. Read the exact signer subject from the certificate profile's public
   certificate. Keep its full distinguished name, including every component
   and comma, for `WINDOWS_SIGNER_SUBJECT`.

Microsoft's current setup references are the
[Artifact Signing GitHub action](https://github.com/Azure/artifact-signing-action),
and [GitHub OIDC authentication](https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect).

## Protected-environment configuration variables

Configure the non-secret identifiers from the Azure and Entra setup on the
`windows-signing` environment:

```bash
gh variable set AZURE_ARTIFACT_SIGNING_CLIENT_ID --env windows-signing --body '<application-client-id>'
gh variable set AZURE_ARTIFACT_SIGNING_TENANT_ID --env windows-signing --body '<directory-tenant-id>'
gh variable set AZURE_ARTIFACT_SIGNING_SUBSCRIPTION_ID --env windows-signing --body '<subscription-id>'
gh variable set AZURE_ARTIFACT_SIGNING_ENDPOINT --env windows-signing --body 'https://<region>.codesigning.azure.net/'
gh variable set AZURE_ARTIFACT_SIGNING_ACCOUNT_NAME --env windows-signing --body '<signing-account-name>'
gh variable set AZURE_ARTIFACT_SIGNING_CERTIFICATE_PROFILE_NAME --env windows-signing --body '<certificate-profile-name>'
gh variable set WINDOWS_SIGNER_SUBJECT --env windows-signing --body '<exact-certificate-subject>'
```

Leave both activation switches unset or false during setup:

```bash
gh variable set WINDOWS_SIGNING_ENABLED --body false
gh variable set WINDOWS_SIGNING_PUBLICLY_VERIFIED --body false
```

## First signed-build gate

Run a signed build from `main` without publication:

```bash
gh workflow run release.yml \
  --ref main \
  -f sign_macos=false \
  -f notarize_macos=false \
  -f sign_windows=true \
  -f publish=false
```

The workflow must, in order:

1. build the frozen Windows application;
2. authenticate with GitHub OIDC and sign `FolioOrb.exe` using SHA-256 and an
   RFC 3161 SHA-256 timestamp;
3. require a trusted Authenticode chain, the exact configured signer subject,
   the Code Signing EKU, and a timestamp, then pass both frozen smoke paths;
4. build the installer around that signed executable;
5. sign and verify the exact final installer with the same requirements;
6. record the installer's raw SHA-256 and upload it beside
   `windows-SHA256SUMS.txt` in the `windows-installer` Actions artifact.

The two OIDC-capable signing jobs do not install Python packages, install Inno
Setup, execute FolioOrb, calculate release checksums, or publish final release
artifacts. Build, signed-app smoke, installer packaging, checksum generation,
and final upload run in separate jobs without `id-token: write`; only pinned
actions and the two small checked-in validation scripts run with signing
authority.

Record the successful run ID. On a clean disposable Windows x64 VM, download
the exact workflow artifact and require exactly one installer:

```powershell
$RunId = '1234567890' # Replace with the exact successful workflow run ID.
$ArtifactDir = Join-Path $env:TEMP "folioorb-signing-$RunId"
New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
gh run view $RunId --json headSha,event,status,conclusion,url
gh run download $RunId --name windows-installer --dir $ArtifactDir

$Installers = @(Get-ChildItem $ArtifactDir -File -Filter 'FolioOrb-Windows-x64-*-Setup.exe')
if ($Installers.Count -ne 1) { throw "Expected exactly one Windows installer." }
$Installer = $Installers[0]
$ExpectedHash = (Get-Content (Join-Path $ArtifactDir 'windows-SHA256SUMS.txt') -Raw).Trim().Split()[0]
$ActualHash = (Get-FileHash $Installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualHash -ne $ExpectedHash) { throw 'Downloaded installer checksum mismatch.' }

$Signature = Get-AuthenticodeSignature $Installer.FullName
if ($Signature.Status -ne 'Valid') { throw "Installer signature is $($Signature.Status)." }
if ($Signature.SignerCertificate.Subject -cne '<exact-certificate-subject>') {
  throw 'Installer signer subject mismatch.'
}
if ($null -eq $Signature.TimeStamperCertificate) { throw 'Installer has no timestamp.' }
signtool verify /pa /all /tw /v $Installer.FullName
if ($LASTEXITCODE -ne 0) { throw 'Installer SignTool verification failed.' }
```

Install only inside that disposable VM, then verify the installed executable
with the same expected subject and timestamp checks. Confirm both frozen smoke
paths passed in the same workflow run. Record the run URL, source SHA,
installer filename, SHA-256, signer subject, and timestamp authority.

Only after that build-only artifact is accepted, activate signing in two stages.
First enable continuous signing while leaving the public-claim switch false:

```bash
gh variable set WINDOWS_SIGNING_ENABLED --body true
gh variable set WINDOWS_SIGNING_PUBLICLY_VERIFIED --body false
gh workflow run release.yml \
  --ref main \
  -f sign_macos=false \
  -f notarize_macos=false \
  -f sign_windows=false \
  -f publish=true
```

The repository variable makes that manual `main` run take the signed path even
though the manual signing input is false. Download the newly published
`latest-main` artifact, repeat the exact checksum, installer signature,
installed-executable, and timestamp acceptance above, and confirm its source
SHA. The release note remains pilot wording because the public switch is still
false.

Next update and verify channel-specific public surfaces: `README.md`, the docs
landing page, Windows download and installation guides, troubleshooting
guidance, and the releases/versioning roadmap. State only that an independently
accepted `latest-main` is signed. Preserve the stable channel's unsigned status
until a signed stable release actually exists, retain the SmartScreen reputation
caveat, and do not rewrite historical unsigned-version instructions. Merge the
copy update, require its signed `main` build to pass, build the docs, and verify
the live surface.

Finally permit the public release-note claim and explicitly refresh the rolling
release; changing a repository variable alone does not run the workflow:

```bash
gh variable set WINDOWS_SIGNING_PUBLICLY_VERIFIED --body true
gh workflow run release.yml \
  --ref main \
  -f sign_macos=false \
  -f notarize_macos=false \
  -f sign_windows=false \
  -f publish=true
```

Verify that final run, its signed assets, the `latest-main` target SHA, release
note, and live docs before calling activation complete. `WINDOWS_SIGNING_ENABLED`
controls signing on normal release builds. The separate
`WINDOWS_SIGNING_PUBLICLY_VERIFIED` variable permits release notes to say
Authenticode signing is active only after acceptance. A manual rehearsal never
publishes unless `publish=true` is separately selected from `main`.

To deactivate Windows signing without deleting its Azure resources:

```bash
gh variable set WINDOWS_SIGNING_ENABLED --body false
gh variable set WINDOWS_SIGNING_PUBLICLY_VERIFIED --body false
```

This phase does not activate or change the separate macOS signing and
notarization gates.
