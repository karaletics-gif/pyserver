"""
modules/auth/permissions.py – role-based capability system.

Roles and their capabilities
-----------------------------
  admin    all capabilities
  editor   read + write + publish content
  member   read only

Capabilities (strings)
-----------------------
  "read"              view public and member-only content
  "write_post"        create / edit own posts
  "publish_post"      move posts to 'published'
  "delete_post"       delete any post
  "manage_users"      create / edit / deactivate users
  "manage_settings"   read and write site settings
  "manage_roles"      change other users' roles

Usage
-----
    from modules.auth.permissions import can, require_capability, ROLES

    can(user, "publish_post")           # → True / False
    require_capability("manage_users")  # → decorator factory
"""

from __future__ import annotations

from typing import Callable

# ── Capability registry ───────────────────────────────────────────────────────

# Every known capability (single source of truth)
ALL_CAPABILITIES: frozenset[str] = frozenset({
    "read",
    "write_post",
    "publish_post",
    "delete_post",
    "manage_users",
    "manage_settings",
    "manage_roles",
})

# Role → set of capabilities
ROLES: dict[str, frozenset[str]] = {
    "admin": ALL_CAPABILITIES,

    "editor": frozenset({
        "read",
        "write_post",
        "publish_post",
        "delete_post",
    }),

    "member": frozenset({
        "read",
    }),
}

# Ordered list for UI display
ROLE_HIERARCHY: list[str] = ["admin", "editor", "member"]


# ── Core helpers ──────────────────────────────────────────────────────────────

def capabilities_for(role: str) -> frozenset[str]:
    """Return the capability set for *role* (empty set for unknown roles)."""
    return ROLES.get(role, frozenset())


def can(user, capability: str) -> bool:
    """
    Return True if *user* has *capability*.

    *user* may be any object with a `.role` attribute (e.g. a User ORM
    instance), or None (unauthenticated → no capabilities).
    """
    if user is None:
        return False
    if not user.active:
        return False
    return capability in capabilities_for(getattr(user, "role", ""))


def role_can(role: str, capability: str) -> bool:
    """Return True if *role* grants *capability* (no user object needed)."""
    return capability in capabilities_for(role)


def is_valid_role(role: str) -> bool:
    return role in ROLES


# ── Decorator factory ─────────────────────────────────────────────────────────

def require_capability(capability: str):
    """
    Route decorator factory: abort with 403 if the current user lacks
    *capability*.  Depends on request.user being set by AuthMiddleware.

    Usage
    -----
        @router.get("/admin")
        @require_capability("manage_users")
        def admin_panel(request):
            ...
    """
    def decorator(handler: Callable) -> Callable:
        def wrapper(request, **kwargs):
            from core.response import Response
            user = getattr(request, "user", None)
            if user is None:
                from modules.auth.login_page import login_url
                return Response.redirect(login_url(request))
            if not can(user, capability):
                return Response.html(
                    f"<h1>403 – Forbidden</h1>"
                    f"<p>Requires capability: <code>{capability}</code></p>",
                    status=403,
                )
            return handler(request, **kwargs)
        wrapper.__name__ = handler.__name__
        return wrapper
    return decorator


def require_login(handler: Callable) -> Callable:
    """Simpler decorator: just require any authenticated user."""
    def wrapper(request, **kwargs):
        from core.response import Response
        if getattr(request, "user", None) is None:
            return Response(status=302).set_header("Location", "/login")
        return handler(request, **kwargs)
    wrapper.__name__ = handler.__name__
    return wrapper
