"""
themes/default/theme.py

Executed once when the theme is activated. This is the equivalent of
WordPress's functions.php.

Available globals (injected by ThemeLoader):
  hooks    – HookRegistry: register filters and action hooks
  theme    – Theme: the active Theme object
  settings – Setting model (for reading/writing site settings)
"""

# ── Theme metadata ────────────────────────────────────────────────────────────

THEME_NAME        = "Default"
THEME_VERSION     = "1.0.0"
THEME_AUTHOR      = "PyServer"
THEME_DESCRIPTION = "The default dark theme for PyServer."
THEME_URL         = "https://github.com/example/pyserver"

# ── Global context: injected into every template ──────────────────────────────

@hooks.filter("theme.context", priority=10)
def default_global_context(ctx: dict) -> dict:
    """Add site-wide variables every template can use."""
    site_name    = settings.get_value("site_name", "PyServer") if settings else "PyServer"
    site_tagline = settings.get_value("site_tagline", "Built with pure Python") if settings else ""

    ctx.setdefault("site_name",    site_name)
    ctx.setdefault("site_tagline", site_tagline)
    ctx.setdefault("nav_links",    _build_nav())
    ctx.setdefault("footer_links", [("Home", "/"), ("Login", "/login"), ("Register", "/register")])
    ctx.setdefault("current_user", None)
    ctx.setdefault("error",        None)
    ctx.setdefault("flash_ok",     None)
    ctx.setdefault("flash_err",    None)
    return ctx


def _build_nav():
    """Build the primary navigation link list."""
    return [
        ("Home",     "/",         "always"),
        ("Blog",     "/blog",     "always"),
        ("About",    "/about",    "always"),
        ("Dashboard","/dashboard","auth"),
        ("Admin",    "/admin",    "admin"),
    ]


# ── <body> class enrichment ───────────────────────────────────────────────────

@hooks.filter("theme.body_class", priority=10)
def body_class(classes: str) -> str:
    return (classes + " theme-default").strip()


# ── Extra <head> content ──────────────────────────────────────────────────────

@hooks.filter("theme.head", priority=10)
def extra_head(html: str) -> str:
    return html + """
<meta name="generator" content="PyServer">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🐍</text></svg>">
"""


# ── Footer injection ──────────────────────────────────────────────────────────

@hooks.filter("theme.footer", priority=10)
def footer_scripts(html: str) -> str:
    return html + "<!-- Default theme footer -->"


# ── Per-template context enrichment ───────────────────────────────────────────

@hooks.filter("template.index.context", priority=10)
def index_context(ctx: dict) -> dict:
    """Homepage gets a hero flag."""
    ctx.setdefault("show_hero", True)
    ctx.setdefault("posts_per_page", 6)
    return ctx


@hooks.filter("template.single.context", priority=10)
def single_context(ctx: dict) -> dict:
    """Single post: disable hero, enable TOC."""
    ctx["show_hero"] = False
    ctx.setdefault("show_toc", False)
    return ctx


@hooks.filter("template.404.context", priority=10)
def not_found_context(ctx: dict) -> dict:
    ctx.setdefault("page_title",   "Page Not Found")
    ctx.setdefault("page_message", "The page you're looking for doesn't exist or has moved.")
    return ctx


# ── Lifecycle hooks ───────────────────────────────────────────────────────────

@hooks.hook("theme.activated", priority=10)
def on_activated(active_theme) -> None:
    print(f"    ✓ Default theme hooks registered")


@hooks.hook("theme.before_render", priority=10)
def before_render(template_name: str, ctx: dict) -> None:
    pass   # Could log, inject CSRF tokens, etc.


@hooks.hook("theme.after_render", priority=10)
def after_render(template_name: str, html: str) -> None:
    pass   # Could post-process HTML, cache, etc.


@hooks.filter("template.editor.context", priority=10)
def editor_context(ctx: dict) -> dict:
    """Editor page: disable hero, set sensible defaults."""
    ctx.setdefault("editing",     False)
    ctx.setdefault("post",        None)
    ctx.setdefault("revisions",   [])
    ctx.setdefault("can_publish", False)
    ctx.setdefault("can_delete",  False)
    ctx.setdefault("form_title",  "")
    ctx.setdefault("form_body",   "")
    return ctx
