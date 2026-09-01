"""Static contracts for the opt-in Developer ID release path."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_release_signing_is_explicit_and_fails_closed():
    workflow = _text(".github/workflows/release.yml")
    signer = _text("packaging/macos/sign_artifact.sh")

    assert "sign_macos:" in workflow
    assert "publish:" in workflow
    assert "MACOS_SIGNING_ENABLED: ${{ vars.MACOS_SIGNING_ENABLED }}" in workflow
    assert "macos_signing: ${{ steps.vars.outputs.macos_signing }}" in workflow
    assert (
        "MACOS_DEVELOPER_ID_CERTIFICATE: ${{ secrets.MACOS_DEVELOPER_ID_CERTIFICATE }}"
        in workflow
    )
    assert (
        "MACOS_DEVELOPER_ID_PASSWORD: ${{ secrets.MACOS_DEVELOPER_ID_PASSWORD }}"
        in workflow
    )
    assert workflow.count("MACOS_DEVELOPER_ID_CERTIFICATE: ${{ secrets.") == 2
    assert "requires both Developer ID secrets" in signer
    assert "MACOS_DEVELOPER_TEAM_ID must be the expected" in signer
    assert "Expected exactly one valid Developer ID Application identity" in signer
    assert "umask 077" in signer


def test_manual_signing_rehearsal_cannot_publish_by_default():
    workflow = _text(".github/workflows/release.yml")

    assert """publish:
        description: Publish from main after exact-artifact acceptance
        required: true
        type: boolean
        default: false""" in workflow
    assert 'echo "publish=false"' in workflow
    assert "Manual publication is restricted to refs/heads/main" in workflow
    assert "needs.prepare.outputs.publish == 'true'" in workflow


def test_macos_signing_fails_closed_until_external_trust_boundary_is_accepted():
    workflow = _text(".github/workflows/release.yml")
    activation = _text("packaging/MACOS_SIGNING.md")

    assert (
        "macOS credentialed release work is restricted to protected refs/heads/main"
        in workflow
    )
    assert "MACOS_SIGNING_TRUST_BOUNDARY_ACCEPTED" in workflow
    assert "macOS signing remains disabled until its external protected-environment" in workflow
    assert "Repository source" in activation
    assert "external environment policy" in activation
    assert "version tags are refused" in activation


def test_macos_artifact_records_and_checks_exact_source_sha():
    workflow = _text(".github/workflows/release.yml")

    assert "source_sha: ${{ steps.vars.outputs.source_sha }}" in workflow
    assert 'if [[ "$SOURCE_SHA" != "$GITHUB_SHA" ]]' in workflow
    assert 'printf \'%s\\n\' "${{ needs.prepare.outputs.source_sha }}"' in workflow
    assert 'test "$(cat macos-SOURCE-SHA.txt)" = "$GITHUB_SHA"' in workflow
    assert "dist/out/macos-SOURCE-SHA.txt" in workflow


def test_credentials_are_isolated_in_a_protected_fixed_logic_job():
    workflow = _text(".github/workflows/release.yml")
    build = workflow.split("  build-macos:", maxsplit=1)[1].split(
        "  sign-macos:", maxsplit=1
    )[0]
    signing = workflow.split("  sign-macos:", maxsplit=1)[1].split(
        "  build-windows:", maxsplit=1
    )[0]

    assert "secrets.MACOS_" not in build
    assert "environment: macos-signing" in signing
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in signing
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in signing
    verify = signing.index("Verify exact source and app before credential access")
    credentials = signing.index("Sign and verify Developer ID app bundle")
    assert verify < credentials
    assert 'test "$(cat macos-SOURCE-SHA.txt)" = "$GITHUB_SHA"' in signing
    assert "shasum -a 256 --check macos-app-SHA256SUMS.txt" in signing
    assert "verify_signing_archive.py FolioOrb-app.tar.gz" in signing
    assert "name: macos-app-for-signing" in build
    assert "python -m pip" not in signing


def test_release_actions_and_macos_producer_runtime_are_immutable():
    workflow = _text(".github/workflows/release.yml")
    build = workflow.split("  build-macos:", maxsplit=1)[1].split(
        "  sign-macos:", maxsplit=1
    )[0]

    assert not re.search(r"uses: actions/[^@\s]+@(v\d+|main|master)(?:\s|$)", workflow)
    assert "python-version: \"3.12.10\"" in build
    assert "pip install --upgrade pip" not in build


def test_dmg_acceptance_is_structural_even_if_layout_tool_returns_nonzero():
    workflow = _text(".github/workflows/release.yml")
    builder = _text("packaging/macos/build_and_verify_dmg.sh")
    installer = _text("packaging/macos/install_create_dmg.sh")

    assert "create-dmg" not in workflow or "install_create_dmg.sh" in workflow
    assert "create-dmg" in builder
    assert '"$OUTPUT_DMG" "$STAGE_ROOT/" || true' not in builder
    assert "CREATE_DMG_STATUS=$?" in builder
    assert 'hdiutil verify "$OUTPUT_DMG"' in builder
    assert 'test -d "$MOUNT_POINT/FolioOrb.app"' in builder
    assert 'test "$(readlink "$MOUNT_POINT/Applications")" = "/Applications"' in builder
    assert 'test "$(readlink "$MOUNT_POINT/FolioSenseAI.app")" = "FolioOrb.app"' in builder
    assert "archive/refs/tags/v${VERSION}.tar.gz" in installer
    assert "EXPECTED_SHA256=" in installer


def test_public_signing_claim_has_a_separate_acceptance_gate():
    workflow = _text(".github/workflows/release.yml")

    assert "MACOS_SIGNING_PUBLICLY_VERIFIED" in workflow
    assert (
        "macos_signing_public: ${{ steps.vars.outputs.macos_signing_public }}"
        in workflow
    )
    assert "MACOS_SIGNING_ACTIVE: ${{ needs.prepare.outputs.macos_signing }}" in workflow
    assert "MACOS_SIGNED: ${{ needs.prepare.outputs.macos_signing_public }}" in workflow
    assert "credentialed pilot validation" in workflow


def test_pyinstaller_and_final_artifacts_share_the_developer_id_gate():
    workflow = _text(".github/workflows/release.yml")
    spec = _text("packaging/pyinstaller/FolioOrb.spec")
    signer = _text("packaging/macos/sign_artifact.sh")

    assert 'os.getenv("FOLIOORB_CODESIGN_IDENTITY") or None' in spec
    assert '"packaging" / "macos" / "FolioOrb.entitlements"' in spec
    assert "codesign_identity=CODESIGN_IDENTITY" in spec
    assert "entitlements_file=ENTITLEMENTS_FILE" in spec
    assert 'codesign --verify --deep --strict --verbose=2 "$ARTIFACT"' in signer
    assert 'codesign --verify --strict --verbose=2 "$ARTIFACT"' in signer
    assert "Authority=Developer ID Application:" in signer
    assert 'hdiutil verify "$DMG"' in workflow
    assert '"$MOUNT_POINT/FolioOrb.app"' in workflow
    assert "EMBEDDED_TEAM_ID" in workflow


def test_ephemeral_keychain_is_cleaned_even_after_failure():
    workflow = _text(".github/workflows/release.yml")
    signer = _text("packaging/macos/sign_artifact.sh")
    signing = workflow.split("  sign-macos:", maxsplit=1)[1].split(
        "  build-windows:", maxsplit=1
    )[0]

    assert "trap cleanup EXIT" in signer
    assert 'security delete-keychain "$KEYCHAIN_PATH"' in signer
    assert "FOLIOORB_SIGNING_KEYCHAIN" not in workflow
    app_sign = signing.index("Sign and verify Developer ID app bundle")
    smoke = signing.index("Smoke test signed frozen bundle")
    dmg_sign = signing.index("Sign and verify Developer ID DMG")
    assert app_sign < smoke < dmg_sign


def test_docs_do_not_conflate_signing_with_notarization():
    activation = _text("packaging/MACOS_SIGNING.md")
    roadmap = _text("docs-site/src/content/docs/releases-and-versioning.mdx")

    assert "This is Phase 2 readiness, not proof that Phase 2 is live" in activation
    assert "Notarization is a separate Phase 3" in activation
    assert "publish=false" in activation
    assert "MACOS_SIGNING_PUBLICLY_VERIFIED" in activation
    assert "Activation pending" in roadmap
    assert "no public release is described" in roadmap
    assert "Notarization remains a separate later gate" in roadmap
