"""
modules/auth/middleware.py – authentication middleware for PyServer.

AuthMiddleware wraps the router's dispatch() so that every request
automatically has request.user resolved before the handler runs.

Usage
-----
    from core.router        import Router
    from modules.auth.middleware import AuthMiddleware

    router = Router()
    auth   = AuthMiddleware(router)

    # In the server:
    server = Server(auth, host="0.0.0.0", port=8080)

The middleware is transparent – it simply enriches Request objects and
passes them through. Handlers then access:

    request.user          # User instance or None
    request.is_authenticated   # bool shorthand

Protected routes use the decorators from permissions.py:

    @router.get("/dashboard")
    @require_login
    def dashboard(request): ...

    @router.get("/admin")
    @require_capability("manage_users")
    def admin(request): ...
"""

from __future__ import annotations

from modules.auth.service import get_current_user
from blocks.csrf import CSRFError, validate_csrf
from core.response import Response


class AuthMiddleware:
    """
    Wraps a Router (or any object with a .dispatch() method).

    Responsibilities
    ----------------
    1. Resolve request.user via session cookie before dispatch.
    2. Attach is_authenticated, is_admin convenience booleans.
    3. Pass the request through to the real router unchanged.
    """

    def __init__(self, router) -> None:
        self._router = router

    def dispatch(self, request):
        # Resolve and attach user
        user = get_current_user(request)
        request.user             = user
        request.is_authenticated = user is not None
        request.is_admin         = user is not None and getattr(user, "role", "") == "admin"

        try:
            validate_csrf(request)
        except CSRFError:
            return Response.html("<h1>403 - Invalid or missing CSRF token</h1>", status=403)

        return self._router.dispatch(request)
