"""Static and executable contracts for the opt-in macOS notarization path."""

import base64
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _fake_notary_environment(
    tmp_path: Path,
    status: str = "Accepted",
    *,
    log_issues: bool = False,
) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls.log"

    xcrun = fake_bin / "xcrun"
    xcrun.write_text(
        """#!/bin/bash
set -euo pipefail
if [[ -n "${MACOS_NOTARY_PRIVATE_KEY:-}" ]]; then
  echo "raw notary secret leaked to xcrun" >&2
  exit 90
fi
printf '%s\\n' "$*" >> "$FAKE_CALLS"
if [[ "$1 $2" == "notarytool submit" ]]; then
  printf '{"id":"01234567-89ab-cdef-0123-456789abcdef","status":"%s"}\\n' "$FAKE_NOTARY_STATUS"
elif [[ "$1 $2" == "notarytool log" ]]; then
  output="${@: -1}"
  if [[ "$FAKE_NOTARY_STATUS" == "Accepted" && "$FAKE_LOG_ISSUES" != "true" ]]; then
    printf '{"status":"Accepted","issues":[]}\\n' > "$output"
  elif [[ "$FAKE_NOTARY_STATUS" == "Accepted" ]]; then
    printf '{"status":"Accepted","issues":[{"severity":"warning"}]}\\n' > "$output"
  else
    printf '{"status":"Invalid","issues":[{"severity":"error"}]}\\n' > "$output"
  fi
elif [[ "$1" != "stapler" ]]; then
  exit 2
fi
""",
        encoding="utf-8",
    )
    xcrun.chmod(0o755)

    ditto = fake_bin / "ditto"
    ditto.write_text(
        """#!/bin/bash
set -euo pipefail
for output in "$@"; do :; done
touch "$output"
""",
        encoding="utf-8",
    )
    ditto.chmod(0o755)

    spctl = fake_bin / "spctl"
    spctl.write_text(
        """#!/bin/bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_CALLS"
printf '%s\\n' 'accepted' 'source=Notarized Developer ID'
""",
        encoding="utf-8",
    )
    spctl.chmod(0o755)

    real_openssl = shutil.which("openssl")
    assert real_openssl is not None
    openssl = fake_bin / "openssl"
    openssl.write_text(
        f"""#!/bin/bash
set -euo pipefail
if [[ -n "${{MACOS_NOTARY_PRIVATE_KEY:-}}" ]]; then
  echo "raw notary secret leaked to openssl" >&2
  exit 90
fi
exec "{real_openssl}" "$@"
""",
        encoding="utf-8",
    )
    openssl.chmod(0o755)

    key = tmp_path / "AuthKey.p8"
    key.write_text("fixture", encoding="utf-8")
    return {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "FAKE_CALLS": str(calls),
        "FAKE_NOTARY_STATUS": status,
        "FAKE_LOG_ISSUES": "true" if log_issues else "false",
        "FOLIOORB_NOTARY_KEY_PATH": str(key),
        "FOLIOORB_NOTARY_KEY_ID": "ABCDEFGHIJ",
        "FOLIOORB_NOTARY_ISSUER_ID": "01234567-89ab-cdef-0123-456789abcdef",
    }


def test_notarization_is_explicit_and_requires_signing_in_the_same_run():
    workflow = _text(".github/workflows/release.yml")

    assert "notarize_macos:" in workflow
    assert "MACOS_NOTARIZATION_ENABLED: ${{ vars.MACOS_NOTARIZATION_ENABLED }}" in workflow
    assert "macos_notarization: ${{ steps.vars.outputs.macos_notarization }}" in workflow
    assert "macOS notarization requires Developer ID signing in the same run" in workflow
    assert 'echo "macos_notarization=false"' in workflow


