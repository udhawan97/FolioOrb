"""Static contracts for the opt-in Windows Authenticode release path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_windows_signing_is_explicit_and_uses_oidc_without_a_private_key():
    workflow = _text(".github/workflows/release.yml")

    assert "sign_windows:" in workflow
    assert "WINDOWS_SIGNING_ENABLED: ${{ vars.WINDOWS_SIGNING_ENABLED }}" in workflow
    assert "windows_signing: ${{ steps.vars.outputs.windows_signing }}" in workflow
    assert "id-token: write" in workflow
    assert "azure/login@7ddb5af1ef8758cf1353cf3b42f940aee27ba21c" in workflow
    assert "azure/artifact-signing-action@c7ab2a863ab5f9a846ddb8265964877ef296ee82" in workflow
    assert "AZURE_ARTIFACT_SIGNING_CLIENT_ID" in workflow
    assert "AZURE_ARTIFACT_SIGNING_TENANT_ID" in workflow
    assert "AZURE_ARTIFACT_SIGNING_SUBSCRIPTION_ID" in workflow
    assert "WINDOWS_SIGNING_PRIVATE_KEY" not in workflow
    assert "WINDOWS_SIGNING_CERTIFICATE" not in workflow


def test_manual_windows_signing_rejects_arbitrary_refs():
    workflow = _text(".github/workflows/release.yml")

    assert '$GITHUB_REF" != "refs/heads/main"' in workflow
    assert '$GITHUB_REF" != refs/tags/v*' in workflow
    assert "Manual Windows signing is restricted to refs/heads/main or version tags." in workflow


def test_windows_signing_configuration_fails_closed_before_azure_login():
    workflow = _text(".github/workflows/release.yml")
    validator = _text("packaging/windows/validate_artifact_signing.ps1")

    validate = workflow.index("- name: Validate Artifact Signing configuration")
    login = workflow.index("- name: Authenticate to Azure for Artifact Signing")
    sign_app = workflow.index("- name: Sign frozen Windows executable")

    assert validate < login < sign_app
    assert "Artifact Signing requires all Azure identity and signing profile variables" in validator
    assert "must use an HTTPS *.codesigning.azure.net endpoint root" in validator
    assert "WINDOWS_SIGNER_SUBJECT must be the exact expected Authenticode subject" in validator
    assert "packaging/windows/validate_artifact_signing.ps1" in workflow
    assert "packaging/windows/verify_authenticode.ps1" in workflow


def test_frozen_executable_and_final_installer_share_the_signing_gate():
    workflow = _text(".github/workflows/release.yml")

    build_app = workflow.index("- name: Build app bundle", workflow.index("build-windows:"))
    stage_unsigned_app = workflow.index("- name: Stage Windows app for isolated signing")
    sign_app_job = workflow.index("sign-windows-app:")
    sign_app = workflow.index("- name: Sign frozen Windows executable", sign_app_job)
    verify_app = workflow.index("- name: Verify frozen Windows executable signature")
    stage_signed_app = workflow.index("- name: Stage signed Windows app outside the OIDC job")
    package_job = workflow.index("package-windows-signed:")
    smoke = workflow.index("- name: Smoke test signed frozen bundle", package_job)
    build_installer = workflow.index("- name: Build installer around signed executable")
    stage_installer = workflow.index("- name: Stage Windows installer for isolated signing")
    sign_installer_job = workflow.index("sign-windows-installer:")
    sign_installer = workflow.index("- name: Sign Windows installer")
    verify_installer = workflow.index("- name: Verify Windows installer signature")
    stage_signed_installer = workflow.index(
        "name: windows-signed-installer", verify_installer
    )
    finalizer = workflow.index("finalize-windows-signed:")
    checksum = workflow.index("- name: Record signed Windows artifact checksum")
    upload = workflow.index(
        "- uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        checksum,
    )

    assert (
        build_app
        < stage_unsigned_app
        < sign_app
        < verify_app
        < stage_signed_app
        < smoke
        < build_installer
        < stage_installer
        < sign_installer
        < verify_installer
        < stage_signed_installer
        < finalizer
        < checksum
        < upload
    )
    assert "dist\\FolioOrb\\FolioOrb.exe" in workflow
    assert "dist\\installer\\FolioOrb-Windows-x64-$env:ASSET_TOKEN-Setup.exe" in workflow
    assert workflow.count("file-digest: SHA256") == 2
    assert workflow.count("timestamp-rfc3161: http://timestamp.acs.microsoft.com") == 2
    assert workflow.count("timestamp-digest: SHA256") == 2
    assert sign_app_job < sign_app < package_job < sign_installer_job < sign_installer


def test_oidc_authority_is_isolated_from_build_packaging_and_smoke_steps():
    workflow = _text(".github/workflows/release.yml")
    build = workflow.split("  build-windows:", maxsplit=1)[1].split(
        "  sign-windows-app:", maxsplit=1
    )[0]
    sign_app = workflow.split("  sign-windows-app:", maxsplit=1)[1].split(
        "  package-windows-signed:", maxsplit=1
    )[0]
    package = workflow.split("  package-windows-signed:", maxsplit=1)[1].split(
        "  sign-windows-installer:", maxsplit=1
    )[0]
    sign_installer = workflow.split("  sign-windows-installer:", maxsplit=1)[1].split(
        "  finalize-windows-signed:", maxsplit=1
    )[0]
    finalizer = workflow.split("  finalize-windows-signed:", maxsplit=1)[1].split(
        "  publish:", maxsplit=1
    )[0]

    assert "id-token: write" not in build
    assert "id-token: write" not in package
    assert "id-token: write" not in finalizer
    assert "azure/login@" not in build
    assert "azure/login@" not in package
    assert "Smoke test signed frozen bundle" in package
    assert "choco install innosetup" in package
    assert "Record signed Windows artifact checksum" in finalizer
    assert "name: windows-installer" in finalizer
    for signing_job in (sign_app, sign_installer):
        assert "environment: windows-signing" in signing_job
        assert "id-token: write" in signing_job
        assert "python -m pip" not in signing_job
        assert "choco install" not in signing_job
        assert "Start-Process" not in signing_job
        assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in signing_job


def test_windows_artifacts_require_one_exact_named_installer():
    workflow = _text(".github/workflows/release.yml")
    exact = (
        "dist/installer/FolioOrb-Windows-x64-"
        "${{ needs.prepare.outputs.asset_token }}-Setup.exe"
    )

    assert "path: dist/installer/*.exe" not in workflow
    assert workflow.count(exact) >= 4
    assert workflow.count('$installers.Count -ne 1') == 2
    assert "Expected exactly the named Windows installer before upload." in workflow
    assert "Expected exactly the named Windows installer before finalization." in workflow


def test_publish_downloads_only_final_platform_artifacts():
    workflow = _text(".github/workflows/release.yml")
    publish = workflow.split("\n  publish:\n", maxsplit=1)[1]

    assert "Download final macOS artifact only" in publish
    assert "Download final Windows artifact only" in publish
    assert "name: macos-dmg" in publish
    assert "name: windows-installer" in publish
    assert "windows-app-for-signing" not in publish
    assert "windows-installer-for-signing" not in publish


def test_authenticode_verifier_requires_trust_identity_eku_and_timestamp():
    verifier = _text("packaging/windows/verify_authenticode.ps1")

    assert "Get-AuthenticodeSignature" in verifier
    assert 'Signature status is not Valid' in verifier
    assert 'Signature is not embedded Authenticode' in verifier
    assert 'does not match expected subject' in verifier
    assert '1.3.6.1.5.5.7.3.3' in verifier
    assert 'has no RFC 3161 timestamp certificate' in verifier
    for argument in ('"verify"', '"/pa"', '"/all"', '"/tw"', '"/v"'):
        assert argument in verifier


def test_raw_windows_installer_checksum_is_uploaded_with_rehearsal():
    workflow = _text(".github/workflows/release.yml")

    assert "windows-SHA256SUMS.txt" in workflow
    assert "Get-FileHash -LiteralPath $installer -Algorithm SHA256" in workflow
    assert "dist/installer/windows-SHA256SUMS.txt" in workflow


def test_public_windows_claim_has_a_separate_acceptance_gate():
    workflow = _text(".github/workflows/release.yml")

    assert "WINDOWS_SIGNING_PUBLICLY_VERIFIED" in workflow
    assert "windows_signing_public: ${{ steps.vars.outputs.windows_signing_public }}" in workflow
    assert "WINDOWS_SIGNING_ACTIVE: ${{ needs.prepare.outputs.windows_signing }}" in workflow
    assert "WINDOWS_SIGNED: ${{ needs.prepare.outputs.windows_signing_public }}" in workflow
    assert "Windows signing is in credentialed pilot validation" in workflow
    assert "SmartScreen reputation warnings can still appear" in workflow


def test_docs_keep_windows_readiness_separate_from_activation():
    activation = _text("packaging/WINDOWS_SIGNING.md")
    roadmap = _text("docs-site/src/content/docs/releases-and-versioning.mdx")
    install = _text("docs-site/src/content/docs/install-windows.mdx")

    assert "This is readiness, not proof that Windows signing is active" in activation
    assert "publish=false" in activation
    assert "WINDOWS_SIGNING_PUBLICLY_VERIFIED" in activation
    assert "gh run download" in activation
    assert "branch/tag restrictions" in activation
    assert "does not encode the selected ref" in activation
    assert "activate signing in two stages" in activation
    assert "changing a repository variable alone does not run the workflow" in activation
    assert "Preserve the stable channel's unsigned status" in activation
    assert "windows-SHA256SUMS.txt" in activation
    assert "Readiness checked in; activation pending" in roadmap
    assert "SmartScreen reputation" in roadmap
    assert "early builds aren't code-signed" in install
