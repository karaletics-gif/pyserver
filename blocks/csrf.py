"""
core/csrf.py – double-submit CSRF protection.

How it works
------------
1. On every GET response, a random token is stored in the session.
2. POST forms include the token in a hidden field <input name="_csrf">.
3. Before processing any POST/PUT/DELETE, validate the submitted token
   against the session token.
4. Mismatch → 403 Forbidden.

Usage
-----
    from core.csrf import csrf_token_for, validate_csrf, CSRFError

    # In a GET handler – get the token to embed in the form:
    token = csrf_token_for(request)

    # In a POST handler – validate before processing:
    try:
        validate_csrf(request)
    except CSRFError:
        return Response.html("<h1>403 Invalid CSRF token</h1>", status=403)

    # Or use the decorator:
    @csrf_protect
    def my_post_handler(request): ...

    # Template helper (theme.py or base_ctx):
    ctx["csrf_token"] = csrf_token_for(request)
    # Template: <input type="hidden" name="_csrf" value="<?= csrf_token ?>">
"""

from __future__ import annotations

import os
import functools
from core.response import Response


_SESSION_KEY = "csrf_token"
_FORM_FIELD  = "_csrf"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CSRFError(Exception):
    pass


def csrf_token_for(request) -> str:
    """
    Return the CSRF token for this session, creating one if needed.
    Requires request.user to be resolved (middleware must have run).
    """
    from modules.auth.sessions import sessions

    # Extract session token from cookie
    token = sessions.extract_token(request)
    if not token:
        return ""

    data = sessions.get(token)
    if data is None:
        return ""

    if _SESSION_KEY not in data:
        csrf = os.urandom(16).hex()
        sessions.update(token, **{_SESSION_KEY: csrf})
    else:
        csrf = data[_SESSION_KEY]

    return csrf


def validate_csrf(request) -> None:
    """
    Raise CSRFError if the submitted _csrf token doesn't match the session.
    Safe methods (GET, HEAD) are always allowed.
    """
    if request.method in _SAFE_METHODS:
        return

    expected = csrf_token_for(request)
    if not expected:
        # No session → no CSRF protection needed (anon POST like login/register)
        return

    submitted = (
        request.form.get(_FORM_FIELD, "")
        or request.headers.get("X-CSRF-Token", "")
    )

    import hmac
    if not hmac.compare_digest(expected, submitted):
        raise CSRFError("CSRF token invalid or missing.")


def csrf_protect(handler):
    """Decorator: validate CSRF on unsafe methods, 403 on failure."""
    @functools.wraps(handler)
    def wrapper(request, **kwargs):
        try:
            validate_csrf(request)
        except CSRFError:
            return Response.html(
                "<h1>403 – Invalid or missing CSRF token</h1>"
                "<p><a href='javascript:history.back()'>Go back</a></p>",
                status=403,
            )
        return handler(request, **kwargs)
    return wrapper
