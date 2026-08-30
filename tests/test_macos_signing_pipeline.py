"""Static contracts for the opt-in Developer ID release path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_release_signing_is_explicit_and_fails_closed():
    workflow = _text(".github/workflows/release.yml")

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
    assert "requires both Developer ID secrets" in workflow
    assert "MACOS_DEVELOPER_TEAM_ID must be the expected" in workflow
    assert "Expected exactly one valid Developer ID Application identity" in workflow
    assert "umask 077" in workflow


def test_manual_signing_rehearsal_cannot_publish_by_default():
    workflow = _text(".github/workflows/release.yml")

    assert """publish:
        description: Publish from main after exact-artifact acceptance
        required: true
        type: boolean
        default: false""" in workflow
    assert 'echo "publish=false"' in workflow
    assert "Manual publication is restricted to refs/heads/main" in workflow
    assert "if: needs.prepare.outputs.publish == 'true'" in workflow


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

    assert 'os.getenv("FOLIOORB_CODESIGN_IDENTITY") or None' in spec
    assert '"packaging" / "macos" / "FolioOrb.entitlements"' in spec
    assert "codesign_identity=CODESIGN_IDENTITY" in spec
    assert "entitlements_file=ENTITLEMENTS_FILE" in spec
    assert "codesign --verify --deep --strict --verbose=2 dist/FolioOrb.app" in workflow
    assert 'codesign --verify --strict --verbose=2 "$DMG"' in workflow
    assert "Authority=Developer ID Application:" in workflow
    assert 'hdiutil verify "$DMG"' in workflow
    assert '"$MOUNT_POINT/FolioOrb.app"' in workflow
    assert "EMBEDDED_TEAM_ID" in workflow


def test_ephemeral_keychain_is_cleaned_even_after_failure():
    workflow = _text(".github/workflows/release.yml")
    cleanup = workflow.split("- name: Cleanup Developer ID keychain", maxsplit=1)[1]

    assert "always()" in cleanup[:180]
    assert 'security delete-keychain "$FOLIOORB_SIGNING_KEYCHAIN"' in cleanup


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