def test_notarization_credential_is_validated_and_ephemeral():
    workflow = _text(".github/workflows/release.yml")
    wrapper = _text("packaging/macos/with_notary_key.sh")

    assert "MACOS_NOTARY_PRIVATE_KEY: ${{ secrets.MACOS_NOTARY_PRIVATE_KEY }}" in workflow
    assert "FOLIOORB_NOTARY_KEY_ID: ${{ vars.MACOS_NOTARY_KEY_ID }}" in workflow
    assert "FOLIOORB_NOTARY_ISSUER_ID: ${{ vars.MACOS_NOTARY_ISSUER_ID }}" in workflow
    assert workflow.count("MACOS_NOTARY_PRIVATE_KEY: ${{ secrets.") == 2
    assert "MACOS_NOTARY_PRIVATE_KEY is not valid base64" in wrapper
    assert "MACOS_NOTARY_PRIVATE_KEY is not a PKCS#8 PEM private key" in wrapper
    assert "of at least 10 characters" in wrapper
    assert "umask 077" in wrapper
    assert 'openssl pkey -in "$NOTARY_KEY_PATH" -noout' in wrapper
    assert "unset MACOS_NOTARY_PRIVATE_KEY" in wrapper
    assert "trap cleanup EXIT" in wrapper
    assert 'rm -f "$NOTARY_KEY_PATH"' in wrapper
    decoded = wrapper.index("\nPY\n")
    unset = wrapper.index("unset MACOS_NOTARY_PRIVATE_KEY")
    openssl = wrapper.index("openssl pkey")
    assert decoded < unset < openssl


def test_app_is_notarized_before_the_dmg_and_dmg_after_signing():
    workflow = _text(".github/workflows/release.yml")

    smoke = workflow.index("- name: Smoke test the frozen bundle")
    notarize_app = workflow.index("- name: Notarize and staple app bundle")
    build_dmg = workflow.index("- name: Build DMG")
    sign_dmg = workflow.index("- name: Sign and verify Developer ID DMG")
    notarize_dmg = workflow.index("- name: Notarize and staple DMG")
    verify_dmg = workflow.index("- name: Verify notarized DMG and embedded app")
    upload = workflow.index(
        "- uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        notarize_dmg,
    )

    assert smoke < notarize_app < build_dmg < sign_dmg < notarize_dmg < verify_dmg < upload
    assert "packaging/macos/with_notary_key.sh app dist/FolioOrb.app" in workflow
    assert "packaging/macos/with_notary_key.sh dmg" in workflow
    assert '"dist/out/FolioOrb-macOS-arm64-${ASSET_TOKEN}.dmg"' in workflow
    assert 'xcrun stapler validate "$MOUNT_POINT/FolioOrb.app"' in workflow


def test_post_notarization_verification_has_no_private_key_secret():
    workflow = _text(".github/workflows/release.yml")
    credentialed = workflow.split("- name: Notarize and staple DMG", maxsplit=1)[1]
    credentialed, remainder = credentialed.split(
        "- name: Verify notarized DMG and embedded app", maxsplit=1
    )
    verification = remainder.split("- name: Record macOS artifact checksum", maxsplit=1)[0]

    assert "MACOS_NOTARY_PRIVATE_KEY" in credentialed
    assert "with_notary_key.sh dmg" in credentialed
    assert "hdiutil" not in credentialed
    assert "MACOS_NOTARY_PRIVATE_KEY" not in verification
    assert "hdiutil verify" in verification
    assert "spctl --assess --type execute" in verification


def test_raw_dmg_checksum_is_recorded_and_uploaded_with_the_rehearsal():
    workflow = _text(".github/workflows/release.yml")

    checksum = workflow.index("- name: Record macOS artifact checksum")
    upload = workflow.index(
        "- uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        checksum,
    )
    assert checksum < upload
    assert 'shasum -a 256 -- "${DMGS[0]}" > macos-SHA256SUMS.txt' in workflow
    assert "dist/out/macos-SHA256SUMS.txt" in workflow


def test_notary_helper_requires_acceptance_stapling_and_gatekeeper():
    helper = _text("packaging/macos/notarize_artifact.sh")

    assert "xcrun notarytool submit" in helper
    assert "--wait" in helper
    assert "--timeout 45m" in helper
    assert '"$NOTARY_STATUS" != "Accepted"' in helper
    assert "xcrun notarytool log" in helper
    assert 'log.get("status") != "Accepted" or issues' in helper
    assert 'xcrun stapler staple -v "$ARTIFACT"' in helper
    assert 'xcrun stapler validate "$ARTIFACT"' in helper
    assert "--context context:primary-signature" in helper
    assert 'spctl "${ASSESS_ARGS[@]}"' in helper
    assert "source=Notarized Developer ID" in helper


