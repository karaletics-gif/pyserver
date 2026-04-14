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
        return False

    try:
        iterations = int(m.group(1))
        salt       = base64.b64decode(m.group(2))
        expected   = base64.b64decode(m.group(3))
    except Exception:
        return False

    actual = _pbkdf2(plaintext.encode(), salt, iterations)
    return hmac.compare_digest(actual, expected)


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
