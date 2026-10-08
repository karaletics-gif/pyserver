"""
modules/auth/login_page.py – extensible admin login at /py-login.

Themes (theme.py) and plugins customise the flow through the global
HookRegistry (cookie.hooks.hooks). Hook names:

Filters (value in, value out)
  auth.login.url            (url, request)          URL unauthenticated users are sent to
  auth.login.fields         (fields, request)       list of field dicts; add/remove/reorder inputs
  auth.login.page_context   (ctx, request)          extra template variables / heading text
  auth.login.form_before    (html, request)         raw HTML above the fields
  auth.login.form_after     (html, request)         raw HTML below the fields
  auth.login.validate       (errors, form, request) append error strings; runs BEFORE authentication
  auth.login.credentials    (creds, request)        change {"email", "password"} before checking
  auth.login.allowed        (True, user, request)   return False or an error string to block AFTER
                                                    credentials were verified (e.g. 2FA, IP rules)
  auth.login.error_message  (message, exc, request) rewrite the error shown to the user
  auth.login.redirect       (url, user, request)    where to go after a successful login
  auth.login.response       (response, user, request) final response (extra cookies, headers)

Actions (fire and forget)
  auth.login.before  (request, form)
  auth.login.failed  (email, message, request)
  auth.login.after   (user, request)

A field dict supports: name, label, type, value, placeholder, autocomplete,
required, help, and html (raw markup that replaces the default input).
"""

from __future__ import annotations

from urllib.parse import quote

from core.request import Request
from core.response import Response
from cookie.hooks import hooks
from modules.auth.permissions import can
from modules.auth.service import AuthError, login as auth_login
from modules.auth.sessions import sessions

LOGIN_PATH = "/py-login"
DEFAULT_ADMIN_URL = "/py-admin"
DEFAULT_USER_URL = "/dashboard"


def safe_next(target: str | None) -> str | None:
    """Accept only same-site absolute paths to prevent open redirects."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return None
    if "\\" in target or "\r" in target or "\n" in target:
        return None
    return target


def login_url(request) -> str:
    """URL of the login page, carrying the originally requested path for GET requests."""
    url = LOGIN_PATH
    if getattr(request, "method", "GET") == "GET":
        path = safe_next(getattr(request, "path", None))
        if path and path != LOGIN_PATH:
            url += "?next=" + quote(path, safe="/")
    return hooks.apply_filters("auth.login.url", url, request)


def _default_fields(form: dict) -> list[dict]:
    return [
        {"name": "email", "label": "Email address", "type": "email",
         "placeholder": "you@example.com", "autocomplete": "email",
         "required": True, "value": form.get("email", "")},
        {"name": "password", "label": "Password", "type": "password",
         "placeholder": "", "autocomplete": "current-password",
         "required": True, "value": ""},
    ]


def register_login_routes(router, render) -> None:
    """Register /py-login. *render(template, request, extra) -> str* renders internal templates."""

    def page(request: Request, next_url: str | None, form: dict, error: str | None = None) -> Response:
        fields = hooks.apply_filters("auth.login.fields", _default_fields(form), request)
        ctx = {
            "login_fields": fields,
            "login_next": next_url or "",
            "login_title": "Administrator sign in",
            "login_intro": "Sign in to continue.",
            "login_button": "Sign in",
            "form_before": hooks.apply_filters("auth.login.form_before", "", request),
            "form_after": hooks.apply_filters("auth.login.form_after", "", request),
            "error": error,
        }
        ctx = hooks.apply_filters("auth.login.page_context", ctx, request)
        return Response.html(render("py-login.html", request, ctx))

    def destination(user, next_url: str | None, request: Request) -> str:
        default = next_url or (DEFAULT_ADMIN_URL if can(user, "manage_users") else DEFAULT_USER_URL)
        chosen = hooks.apply_filters("auth.login.redirect", default, user, request)
        return safe_next(chosen) or default

    @router.any(LOGIN_PATH)
    def py_login(request: Request) -> Response:
        next_url = safe_next(request.query_string.get("next") or request.form.get("next"))
        if request.user:
            return Response.redirect(destination(request.user, next_url, request))
        if request.method != "POST":
            return page(request, next_url, {})

        form = dict(request.form)
        email = form.get("email", "").strip()
        try:
            hooks.run_hook("auth.login.before", request, form)
            errors = hooks.apply_filters("auth.login.validate", [], form, request)
            if errors:
                raise AuthError(" ".join(errors))
            creds = hooks.apply_filters(
                "auth.login.credentials",
                {"email": email, "password": form.get("password", "")}, request,
            )
            email = creds["email"]
            user, token = auth_login(creds["email"], creds["password"])
            verdict = hooks.apply_filters("auth.login.allowed", True, user, request)
            if verdict is not True:
                sessions.delete(token)
                raise AuthError(verdict if isinstance(verdict, str) else "Sign in is not permitted.")
        except AuthError as exc:
            message = hooks.apply_filters("auth.login.error_message", str(exc), exc, request)
            hooks.run_hook("auth.login.failed", email, message, request)
            return page(request, next_url, {"email": email}, error=message)

        hooks.run_hook("auth.login.after", user, request)
        response = Response.redirect(destination(user, next_url, request))
        response.set_cookie(sessions.make_cookie(token))
        return hooks.apply_filters("auth.login.response", response, user, request)
