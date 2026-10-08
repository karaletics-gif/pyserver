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
import io
import os
import posixpath
import re
import shutil
import sys
import tempfile
import traceback
import zipfile
from typing import Any, Callable

from cookie.template_engine import TemplateEngine
from cookie.hooks           import HookRegistry

_SLUG_RE   = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PARENT_RE = re.compile(r"^THEME_PARENT\s*=\s*[\"']([A-Za-z0-9_-]+)[\"']", re.M)
MAX_ZIP_FILES = 2000
MAX_ZIP_UNPACKED = 50 * 1024 * 1024
SCREENSHOTS = ("screenshot.png", "screenshot.jpg", "screenshot.jpeg", "screenshot.webp")


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
        self.template_dir = path   # merged parent+child directory for child themes

        # Populated by _load_metadata() after theme.py runs
        self.name        = slug
        self.version     = "1.0.0"
        self.author      = ""
        self.description = ""
        self.url         = ""
        self.supports    = None   # None = every customisation feature
        self.widget_areas = {"sidebar": "Sidebar", "footer": "Footer"}
        self.parent_slug = self._read_parent()
        self._module     = None
        self._functions  = {}   # callables registered by theme.py

    @property
    def is_child(self) -> bool:
        return bool(self.parent_slug)

    @property
    def screenshot_url(self) -> str:
        for name in SCREENSHOTS:
            if os.path.isfile(os.path.join(self.path, name)) or \
               os.path.isfile(os.path.join(self.path, "assets", name)):
                return f"/themes/{self.slug}/assets/{name}"
        return ""

    def _read_parent(self) -> str:
        try:
            with open(os.path.join(self.path, "theme.py"), encoding="utf-8") as fh:
                match = _PARENT_RE.search(fh.read())
        except OSError:
            return ""
        return match.group(1) if match else ""

    def supports_feature(self, feature: str) -> bool:
        return self.supports is None or feature in self.supports

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
        supports         = getattr(mod, "THEME_SUPPORTS",    None)
        self.supports    = set(supports) if supports is not None else None
        self.widget_areas = dict(getattr(mod, "THEME_WIDGET_AREAS", self.widget_areas))

    # ── Template resolution ───────────────────────────────────────────────────

    def has_template(self, name: str) -> bool:
        """Return True if {name}.html exists in the theme (or merged child) directory."""
        return os.path.isfile(os.path.join(self.template_dir, f"{name}.html"))

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

        for key, value in {
            "current_user": None,
            "csrf_token": "",
            "posts": [],
            "post": None,
            "page": None,
            "query": "",
            "results": [],
            "page_title": None,
            "page_message": None,
            "current_page": 1,
            "total_pages": None,
            "prev_page": None,
            "next_page": None,
        }.items():
            ctx.setdefault(key, value)

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
        html = self.hooks.apply_filters("theme.html", html)

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
        cache_dir: str | None = None,
    ) -> None:
        self.themes_dir = os.path.abspath(themes_dir)
        self.hooks      = hooks or HookRegistry()
        self.cache_dir  = os.path.abspath(cache_dir or os.path.join(
            os.path.dirname(self.themes_dir), "instance", "theme-cache"))
        self._active:   Theme | None = None
        self._registry: dict[str, Theme] = {}
        # (kind, name, fn, priority) re-registered after every activation
        self._core: list[tuple[str, str, Callable, int]] = []

    def add_core_filter(self, name: str, fn: Callable, priority: int = 10) -> None:
        """Register a filter that survives theme switches (theme.* hooks are cleared on switch)."""
        self._core.append(("filter", name, fn, priority))
        self._apply_core()

    def _apply_core(self) -> None:
        for _kind, name, fn, priority in self._core:
            self.hooks.remove_filter(name, fn)
            self.hooks.add_filter(name, fn, priority)

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

        theme = Theme(slug=slug, path=path, hooks=self.hooks)
        if not theme.is_child and not os.path.isfile(os.path.join(path, "index.html")):
            raise ThemeError(f"Theme '{slug}' has no index.html (required fallback).")
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
        parent = self._load_parent(theme)
        self._execute_functions(theme)
        if parent is not None:
            self._execute_functions(parent)
            self._merge_templates(theme, parent)
        theme._load_metadata()
        if parent is not None:
            parent._load_metadata()
        self._apply_core()

        self._active = theme
        self.hooks.run_hook("theme.activated", theme)

        print(f"  🎨  Theme activated: {theme.name!r} (v{theme.version})")
        return theme

    def _load_parent(self, theme: Theme) -> Theme | None:
        if not theme.is_child:
            return None
        if theme.parent_slug == theme.slug:
            raise ThemeError(f"Theme '{theme.slug}' cannot be its own parent.")
        if theme.parent_slug not in self.discover():
            raise ThemeError(
                f"Parent theme '{theme.parent_slug}' of '{theme.slug}' is not installed.")
        parent = self._load(theme.parent_slug)
        if parent.is_child:
            raise ThemeError(f"Parent theme '{parent.slug}' is itself a child theme.")
        return parent

    def _merge_templates(self, child: Theme, parent: Theme) -> None:
        """Build instance/theme-cache/<child>: parent templates overlaid with the child's."""
        target = os.path.join(self.cache_dir, child.slug)
        shutil.rmtree(target, ignore_errors=True)
        skip = shutil.ignore_patterns("theme.py", "assets", "__pycache__")
        shutil.copytree(parent.path, target, ignore=skip)
        shutil.copytree(child.path, target, ignore=skip, dirs_exist_ok=True)
        child.template_dir = target
        child.engine = TemplateEngine(base_dir=target)

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
            from cms.settings.model import Setting
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
        self._registry.pop(self._parent_of(slug), None)

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
        if not _SLUG_RE.match(slug or ""):
            return None
        safe_filename = os.path.normpath(filename).lstrip("/\\")
        for candidate in (slug, self._parent_of(slug)):
            if not candidate:
                continue
            root = os.path.abspath(os.path.join(self.themes_dir, candidate, "assets"))
            asset_path = os.path.abspath(os.path.join(root, safe_filename))
            # Prevent path traversal outside the theme's assets directory
            if not asset_path.startswith(root + os.sep):
                return None
            if not os.path.isfile(asset_path) and safe_filename in SCREENSHOTS:
                asset_path = os.path.join(self.themes_dir, candidate, safe_filename)
            if os.path.isfile(asset_path):
                with open(asset_path, "rb") as fh:
                    return fh.read()
        return None

    def _parent_of(self, slug: str) -> str:
        if not _SLUG_RE.match(slug or ""):
            return ""
        path = os.path.join(self.themes_dir, slug)
        if not os.path.isdir(path):
            return ""
        return self._load(slug).parent_slug if slug in self.discover() else ""

    # ── Install / delete / scaffold ────────────────────────────────────────────

    def install_zip(self, data: bytes, fallback_name: str = "theme") -> str:
        """
        Validate and extract a theme zip into themes_dir. Returns the new slug.

        The archive may contain one top-level folder (with theme.py inside) or the
        theme files directly at its root. Unsafe paths, symlinks, oversized archives
        and existing slugs are rejected.
        """
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ThemeError("The uploaded file is not a valid zip archive.")
        members = [m for m in archive.infolist() if not m.filename.startswith("__MACOSX/")]
        if not members or len(members) > MAX_ZIP_FILES:
            raise ThemeError("The archive is empty or contains too many files.")
        if sum(m.file_size for m in members) > MAX_ZIP_UNPACKED:
            raise ThemeError("The archive is too large when unpacked.")
        for m in members:
            name = m.filename
            clean = posixpath.normpath(name)
            if (name.startswith(("/", "\\")) or "\\" in name or ":" in name.split("/")[0]
                    or clean == ".." or clean.startswith("../")):
                raise ThemeError(f"Unsafe path in archive: {name}")
            if (m.external_attr >> 16) & 0o170000 == 0o120000:
                raise ThemeError(f"Symbolic links are not allowed: {name}")

        names = [m.filename for m in members]
        tops = {n.split("/")[0] for n in names if n.strip("/")}
        if len(tops) == 1 and f"{next(iter(tops))}/theme.py" in names:
            prefix, base = next(iter(tops)) + "/", next(iter(tops))
        elif "theme.py" in names:
            prefix, base = "", fallback_name
        else:
            raise ThemeError("theme.py was not found. A theme needs theme.py and index.html.")
        slug = re.sub(r"[^a-z0-9_-]+", "-", base.lower()).strip("-_")[:64]
        if not _SLUG_RE.match(slug):
            raise ThemeError("The theme folder name is not valid.")

        source = archive.read(prefix + "theme.py").decode("utf-8", errors="replace")
        try:
            compile(source, "theme.py", "exec")
        except SyntaxError as exc:
            raise ThemeError(f"theme.py has a syntax error: {exc}")
        if not _PARENT_RE.search(source) and (prefix + "index.html") not in names:
            raise ThemeError("index.html was not found in the theme.")
        dest = os.path.join(self.themes_dir, slug)
        if os.path.exists(dest):
            raise ThemeError(f"Theme '{slug}' is already installed.")

        os.makedirs(self.themes_dir, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".install-", dir=self.themes_dir)
        try:
            for m in members:
                if not m.filename.startswith(prefix) or m.filename.endswith("/"):
                    continue
                target = os.path.abspath(os.path.join(staging, m.filename[len(prefix):]))
                if not target.startswith(os.path.abspath(staging) + os.sep):
                    raise ThemeError(f"Unsafe path in archive: {m.filename}")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
            os.replace(staging, dest)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self._registry.pop(slug, None)
        return slug

    def delete_theme(self, slug: str) -> None:
        """Delete an installed theme; the active theme and its parent cannot be removed."""
        if slug not in self.discover():
            raise ThemeError("That theme is not installed.")
        active = self._active
        if active and slug in (active.slug, active.parent_slug):
            raise ThemeError("The active theme (or its parent) cannot be deleted.")
        shutil.rmtree(os.path.join(self.themes_dir, slug))
        shutil.rmtree(os.path.join(self.cache_dir, slug), ignore_errors=True)
        self._registry.pop(slug, None)

    def children_of(self, slug: str) -> list[str]:
        return [t.slug for t in self.available() if t.parent_slug == slug]

    def create_child_theme(self, parent_slug: str, name: str) -> str:
        """Scaffold themes/<slug>/ that inherits everything from *parent_slug*."""
        parents = {t.slug: t for t in self.available()}
        if parent_slug not in parents:
            raise ThemeError("Choose an installed parent theme.")
        if parents[parent_slug].is_child:
            raise ThemeError("A child theme cannot be the parent of another theme.")
        name = name.strip()
        slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")[:64]
        if not name or not _SLUG_RE.match(slug):
            raise ThemeError("Enter a name for the child theme.")
        dest = os.path.join(self.themes_dir, slug)
        if os.path.exists(dest):
            raise ThemeError(f"Theme '{slug}' already exists.")
        os.makedirs(os.path.join(dest, "assets"))
        parent_name = parents[parent_slug].name
        with open(os.path.join(dest, "theme.py"), "w", encoding="utf-8") as fh:
            fh.write(
                f'"""Child theme of {parent_name}.\n\n'
                f'Templates placed in this folder override the parent\'s. Anything else\n'
                f'(layout, partials, assets) is inherited.\n"""\n\n'
                f'THEME_NAME        = {name!r}\n'
                f'THEME_PARENT      = {parent_slug!r}\n'
                f'THEME_VERSION     = "1.0.0"\n'
                f'THEME_AUTHOR      = ""\n'
                f'THEME_DESCRIPTION = "Child of {parent_name}."\n\n'
                f'# Register hooks here; the child\'s theme.py runs before the parent\'s.\n'
            )
        return slug

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
