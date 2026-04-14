"""
modules/auth/sessions.py – server-side session store.

Design
------
  • Sessions are stored in memory (a dict keyed by a random token).
  • The token is sent to the browser as an HttpOnly, SameSite=Lax cookie.
  • Each session has a configurable TTL (default 8 hours); idle sessions
    are reaped lazily on every 100th read.
  • For production, swap _store for a Redis/SQLite-backed implementation
    by replacing SessionStore with a compatible class.

Usage
-----
    from modules.auth.sessions import sessions

    # Create
    token = sessions.create(user_id=42, role="admin")

    # Read
    data = sessions.get(token)   # {"user_id": 42, "role": "admin"} or None

    # Destroy
    sessions.delete(token)

    # Cookie helpers
    cookie = sessions.make_cookie(token)     # Set-Cookie header value
    token  = sessions.extract_token(request) # read from Cookie header
"""

from __future__ import annotations

import os
import time
import threading
from typing import Any


# ── Session store ─────────────────────────────────────────────────────────────

class SessionStore:
    """
    Thread-safe in-memory session store.

    Each entry:
        token → {"_created": float, "_accessed": float, **data}
    """

    COOKIE_NAME  = "pysess"
    DEFAULT_TTL  = 8 * 60 * 60   # 8 hours in seconds
    TOKEN_BYTES  = 32
    REAP_EVERY   = 100            # reap expired sessions every N reads

    def __init__(self, ttl: int = DEFAULT_TTL) -> None:
        self._ttl    = ttl
        self._store: dict[str, dict] = {}
        self._lock   = threading.Lock()
        self._reads  = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def create(self, **data: Any) -> str:
        """
        Store *data* under a fresh random token and return the token.

        Typical call: sessions.create(user_id=42, role="admin")
        """
        token = self._new_token()
        now   = time.time()
        with self._lock:
            self._store[token] = {"_created": now, "_accessed": now, **data}
        return token

    def get(self, token: str | None) -> dict | None:
        """
        Return session data dict (without private _ keys), or None if the
        token is missing / expired.
        """
        if not token:
            return None
        with self._lock:
            self._reads += 1
            if self._reads % self.REAP_EVERY == 0:
                self._reap()

            entry = self._store.get(token)
            if entry is None:
                return None
            if time.time() - entry["_created"] > self._ttl:
                del self._store[token]
                return None

            entry["_accessed"] = time.time()
            return {k: v for k, v in entry.items() if not k.startswith("_")}

    def update(self, token: str, **data: Any) -> bool:
        """Merge *data* into an existing session. Returns False if not found."""
        with self._lock:
            if token not in self._store:
                return False
            self._store[token].update(data)
            return True

    def delete(self, token: str) -> None:
        """Destroy a session (logout)."""
        with self._lock:
            self._store.pop(token, None)

    def delete_for_user(self, user_id: int) -> int:
        """Invalidate all sessions belonging to *user_id*. Returns count."""
        with self._lock:
            victims = [t for t, d in self._store.items() if d.get("user_id") == user_id]
            for t in victims:
                del self._store[t]
            return len(victims)

    def count(self) -> int:
        with self._lock:
            return len(self._store)

    # ── Cookie helpers ─────────────────────────────────────────────────────────

    def make_cookie(
        self,
        token: str,
        *,
        max_age: int | None = None,
        path: str = "/",
        http_only: bool = True,
        same_site: str = "Lax",
        secure: bool = False,
    ) -> str:
        """Return a complete Set-Cookie header value for *token*."""
        age   = max_age if max_age is not None else self._ttl
        parts = [f"{self.COOKIE_NAME}={token}", f"Max-Age={age}", f"Path={path}"]
        if http_only:
            parts.append("HttpOnly")
        if same_site:
            parts.append(f"SameSite={same_site}")
        if secure:
            parts.append("Secure")
        return "; ".join(parts)

    def clear_cookie(self) -> str:
        """Return a Set-Cookie value that expires the session cookie."""
        return f"{self.COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"

    def extract_token(self, request) -> str | None:
        """Parse the session token from the request Cookie header."""
        raw = request.headers.get("Cookie", "")
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith(f"{self.COOKIE_NAME}="):
                return part[len(self.COOKIE_NAME) + 1:]
        return None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _new_token(self) -> str:
        return os.urandom(self.TOKEN_BYTES).hex()

    def _reap(self) -> None:
        """Remove expired sessions. Must be called with _lock held."""
        now     = time.time()
        expired = [t for t, d in self._store.items()
                   if now - d["_created"] > self._ttl]
        for t in expired:
            del self._store[t]


# ── Module-level singleton ────────────────────────────────────────────────────

sessions = SessionStore()
