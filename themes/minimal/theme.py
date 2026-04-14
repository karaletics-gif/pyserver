"""
themes/minimal/theme.py

A clean, light, typographic theme. Demonstrates how themes can register
completely different contexts and styles from the default.
"""

THEME_NAME        = "Minimal"
THEME_VERSION     = "1.0.0"
THEME_AUTHOR      = "PyServer"
THEME_DESCRIPTION = "A light, typographic theme focused on reading."
THEME_URL         = ""

# ── Global context ────────────────────────────────────────────────────────────

@hooks.filter("theme.context", priority=10)
def minimal_context(ctx: dict) -> dict:
    site_name = settings.get_value("site_name", "PyServer") if settings else "PyServer"
    ctx.setdefault("site_name",    site_name)
    ctx.setdefault("site_tagline", settings.get_value("site_tagline", "") if settings else "")
    ctx.setdefault("nav_links",    [
        ("Home",  "/"),
        ("Blog",  "/posts"),
        ("About", "/about"),
    ])
    ctx.setdefault("footer_links", [("Home", "/"), ("Login", "/login")])
    ctx.setdefault("current_user", None)
    ctx.setdefault("error",        None)
    ctx.setdefault("flash_ok",     None)
    ctx.setdefault("flash_err",    None)
    return ctx


@hooks.filter("theme.body_class", priority=10)
def body_class(c: str) -> str:
    return (c + " theme-minimal").strip()


@hooks.filter("theme.head", priority=10)
def minimal_head(html: str) -> str:
    return html + '<link rel="preconnect" href="https://fonts.googleapis.com">' \
        + '<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;1,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">'


@hooks.filter("template.index.context", priority=10)
def index_ctx(ctx: dict) -> dict:
    ctx.setdefault("show_hero",      True)
    ctx.setdefault("posts_per_page", 8)
    return ctx


@hooks.filter("template.single.context", priority=10)
def single_ctx(ctx: dict) -> dict:
    ctx["show_hero"] = False
    return ctx


@hooks.filter("template.404.context", priority=10)
def not_found_ctx(ctx: dict) -> dict:
    ctx.setdefault("page_title",   "Page Not Found")
    ctx.setdefault("page_message", "The page you're looking for doesn't exist.")
    return ctx


@hooks.hook("theme.activated", priority=10)
def on_activated(t) -> None:
    print(f"    ✓ Minimal theme hooks registered")


@hooks.filter("template.editor.context", priority=10)
def editor_context(ctx: dict) -> dict:
    ctx.setdefault("editing",     False)
    ctx.setdefault("post",        None)
    ctx.setdefault("revisions",   [])
    ctx.setdefault("can_publish", False)
    ctx.setdefault("can_delete",  False)
    ctx.setdefault("form_title",  "")
    ctx.setdefault("form_body",   "")
    return ctx