def test_notary_helper_runs_the_accepted_app_sequence(tmp_path):
    app = tmp_path / "FolioOrb.app"
    app.mkdir()
    env = _fake_notary_environment(tmp_path)

    result = subprocess.run(
        [str(ROOT / "packaging/macos/notarize_artifact.sh"), "app", str(app)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "notarytool submit" in calls
    assert "notarytool log" in calls
    assert "stapler staple" in calls
    assert "--type execute" in calls
    assert not list(tmp_path.glob("folioorb-notary.*"))


def test_notary_helper_refuses_an_invalid_submission_before_stapling(tmp_path):
    dmg = tmp_path / "FolioOrb.dmg"
    dmg.touch()
    env = _fake_notary_environment(tmp_path, status="Invalid")

    result = subprocess.run(
        [str(ROOT / "packaging/macos/notarize_artifact.sh"), "dmg", str(dmg)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode != 0
    assert "refusing to staple or publish" in result.stderr
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "notarytool log" in calls
    assert "stapler staple" not in calls


def test_notary_helper_runs_the_accepted_dmg_assessment(tmp_path):
    dmg = tmp_path / "FolioOrb.dmg"
    dmg.touch()
    env = _fake_notary_environment(tmp_path)

    result = subprocess.run(
        [str(ROOT / "packaging/macos/notarize_artifact.sh"), "dmg", str(dmg)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "stapler staple" in calls
    assert "--type open --context context:primary-signature" in calls


def test_notary_helper_refuses_an_accepted_submission_with_log_issues(tmp_path):
    dmg = tmp_path / "FolioOrb.dmg"
    dmg.touch()
    env = _fake_notary_environment(tmp_path, log_issues=True)

    result = subprocess.run(
        [str(ROOT / "packaging/macos/notarize_artifact.sh"), "dmg", str(dmg)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode != 0
    assert "notarization log was not clean and Accepted" in result.stderr
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "stapler staple" not in calls


def test_notary_wrapper_removes_each_decoded_private_key(tmp_path):
    app = tmp_path / "FolioOrb.app"
    app.mkdir()
    env = _fake_notary_environment(tmp_path)
    private_key = subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "EC",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
        ],
        check=True,
        capture_output=True,
    ).stdout
    env["MACOS_NOTARY_PRIVATE_KEY"] = base64.b64encode(private_key).decode("ascii")

    result = subprocess.run(
        [str(ROOT / "packaging/macos/with_notary_key.sh"), "app", str(app)],
        check=False,
        capture_output=True,
        cwd=ROOT,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.glob("folioorb-notary-key.*"))


def test_public_notarization_claim_has_a_separate_acceptance_gate():
    workflow = _text(".github/workflows/release.yml")

    assert "MACOS_NOTARIZATION_PUBLICLY_VERIFIED" in workflow
    assert (
        "macos_notarization_public: ${{ steps.vars.outputs.macos_notarization_public }}"
        in workflow
    )
    assert "MACOS_NOTARIZED: ${{ needs.prepare.outputs.macos_notarization_public }}" in workflow
    assert "The macOS app and DMG are Developer ID signed and notarized;" in workflow
    assert "Windows remains unsigned" in workflow
    assert "credentialed pilot validation" in workflow


def test_docs_keep_readiness_separate_from_activation():
    activation = _text("packaging/MACOS_NOTARIZATION.md")
    roadmap = _text("docs-site/src/content/docs/releases-and-versioning.mdx")

    assert "This is readiness, not proof that notarization is active" in activation
    assert "publish=false" in activation
    assert "MACOS_NOTARIZATION_PUBLICLY_VERIFIED" in activation
    assert "gh run download" in activation
    assert "macos-SHA256SUMS.txt" in activation
    assert "Windows Authenticode signing path" in activation
    assert "remains dormant" in activation
    assert "Readiness checked in; activation pending" in roadmap
    assert "normal first-open confirmation remains" in roadmap
    assert "Notarization remains a separate later gate" in roadmap
