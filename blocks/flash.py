"""
core/flash.py – lightweight cookie-based flash messages.

Flash messages survive exactly one redirect.  Write a message on the
response; read and clear it on the next request.

Usage
-----
    from core.flash import set_flash, get_flash

    # In a POST handler (before redirecting):
    resp = Response.redirect("/dashboard")
    set_flash(resp, "Post published successfully.", kind="ok")
    return resp

    # In the destination GET handler:
    flash = get_flash(request, response)
    # flash = {"message": "Post published...", "kind": "ok"} | None

    # In templates the middleware injects: flash_ok / flash_err / flash_info
"""

from __future__ import annotations

import json
import base64
from core.response import Response


COOKIE_NAME = "pyflash"
COOKIE_MAXAGE = 30      # seconds – just long enough for one redirect


def set_flash(response: Response, message: str, kind: str = "ok") -> None:
    """
    Attach a flash message to *response* via a short-lived cookie.

    kind: "ok" | "err" | "info"
    """
    payload = base64.b64encode(
        json.dumps({"m": message, "k": kind}).encode()
    ).decode()
    response.set_cookie(
        f"{COOKIE_NAME}={payload}; Max-Age={COOKIE_MAXAGE}; Path=/; HttpOnly; SameSite=Lax"
    )


def get_flash(request) -> dict | None:
    """
    Read (and schedule deletion of) the flash cookie on *request*.

    Returns {"message": str, "kind": str} or None.
    The cookie must be cleared on the response; call clear_flash(response)
    after reading.
    """
    raw = request.headers.get("Cookie", "")
    for part in raw.split(";"):
        part = part.strip()
        if part.startswith(f"{COOKIE_NAME}="):
            encoded = part[len(COOKIE_NAME) + 1:]
            try:
                data = json.loads(base64.b64decode(encoded).decode())
                return {"message": data.get("m", ""), "kind": data.get("k", "ok")}
            except Exception:
                return None
    return None


def clear_flash(response: Response) -> None:
    """Expire the flash cookie so it isn't shown again."""
    response.set_cookie(f"{COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")


def inject_flash(request, ctx: dict) -> dict:
    """
    Read flash from request and add flash_ok / flash_err / flash_info
    to *ctx*.  Call once per request in base_ctx().
    """
    flash = get_flash(request)
    ctx.setdefault("flash_ok",   None)
    ctx.setdefault("flash_err",  None)
    ctx.setdefault("flash_info", None)
    if flash:
        kind = flash["kind"]
        if kind == "ok":
            ctx["flash_ok"]   = flash["message"]
        elif kind == "err":
            ctx["flash_err"]  = flash["message"]
        else:
            ctx["flash_info"] = flash["message"]
    return ctx
