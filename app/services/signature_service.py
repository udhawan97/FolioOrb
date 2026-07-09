"""Verify the authenticity of the checksum manifest with a minisign signature.

SHA-256 proves a download matches what CI published (integrity). To also prove
it was published by *us* (authenticity), CI signs ``SHA256SUMS.txt`` with a
minisign (Ed25519) key and publishes ``SHA256SUMS.txt.minisig``. The app embeds
the matching public key and checks the signature before trusting the manifest.

This is a staged rollout: until a real public key is embedded below, verification
returns ``None`` ("not configured") and the download flow relies on SHA-256
integrity alone — exactly today's behavior. Once the key is set and CI signs,
a bad signature hard-fails the update.

Supports both minisign signature modes: legacy ``Ed`` (signs the file) and
prehashed ``ED`` (signs the BLAKE2b-512 of the file).
"""
from __future__ import annotations

import base64
import hashlib
import logging

from app.services import ed25519_pure

logger = logging.getLogger(__name__)

# The base64 line from your ``minisign.pub`` (NOT the comment line). Empty until
# the signing key is created and this is filled in — see docs/updating setup.
UPDATER_MINISIGN_PUBLIC_KEY = ""


def is_configured() -> bool:
    return bool(UPDATER_MINISIGN_PUBLIC_KEY.strip())


def _decode_public_key(b64: str) -> tuple[bytes, bytes]:
    """Return (key_id, ed25519_public_key) from a minisign public key line."""
    raw = base64.b64decode(b64.strip())
    if len(raw) != 42 or raw[0:2] != b"Ed":
        raise ValueError("Unrecognized minisign public key")
    return raw[2:10], raw[10:42]


def _parse_minisig(text: str) -> tuple[bytes, bytes, bytes]:
    """Return (algorithm, key_id, signature) from a .minisig file's first block."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(("untrusted comment:", "trusted comment:")):
            continue
        raw = base64.b64decode(stripped)
        if len(raw) != 74:
            raise ValueError("Unexpected minisign signature length")
        return raw[0:2], raw[2:10], raw[10:74]
    raise ValueError("No signature line found in .minisig")


def verify_manifest(
    content: bytes, minisig_text: str, public_key_b64: str | None = None
) -> bool | None:
    """Verify ``content`` (SHA256SUMS bytes) against its minisign signature.

    Returns True/False when a public key is configured, or None when signature
    verification isn't set up yet (caller falls back to SHA-256 integrity only).
    """
    pub_b64 = public_key_b64 if public_key_b64 is not None else UPDATER_MINISIGN_PUBLIC_KEY
    if not pub_b64 or not pub_b64.strip():
        return None
    try:
        key_id, public_key = _decode_public_key(pub_b64)
        alg, sig_key_id, signature = _parse_minisig(minisig_text)
    except (ValueError, base64.binascii.Error) as exc:
        logger.error("Malformed signature material: %s", type(exc).__name__)
        return False

    if sig_key_id != key_id:
        logger.error("Signature key id does not match the embedded public key")
        return False

    if alg == b"ED":
        signed = hashlib.blake2b(content, digest_size=64).digest()
    elif alg == b"Ed":
        signed = content
    else:
        logger.error("Unsupported minisign algorithm")
        return False

    return ed25519_pure.verify(public_key, signature, signed)
