"""Pure-Python Ed25519 (RFC 8032), used only to verify update signatures.

Why hand-rolled instead of a library: the app is packaged with PyInstaller and
the plan deliberately keeps the dependency/audit surface small (curl_cffi etc.
are already packaging-sensitive). Adding ``cryptography``/``pynacl`` just to
verify one tiny signature at update time is not worth the freezing risk.

Verification touches no secret material, so the usual "don't roll your own
crypto" timing-side-channel concern doesn't apply here — the only requirement is
correctness, and this is the canonical RFC 8032 reference algorithm. ``sign`` is
included for tests (to construct signatures); production only calls ``verify``.
"""
from __future__ import annotations

import hashlib

# Single-letter constants below mirror RFC 8032 notation (b, q, L, d, I, B) for
# readability against the spec; keep them as-is rather than shouting-case.
# pylint: disable=invalid-name

_b = 256
_q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _inv(x: int) -> int:
    return pow(x, _q - 2, _q)


_d = -121665 * _inv(121666) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = 4 * _inv(5) % _q
_Bx = _xrecover(_By)
_B = (_Bx % _q, _By % _q)


def _edwards(p: tuple[int, int], quad: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p
    x2, y2 = quad
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _d * x1 * x2 * y1 * y2)
    return (x3 % _q, y3 % _q)


def _scalarmult(p: tuple[int, int], e: int) -> tuple[int, int]:
    if e == 0:
        return (0, 1)
    acc = _scalarmult(p, e // 2)
    acc = _edwards(acc, acc)
    if e & 1:
        acc = _edwards(acc, p)
    return acc


def _encodeint(y: int) -> bytes:
    return y.to_bytes(_b // 8, "little")


def _encodepoint(p: tuple[int, int]) -> bytes:
    x, y = p
    bits = y | ((x & 1) << (_b - 1))
    return bits.to_bytes(_b // 8, "little")


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def publickey(seed: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte Ed25519 seed."""
    h = _sha512(seed)
    a = 2 ** (_b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _b - 2))
    point = _scalarmult(_B, a)
    return _encodepoint(point)


def _hint(m: bytes) -> int:
    h = _sha512(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * _b))


def sign(message: bytes, seed: bytes, public_key: bytes) -> bytes:
    """Produce a 64-byte Ed25519 signature. Used by tests only."""
    h = _sha512(seed)
    a = 2 ** (_b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _b - 2))
    r = _hint(h[_b // 8:_b // 4] + message)
    big_r = _scalarmult(_B, r)
    s = (r + _hint(_encodepoint(big_r) + public_key + message) * a) % _L
    return _encodepoint(big_r) + _encodeint(s)


def _isoncurve(p: tuple[int, int]) -> bool:
    x, y = p
    return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0


def _decodeint(s: bytes) -> int:
    return int.from_bytes(s, "little")


def _decodepoint(s: bytes) -> tuple[int, int]:
    y = int.from_bytes(s, "little") & ((1 << (_b - 1)) - 1)
    x = _xrecover(y)
    if x & 1 != _bit(s, _b - 1):
        x = _q - x
    point = (x, y)
    if not _isoncurve(point):
        raise ValueError("decoding point that is not on curve")
    return point


def verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """Return True iff ``signature`` is a valid Ed25519 signature of ``message``."""
    try:
        if len(signature) != _b // 4 or len(public_key) != _b // 8:
            return False
        big_r = _decodepoint(signature[: _b // 8])
        a = _decodepoint(public_key)
        s = _decodeint(signature[_b // 8: _b // 4])
        h = _hint(_encodepoint(big_r) + public_key + message)
        left = _scalarmult(_B, s)
        right = _edwards(big_r, _scalarmult(a, h))
        return left == right
    except (ValueError, IndexError):
        return False
