"""
core/theme_loader.py – WordPress-style theme system for PyServer.

Architecture
------------
  ThemeLoader        Discovers themes, activates one, runs its theme.py,
                     and provides render() with theme-scoped templates.

  Theme              Wraps a single theme's directory + metadata.
                     Delegates rendering to the shared TemplateEngine.

  theme.py           Each theme's "functions.php" equivalent.  Executed
                     once at activation time inside a context that provides:
                       • hooks    – the global HookRegistry
                       • theme    – the active Theme object
                       • settings – the Settings model helper

Theme directory layout
----------------------
  themes/
    my_theme/
      theme.py          ← executed on activation (required)
      index.html        ← homepage / post list
      single.html       ← single post view
      page.html         ← CMS page view
      archive.html      ← category / date archive
      404.html          ← not-found page
      layout.html       ← optional base layout (used by includes/extends)
      partials/         ← include-able fragments
        nav.html
        footer.html
        ...

Filter hooks themes can use
---------------------------
  "theme.context"           dict  – enrich the global template context
  "theme.body_class"        str   – CSS classes on <body>
  "theme.head"              str   – extra <head> content
  "theme.footer"            str   – extra content before </body>
  "template.{name}.context" dict  – enrich context for a specific template

Action hooks
------------
  "theme.activated"         (theme)   – fired when a theme is loaded
  "theme.before_render"     (name, ctx) – before any template renders
  "theme.after_render"      (name, html) – after any template renders

Public API
----------
  loader = ThemeLoader("themes/")
  loader.activate("default")

  html = loader.render("index", context)      # renders themes/default/index.html
  html = loader.render("single", context)     # falls back to index if missing
  html = loader.render_404(context)
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from typing import Any

from cookie.template_engine import TemplateEngine
from cookie.hooks           import HookRegistry


# ── Theme metadata keys (read from theme.py module attributes) ───────────────

_META_KEYS = (
    "THEME_NAME",
    "THEME_VERSION",
    "THEME_AUTHOR",
    "THEME_DESCRIPTION",
    "THEME_URL",
)


class ThemeError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Theme object
# ─────────────────────────────────────────────────────────────────────────────

class Theme:
    """
    Represents one installed theme.

    Attributes
    ----------
    slug        : directory name (e.g. "default")
    path        : absolute filesystem path to the theme directory
    name        : human-readable name from THEME_NAME in theme.py
    version     : semver string
    author      : author name/email
    description : short description
    engine      : TemplateEngine scoped to this theme's directory
    hooks       : the global HookRegistry (shared across everything)
    _module     : the executed theme.py module (for introspection)
    """

    def __init__(self, slug: str, path: str, hooks: HookRegistry) -> None:
        self.slug        = slug
        self.path        = path
        self.hooks       = hooks
        self.engine      = TemplateEngine(base_dir=path)

        # Populated by _load_metadata() after theme.py runs
        self.name        = slug
        self.version     = "1.0.0"
        self.author      = ""
        self.description = ""
        self.url         = ""
        self._module     = None
        self._functions  = {}   # callables registered by theme.py

    # ── Metadata ──────────────────────────────────────────────────────────────

    def _load_metadata(self) -> None:
        mod = self._module
        if mod is None:
            return
        self.name        = getattr(mod, "THEME_NAME",        self.slug)
        self.version     = getattr(mod, "THEME_VERSION",     "1.0.0")
        self.author      = getattr(mod, "THEME_AUTHOR",      "")
        self.description = getattr(mod, "THEME_DESCRIPTION", "")
        self.url         = getattr(mod, "THEME_URL",         "")

    # ── Template resolution ───────────────────────────────────────────────────

    def has_template(self, name: str) -> bool:
        """Return True if {name}.html exists in the theme directory."""
        return os.path.isfile(os.path.join(self.path, f"{name}.html"))

    def resolve_template(self, name: str) -> str:
        """
        Return the template name to use, applying a fallback chain.

        single → page → index
        archive → index
        404 → index
        """
        fallback_chain = {
            "single":  ["single",  "page",  "index"],
            "page":    ["page",    "single", "index"],
            "archive": ["archive", "index"],
            "404":     ["404",     "index"],
            "search":  ["search",  "index"],
        }
        # For unknown template names not in the fallback chain,
        # only try the exact name — no silent index fallback.
        if name not in fallback_chain:
            candidates = [name]
        else:
            candidates = fallback_chain[name]
        for candidate in candidates:
            if self.has_template(candidate):
                return candidate
        raise ThemeError(
            f"Theme '{self.slug}' has no usable template for '{name}'. "
            f"Expected at least index.html."
        )

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render(self, template_name: str, context: dict | None = None) -> str:
        """
        Render a theme template.

        1. Resolve template with fallback chain.
        2. Build global context (hooks.apply_filters("theme.context", ctx)).
        3. Apply per-template context filter.
        4. Fire before/after render hooks.
        5. Render with TemplateEngine.
        """
        ctx = dict(context or {})

        # Inject theme metadata into every template context
        ctx.setdefault("theme",        self)
        ctx.setdefault("theme_name",   self.name)
        ctx.setdefault("theme_slug",   self.slug)
        ctx.setdefault("theme_path",   self.path)
        ctx.setdefault("theme_url",    f"/themes/{self.slug}")

        # Global context enrichment via filter
        ctx = self.hooks.apply_filters("theme.context", ctx)

        # Per-template context enrichment
        ctx = self.hooks.apply_filters(f"template.{template_name}.context", ctx)

        # Extra <head> / <body class> / footer slots
        ctx.setdefault("theme_head",       self.hooks.apply_filters("theme.head", ""))
        ctx.setdefault("theme_body_class", self.hooks.apply_filters("theme.body_class", ""))
        ctx.setdefault("theme_footer",     self.hooks.apply_filters("theme.footer", ""))

        resolved = self.resolve_template(template_name)

        self.hooks.run_hook("theme.before_render", resolved, ctx)

        html = self.engine.render_file(f"{resolved}.html", ctx)

        self.hooks.run_hook("theme.after_render", resolved, html)

        return html

    # ── Convenience ───────────────────────────────────────────────────────────

    def render_404(self, context: dict | None = None) -> str:
        ctx = dict(context or {})
        ctx.setdefault("page_title", "Page Not Found")
        return self.render("404", ctx)

    def get_asset_url(self, filename: str) -> str:
        """Return a URL to a theme asset (CSS, JS, image)."""
        return f"/themes/{self.slug}/assets/{filename}"

    def __repr__(self) -> str:
        return f"<Theme slug={self.slug!r} name={self.name!r}>"


# ─────────────────────────────────────────────────────────────────────────────
# Theme loader
# ─────────────────────────────────────────────────────────────────────────────

class ThemeLoader:
    """
    Discovers, loads, and activates themes.

    Usage
    -----
        hooks  = HookRegistry()
        loader = ThemeLoader("themes/", hooks=hooks)
        loader.activate("default")

        html = loader.render("index", {"posts": [...]})

    The active theme persists for the lifetime of the process.
    Call loader.activate() again to hot-swap themes.
    """

    def __init__(
        self,
        themes_dir: str = "themes",
        hooks: HookRegistry | None = None,
    ) -> None:
        self.themes_dir = os.path.abspath(themes_dir)
        self.hooks      = hooks or HookRegistry()
        self._active:   Theme | None = None
        self._registry: dict[str, Theme] = {}

    # ── Discovery ─────────────────────────────────────────────────────────────

    def discover(self) -> list[str]:
        """Return slugs of all directories inside themes_dir that have theme.py."""
        if not os.path.isdir(self.themes_dir):
            return []
        slugs = []
        for entry in sorted(os.listdir(self.themes_dir)):
            candidate = os.path.join(self.themes_dir, entry)
            if os.path.isdir(candidate) and os.path.isfile(
                os.path.join(candidate, "theme.py")
            ):
                slugs.append(entry)
        return slugs

    def available(self) -> list[Theme]:
        """
        Return Theme objects for every discovered theme.
        Themes are loaded (metadata only, not activated).
        """
        result = []
        for slug in self.discover():
            theme = self._load(slug)
            result.append(theme)
        return result

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self, slug: str) -> Theme:
        """Load (but do not activate) a theme by slug."""
        if slug in self._registry:
            return self._registry[slug]

        path = os.path.join(self.themes_dir, slug)
        if not os.path.isdir(path):
            raise ThemeError(f"Theme directory not found: {path}")

        functions_path = os.path.join(path, "theme.py")
        if not os.path.isfile(functions_path):
            raise ThemeError(f"theme.py missing from theme '{slug}': {functions_path}")

        if not os.path.isfile(os.path.join(path, "index.html")):
            raise ThemeError(f"Theme '{slug}' has no index.html (required fallback).")

        theme = Theme(slug=slug, path=path, hooks=self.hooks)
        self._registry[slug] = theme
        return theme

    # ── Activation ────────────────────────────────────────────────────────────

    def activate(self, slug: str) -> Theme:
        """
        Load and activate a theme.

        1. Load the theme directory.
        2. Execute theme.py in a sandboxed namespace.
        3. Fire "theme.activated" hook.
        4. Store as active theme.
        """
        theme = self._load(slug)
        self._execute_functions(theme)
        theme._load_metadata()

        self._active = theme
        self.hooks.run_hook("theme.activated", theme)

        print(f"  🎨  Theme activated: {theme.name!r} (v{theme.version})")
        return theme

    def _execute_functions(self, theme: Theme) -> None:
        """
        Execute theme.py inside a controlled namespace.

        The namespace exposes:
          hooks    – HookRegistry (global, shared)
          theme    – the Theme object being activated
          settings – Settings.get_value / Settings.set_value helpers
          __file__ – the theme.py path (so relative imports work)
        """
        functions_path = os.path.join(theme.path, "theme.py")

        # Build the execution namespace
        namespace: dict[str, Any] = {
            "__file__":    functions_path,
            "__name__":    f"themes.{theme.slug}.theme",
            "__builtins__": __builtins__,
            "hooks":       self.hooks,
            "theme":       theme,
        }

        # Lazily inject Settings to avoid circular imports at module load time
        try:
            from modules.settings.model import Setting
            namespace["settings"] = Setting
        except ImportError:
            namespace["settings"] = None

        try:
            with open(functions_path, encoding="utf-8") as fh:
                source = fh.read()
            code = compile(source, functions_path, "exec")
            exec(code, namespace)  # noqa: S102
        except Exception:
            raise ThemeError(
                f"Error executing theme.py for theme '{theme.slug}':\n"
                + traceback.format_exc()
            )

        # Store the namespace so theme.py can register named functions
        theme._module  = type(sys)("theme")
        theme._module.__dict__.update(namespace)

    # ── Rendering ─────────────────────────────────────────────────────────────

    @property
    def active(self) -> Theme:
        if self._active is None:
            raise ThemeError(
                "No theme is active. Call ThemeLoader.activate(slug) first."
            )
        return self._active

    def render(self, template_name: str, context: dict | None = None) -> str:
        """Render *template_name* with the active theme."""
        return self.active.render(template_name, context)

    def render_404(self, context: dict | None = None) -> str:
        return self.active.render_404(context)

    # ── Hot-swap ──────────────────────────────────────────────────────────────

    def switch(self, slug: str) -> Theme:
        """
        Switch to a different theme at runtime.

        Clears any hooks registered by the previous theme's theme.py
        that are namespaced under "theme.*", then activates the new one.
        On failure, re-activates the previously active theme so the site
        remains functional.
        """
        previous_slug = self._active.slug if self._active else None

        # Snapshot current theme hooks so we can restore on failure
        hooks_backup  = {k: list(v) for k, v in self.hooks._hooks.items()}
        filter_backup = {k: list(v) for k, v in self.hooks._filters.items()}

        # Clear theme-specific hooks so old registrations don't bleed over
        for hook_name in list(self.hooks._hooks.keys()):
            if hook_name.startswith("theme.") or hook_name.startswith("template."):
                self.hooks._hooks[hook_name] = []
        for filt_name in list(self.hooks._filters.keys()):
            if filt_name.startswith("theme.") or filt_name.startswith("template."):
                self.hooks._filters[filt_name] = []

        # Evict from registry so theme.py re-executes cleanly
        self._registry.pop(slug, None)

        try:
            return self.activate(slug)
        except ThemeError:
            # Restore hooks to pre-switch state
            self.hooks._hooks.update(hooks_backup)
            self.hooks._filters.update(filter_backup)
            # Re-activate previous theme to keep the site running
            if previous_slug and previous_slug != slug:
                self._registry.pop(previous_slug, None)
                try:
                    self.activate(previous_slug)
                except ThemeError:
                    pass
            raise

    # ── Static asset serving ──────────────────────────────────────────────────

    def serve_asset(self, slug: str, filename: str) -> bytes | None:
        """
        Read and return raw bytes for a theme asset.
        Returns None if the file doesn't exist.
        """
        safe_filename = os.path.normpath(filename).lstrip("/\\")
        asset_path    = os.path.join(self.themes_dir, slug, "assets", safe_filename)
        # Prevent path traversal outside the theme's assets directory
        expected_root = os.path.join(self.themes_dir, slug, "assets")
        if not os.path.abspath(asset_path).startswith(os.path.abspath(expected_root)):
            return None
        if not os.path.isfile(asset_path):
            return None
        with open(asset_path, "rb") as fh:
            return fh.read()

    # ── Introspection ─────────────────────────────────────────────────────────

    def info(self) -> dict:
        """Return a summary dict for the active theme."""
        t = self.active
        return {
            "slug":        t.slug,
            "name":        t.name,
            "version":     t.version,
            "author":      t.author,
            "description": t.description,
            "templates":   [
                f[:-5] for f in os.listdir(t.path)
                if f.endswith(".html")
            ],
            "has_partials": os.path.isdir(os.path.join(t.path, "partials")),
        }

    def __repr__(self) -> str:
        active = self._active.slug if self._active else "none"
        return f"<ThemeLoader themes_dir={self.themes_dir!r} active={active!r}>"
