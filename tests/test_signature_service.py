"""minisign parsing + verification of the checksum manifest.

Constructs real minisign public keys and .minisig files (both legacy 'Ed' and
prehashed 'ED' modes) using the pure Ed25519 signer, then verifies them.
"""
import base64
import hashlib

from app.services import ed25519_pure, signature_service

KEY_ID = bytes([1, 2, 3, 4, 5, 6, 7, 8])


def _keypair(seed=bytes(range(32))):
    pk = ed25519_pure.publickey(seed)
    pub_b64 = base64.b64encode(b"Ed" + KEY_ID + pk).decode()
    return seed, pk, pub_b64


def _minisig(alg, key_id, seed, pk, content):
    signed = hashlib.blake2b(content, digest_size=64).digest() if alg == b"ED" else content
    sig = ed25519_pure.sign(signed, seed, pk)
    block = base64.b64encode(alg + key_id + sig).decode()
    glob = base64.b64encode(b"\x00" * 64).decode()  # trusted-comment sig, unused
    return f"untrusted comment: signature\n{block}\ntrusted comment: ts\n{glob}\n"


def test_not_configured_returns_none():
    assert signature_service.verify_manifest(b"data", "", public_key_b64="") is None


def test_valid_legacy_signature():
    seed, pk, pub = _keypair()
    content = b"deadbeef  app.dmg\n"
    sig_text = _minisig(b"Ed", KEY_ID, seed, pk, content)
    assert signature_service.verify_manifest(content, sig_text, public_key_b64=pub) is True


def test_valid_prehashed_signature():
    seed, pk, pub = _keypair()
    content = b"cafef00d  app.exe\n"
    sig_text = _minisig(b"ED", KEY_ID, seed, pk, content)
    assert signature_service.verify_manifest(content, sig_text, public_key_b64=pub) is True


def test_tampered_content_fails():
    seed, pk, pub = _keypair()
    content = b"deadbeef  app.dmg\n"
    sig_text = _minisig(b"Ed", KEY_ID, seed, pk, content)
    assert signature_service.verify_manifest(b"TAMPERED\n", sig_text, public_key_b64=pub) is False


def test_key_id_mismatch_fails():
    seed, pk, pub = _keypair()
    content = b"x  y\n"
    # Signature carries a different key id than the embedded public key.
    sig_text = _minisig(b"Ed", bytes([9] * 8), seed, pk, content)
    assert signature_service.verify_manifest(content, sig_text, public_key_b64=pub) is False


def test_malformed_signature_fails():
    _, _, pub = _keypair()
    assert signature_service.verify_manifest(b"x", "not a real minisig", public_key_b64=pub) is False


def test_is_configured_reflects_key():
    assert signature_service.is_configured() is False  # empty by default
