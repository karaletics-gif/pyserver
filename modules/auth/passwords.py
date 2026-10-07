"""
modules/auth/passwords.py – secure password hashing (stdlib only).

Algorithm  : PBKDF2-HMAC-SHA256
Iterations : 600 000  (OWASP 2023 recommendation for PBKDF2-SHA256)
Salt       : 16 random bytes, base64-encoded
Format     : "pbkdf2$<iters>$<b64-salt>$<b64-hash>"

Usage
-----
    from modules.auth.passwords import hash_password, verify_password

    stored = hash_password("hunter2")
    ok     = verify_password("hunter2", stored)   # True
    bad    = verify_password("wrong",   stored)   # False
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

# ── Constants ─────────────────────────────────────────────────────────────────

_ALGO       = "sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 16
_HASH_BYTES = 32
_SEPARATOR  = "$"
_PREFIX     = "pbkdf2"

_STORED_RE  = re.compile(
    r"^pbkdf2\$(\d+)\$([A-Za-z0-9+/=]+)\$([A-Za-z0-9+/=]+)$"
)
_PHPASS_CHARS = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def validate_password(plaintext: str, allow_weak: bool = False) -> None:
    """Require a strong password unless the user explicitly opts into weaker ones."""
    if allow_weak:
        if len(plaintext) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return
    if len(plaintext) < 12:
        raise ValueError("Use at least 12 characters, or explicitly confirm a weaker password.")
    categories = (
        any(char.islower() for char in plaintext),
        any(char.isupper() for char in plaintext),
        any(char.isdigit() for char in plaintext),
        any(not char.isalnum() for char in plaintext),
    )
    if sum(categories) < 3:
        raise ValueError("Use at least three of lowercase, uppercase, numbers, and symbols, or explicitly confirm a weaker password.")


# ── Core functions ────────────────────────────────────────────────────────────

def hash_password(plaintext: str, iterations: int = _ITERATIONS) -> str:
    """
    Return a storable hash string for *plaintext*.

    The returned string is safe to store directly in the database.
    """
    if not plaintext:
        raise ValueError("Password must not be empty.")

    salt   = os.urandom(_SALT_BYTES)
    digest = _pbkdf2(plaintext.encode(), salt, iterations)

    b64_salt = base64.b64encode(salt).decode()
    b64_hash = base64.b64encode(digest).decode()

    return f"{_PREFIX}{_SEPARATOR}{iterations}{_SEPARATOR}{b64_salt}{_SEPARATOR}{b64_hash}"


def verify_password(plaintext: str, stored: str) -> bool:
    """
    Return True iff *plaintext* matches the *stored* hash.

    Uses a constant-time comparison to defeat timing attacks.
    Returns False (never raises) on malformed stored values.
    """
    m = _STORED_RE.match(stored or "")
    if not m:
        return _verify_phpass(plaintext, stored or "")

    try:
        iterations = int(m.group(1))
        salt       = base64.b64decode(m.group(2))
        expected   = base64.b64decode(m.group(3))
    except Exception:
        return False

    actual = _pbkdf2(plaintext.encode(), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _verify_phpass(plaintext: str, stored: str) -> bool:
    """Verify WordPress's portable phpass hashes before transparently rehashing."""
    if len(stored) != 34 or stored[:3] not in ("$P$", "$H$"):
        return False
    try:
        count_log2 = _PHPASS_CHARS.index(stored[3])
        salt = stored[4:12].encode("ascii")
        expected = stored[12:]
        if count_log2 < 7 or count_log2 > 20:
            return False
        digest = hashlib.md5(salt + plaintext.encode()).digest()
        for _ in range(1 << count_log2):
            digest = hashlib.md5(digest + plaintext.encode()).digest()
        actual = _phpass_encode64(digest)
    except (ValueError, UnicodeEncodeError):
        return False
    return hmac.compare_digest(actual, expected)


def _phpass_encode64(data: bytes) -> str:
    output = []
    index = 0
    while index < len(data):
        value = data[index]
        index += 1
        output.append(_PHPASS_CHARS[value & 0x3F])
        if index < len(data):
            value |= data[index] << 8
        output.append(_PHPASS_CHARS[(value >> 6) & 0x3F])
        if index >= len(data):
            break
        index += 1
        if index < len(data):
            value |= data[index] << 16
        output.append(_PHPASS_CHARS[(value >> 12) & 0x3F])
        if index >= len(data):
            break
        index += 1
        output.append(_PHPASS_CHARS[(value >> 18) & 0x3F])
    return "".join(output)


def needs_rehash(stored: str, iterations: int = _ITERATIONS) -> bool:
    """
    Return True if *stored* was hashed with fewer iterations than the
    current default – use this to silently upgrade hashes on login.
    """
    m = _STORED_RE.match(stored or "")
    if not m:
        return True
    return int(m.group(1)) < iterations


# ── Internal ──────────────────────────────────────────────────────────────────

def _pbkdf2(password: bytes, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(_ALGO, password, salt, iterations, dklen=_HASH_BYTES)
