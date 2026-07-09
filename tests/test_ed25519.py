"""Pure-Python Ed25519 used to verify update signatures.

Roundtrip + negative tests. The algorithm is the RFC 8032 reference, so a valid
sign/verify pair here matches libsodium/minisign; end-to-end interop with the
real minisign CLI is confirmed during release QA once a signing key is embedded.
"""
from app.services import ed25519_pure


def test_sign_verify_roundtrip():
    seed = bytes(range(32))
    pk = ed25519_pure.publickey(seed)
    assert len(pk) == 32
    msg = b"abc123  FolioSenseAI-macOS-arm64-v4.4.0.dmg\n"
    sig = ed25519_pure.sign(msg, seed, pk)
    assert len(sig) == 64
    assert ed25519_pure.verify(pk, sig, msg) is True


def test_tampered_message_fails():
    seed = bytes([3] * 32)
    pk = ed25519_pure.publickey(seed)
    sig = ed25519_pure.sign(b"the original", seed, pk)
    assert ed25519_pure.verify(pk, sig, b"the 0riginal") is False


def test_wrong_key_fails():
    seed1 = bytes([7] * 32)
    seed2 = bytes([9] * 32)
    pk1 = ed25519_pure.publickey(seed1)
    pk2 = ed25519_pure.publickey(seed2)
    sig = ed25519_pure.sign(b"payload", seed1, pk1)
    assert ed25519_pure.verify(pk2, sig, b"payload") is False


def test_bad_lengths_return_false():
    assert ed25519_pure.verify(b"tooshort", b"x" * 64, b"m") is False
    assert ed25519_pure.verify(b"k" * 32, b"shortsig", b"m") is False
