"""
modules/admin/appearance.py – Appearance screens (WordPress-style).

Themes (grid, upload zip, delete, activate), child themes, Patterns, Customize, Widgets,
Fonts, Menus, Header, Background and the Theme File Editor.

Site-wide settings made here are applied to every theme by core filters that survive
theme switches: theme.context (menus, widgets, header vars) and theme.html (CSS and
footer widgets). A theme can declare in theme.py:

  THEME_PARENT       = "default"                       make it a child theme
  THEME_SUPPORTS     = {"menus", "widgets", ...}       hide unsupported Appearance screens
  THEME_WIDGET_AREAS = {"sidebar": "Sidebar"}          widget areas the theme provides
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re

from blocks.theme_loader import SCREENSHOTS, ThemeError
from core import config
from core.request import Request
from core.response import Response
from cms.settings.model import Setting
from modules.admin.menu import admin_url, submenu_item
from modules.auth.permissions import require_capability

FONTS = {
    "": ("Theme default", ""),
    "system": ("System UI", 'system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif'),
    "serif": ("Serif (Georgia)", 'Georgia,"Times New Roman",serif'),
    "sans": ("Sans-serif (Helvetica)", '"Helvetica Neue",Helvetica,Arial,sans-serif'),
    "humanist": ("Humanist (Trebuchet)", '"Trebuchet MS","Lucida Grande",sans-serif'),
    "mono": ("Monospace", 'ui-monospace,Consolas,"Courier New",monospace'),
}
_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_URL_BAD = re.compile(r"""[\s"'()<>\\]""")
EDITABLE = {".html", ".css", ".js", ".py", ".json", ".txt", ".md"}
MAX_EDIT_BYTES = 512 * 1024
MAX_ITEMS = 100

# key -> (label, type, help, choices)
CUSTOMIZER = {
    "customize": ("Customize", "customize", [
        ("site_name", "Site Title", "text", "", None),
        ("site_tagline", "Tagline", "text", "", None),
        ("cz_accent", "Accent colour (links)", "color", "", None),
        ("cz_custom_css", "Additional CSS", "textarea", "Added to every page after the theme styles.", None),
    ]),
    "fonts": ("Fonts", "fonts", [
        ("cz_body_font", "Body font", "select", "", {k: v[0] for k, v in FONTS.items()}),
        ("cz_heading_font", "Heading font", "select", "", {k: v[0] for k, v in FONTS.items()}),
    ]),
    "header": ("Header", "header", [
        ("cz_header_text", "Header text", "text", "Available to themes as header_text.", None),
        ("cz_header_logo", "Logo image URL", "url", "Use a file from the Media Library (for example /py-content/uploads/logo.png).", None),
    ]),
    "background": ("Background", "background", [
        ("cz_bg_color", "Background colour", "color", "", None),
        ("cz_bg_image", "Background image URL", "url", "Use a file from the Media Library.", None),
    ]),
}
_PAGE_FOR = {"customize": "customize", "fonts": "fonts", "header": "header", "background": "background"}


# ── Stored data helpers ──────────────────────────────────────────────────────

def _json_setting(key: str, default):
    try:
        value = json.loads(Setting.get_value(key, "") or "")
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def clean_url(value: str) -> str | None:
    value = value.strip()
    if not value:
        return ""
    if _URL_BAD.search(value) or not (value.startswith("/") or value.startswith(("http://", "https://"))):
        return None
    return value


def _indexed(form: dict, prefix: str, fields: tuple[str, ...]) -> list[dict]:
    rows = []
    for i in range(MAX_ITEMS):
        row = {f: form.get(f"{prefix}{i}_{f}", "") for f in fields}
        if any(form.get(f"{prefix}{i}_{f}") is not None for f in fields):
            rows.append(row)
    return rows


# ── Core filters applied to every theme ──────────────────────────────────────

def customizer_css() -> str:
    rules = []
    accent = Setting.get_value("cz_accent", "")
    if _COLOR.match(accent or ""):
        rules.append(f":root{{--accent:{accent}}}a{{color:{accent}}}")
    body_font = FONTS.get(Setting.get_value("cz_body_font", "") or "", FONTS[""])[1]
    if body_font:
        rules.append(f"body{{font-family:{body_font}}}")
    heading_font = FONTS.get(Setting.get_value("cz_heading_font", "") or "", FONTS[""])[1]
    if heading_font:
        rules.append(f"h1,h2,h3,h4,h5,h6{{font-family:{heading_font}}}")
    bg_color = Setting.get_value("cz_bg_color", "")
    if _COLOR.match(bg_color or ""):
        rules.append(f"body{{background-color:{bg_color}}}")
    bg_image = Setting.get_value("cz_bg_image", "")
    if bg_image and clean_url(bg_image):
        rules.append(f"body{{background-image:url('{bg_image}');background-size:cover;background-attachment:fixed}}")
    custom = (Setting.get_value("cz_custom_css", "") or "").replace("</", "<\\/")
    if custom.strip():
        rules.append(custom)
    return "\n".join(rules)


def _widget_html(area: str, widgets: list[dict]) -> str:
    parts = []
    for w in widgets:
        title = f"<h3>{html_lib.escape(w.get('title', ''))}</h3>" if w.get("title") else ""
        content = w.get("content", "")
        body = content if w.get("type") == "html" else html_lib.escape(content).replace("\n", "<br>")
        parts.append(f'<div class="py-widget">{title}{body}</div>')
    if not parts:
        return ""
    return f'<aside class="py-widgets py-widgets-{area}" data-py-widget-area="{area}">{"".join(parts)}</aside>'


def _context_filter(ctx: dict) -> dict:
    menus = _json_setting("nav_menus", {})
    for location, key in (("primary", "nav_links"), ("footer", "footer_links")):
        items = [(m["label"], m["url"]) for m in menus.get(location, []) if m.get("label") and m.get("url")]
        if items:
            existing = ctx.get(key)
            triple = bool(existing) and len(existing[0]) == 3
            ctx[key] = [(label, url, "always") for label, url in items] if triple else items
    ctx["menus"] = menus
    stored = _json_setting("widgets", {})
    ctx["widgets"] = {area: _widget_html(area, stored.get(area, [])) for area in stored}
    ctx["header_text"] = Setting.get_value("cz_header_text", "") or ""
    ctx["header_logo"] = Setting.get_value("cz_header_logo", "") or ""
    return ctx


def _html_filter(output: str) -> str:
    css = customizer_css()
    if css:
        tag = f'<style id="py-customizer">{css}</style>'
        lowered = output.lower()
        head_end = lowered.find("</head>")
        output = output[:head_end] + tag + output[head_end:] if head_end != -1 else tag + output
    footer = _widget_html("footer", _json_setting("widgets", {}).get("footer", []))
    if footer and 'data-py-widget-area="footer"' not in output:
        body_end = output.lower().rfind("</body>")
        output = output[:body_end] + footer + output[body_end:] if body_end != -1 else output + footer
    return output


# ── Routes ───────────────────────────────────────────────────────────────────

def register_appearance_routes(router, page, flash_redirect, loader) -> None:
    from cookie.hooks import hooks

    loader.add_core_filter("theme.context", _context_filter, priority=99)
    loader.add_core_filter("theme.html", _html_filter, priority=99)

    def supported(feature: str) -> bool:
        try:
            return loader.active.supports_feature(feature)
        except ThemeError:
            return True

    @hooks.filter("admin.submenu")
    def appearance_submenu(children, parent_key, request):
        if parent_key != "appearance":
            return children
        entries = [("themes", "Themes", admin_url("themes"), None),
                   ("patterns", "Patterns", admin_url("edit", post_type="pattern"), None),
                   ("customize", "Customize", admin_url("customize"), "customize"),
                   ("widgets", "Widgets", admin_url("widgets"), "widgets"),
                   ("fonts", "Fonts", admin_url("fonts"), "fonts"),
                   ("menus", "Menus", admin_url("nav-menus"), "menus"),
                   ("header", "Header", admin_url("header"), "header"),
                   ("background", "Background", admin_url("background"), "background")]
        if not config.DISALLOW_FILE_EDIT:
            entries.append(("editor", "Theme File Editor", admin_url("theme-editor"), None))
        return children + [submenu_item(label, link, key) for key, label, link, feature in entries
                           if feature is None or supported(feature)]

    # ── Themes grid ──────────────────────────────────────────────────────────

    def _cards(search: str) -> list[dict]:
        themes = loader.available()
        installed = {t.slug: t for t in themes}
        active = loader.active
        cards = []
        for t in themes:
            if search and search not in t.name.lower() and search not in t.description.lower():
                continue
            parent = installed.get(t.parent_slug)
            cards.append({
                "slug": t.slug, "name": t.name, "version": t.version, "author": t.author,
                "description": t.description, "screenshot": t.screenshot_url,
                "is_active": t.slug == active.slug,
                "parent_name": (parent.name if parent else t.parent_slug) if t.is_child else "",
                "missing_parent": t.is_child and parent is None,
                "deletable": t.slug not in (active.slug, active.parent_slug),
            })
        cards.sort(key=lambda c: (not c["is_active"], c["name"].lower()))
        return cards

    @router.any(admin_url("themes"))
    @require_capability("manage_settings")
    def themes_page(request: Request) -> Response:
        if request.method == "POST":
            if request.form.get("action") == "delete":
                try:
                    loader.delete_theme(request.form.get("slug", ""))
                    return flash_redirect(admin_url("themes"), "Theme deleted.", "ok")
                except (ThemeError, OSError) as exc:
                    return flash_redirect(admin_url("themes"), str(exc), "err")
            return Response.redirect(admin_url("themes"))
        search = request.query_string.get("s", "").strip().lower()
        cards = _cards(search)
        return page(request, "themes.html", "appearance", "themes", cards=cards,
                    search=search, total=len(cards), active_theme=loader.active)

    # ── Install (zip upload) and child theme scaffold ────────────────────────

    def _install_page(request, error=None, form=None):
        return page(request, "theme_install.html", "appearance", "themes", error=error,
                    form=form or {}, parents=[t for t in loader.available() if not t.is_child],
                    max_mb=config.MAX_THEME_ZIP_MB)

    def _activate(slug: str) -> str | None:
        try:
            loader.switch(slug)
            Setting.set_value("active_theme", slug)
            return None
        except ThemeError as exc:
            return str(exc).splitlines()[0]

    @router.any(admin_url("theme-install"))
    @require_capability("manage_settings")
    def theme_install(request: Request) -> Response:
        if request.method == "GET":
            return _install_page(request)
        form = request.form
        try:
            if form.get("action") == "child":
                slug = loader.create_child_theme(form.get("parent", ""), form.get("name", ""))
                done = "Child theme created"
            else:
                upload = request.files.get("file")
                if not upload or not upload[0]:
                    raise ThemeError("Choose a .zip file to upload.")
                if not upload[0].lower().endswith(".zip"):
                    raise ThemeError("Only .zip files can be uploaded.")
                if len(upload[2]) > config.MAX_THEME_ZIP_MB * 1024 * 1024:
                    raise ThemeError(f"The file is larger than {config.MAX_THEME_ZIP_MB} MB.")
                stem = os.path.splitext(os.path.basename(upload[0]))[0]
                slug = loader.install_zip(upload[2], fallback_name=stem)
                done = "Theme installed"
        except (ThemeError, OSError) as exc:
            return _install_page(request, error=str(exc), form=form)
        if form.get("activate") == "1":
            problem = _activate(slug)
            if problem:
                return flash_redirect(admin_url("themes"), f"{done}, but it could not be activated: {problem}", "err")
            return flash_redirect(admin_url("themes"), f"{done} and activated. Other themes are now inactive.", "ok")
        return flash_redirect(admin_url("themes"), f"{done}.", "ok")

    # ── Customize / Fonts / Header / Background ──────────────────────────────

    def _customizer(slug: str):
        title, feature, fields = CUSTOMIZER[slug]

        @router.any(admin_url(slug))
        @require_capability("manage_settings")
        def handler(request: Request) -> Response:
            if not supported(feature):
                return flash_redirect(admin_url("themes"), f"The active theme does not support {title}.", "err")
            error = None
            if request.method == "POST":
                values = {}
                for key, _label, kind, _help, choices in fields:
                    raw = request.form.get(key, "")
                    if kind == "color":
                        raw = raw.strip()
                        if raw and not _COLOR.match(raw):
                            error = f"{_label}: use a hex colour such as #3858e9."
                    elif kind == "url":
                        cleaned = clean_url(raw)
                        if cleaned is None:
                            error = f"{_label}: enter a path starting with / or an http(s) address."
                        raw = cleaned or ""
                    elif kind == "select" and raw not in choices:
                        error = f"{_label}: choose one of the listed options."
                    elif kind == "textarea":
                        raw = raw[:20000]
                    else:
                        raw = raw.strip()[:200]
                    values[key] = raw
                if not error:
                    for key, value in values.items():
                        Setting.set_value(key, value)
                    return flash_redirect(admin_url(slug), f"{title} saved.", "ok")
            current = [{
                "key": key, "label": label, "type": kind, "help": help_text,
                "choices": list((choices or {}).items()),
                "value": (request.form.get(key) if error else Setting.get_value(key, "")) or "",
            } for key, label, kind, help_text, choices in fields]
            return page(request, "customize.html", "appearance", slug, title=title,
                        fields=current, error=error, action=admin_url(slug))
        return handler

    for _slug in CUSTOMIZER:
        _customizer(_slug)

    # ── Menus ────────────────────────────────────────────────────────────────

    @router.any(admin_url("nav-menus"))
    @require_capability("manage_settings")
    def menus_page(request: Request) -> Response:
        if not supported("menus"):
            return flash_redirect(admin_url("themes"), "The active theme does not support menus.", "err")
        if request.method == "POST":
            menus = {}
            for location in ("primary", "footer"):
                rows = _indexed(request.form, f"m_{location}_", ("label", "url"))
                items = []
                for row in rows:
                    label, url = row["label"].strip()[:100], clean_url(row["url"])
                    if not label and not row["url"].strip():
                        continue
                    if not label or not url:
                        return flash_redirect(admin_url("nav-menus"),
                                              "Each menu item needs a label and a valid URL (/path or http(s)://).", "err")
                    items.append({"label": label, "url": url})
                menus[location] = items
            Setting.set_value("nav_menus", json.dumps(menus))
            return flash_redirect(admin_url("nav-menus"), "Menus saved.", "ok")
        stored = _json_setting("nav_menus", {})
        return page(request, "menus.html", "appearance", "menus",
                    locations=[("primary", "Primary menu", stored.get("primary", [])),
                               ("footer", "Footer menu", stored.get("footer", []))])

    # ── Widgets ──────────────────────────────────────────────────────────────

    @router.any(admin_url("widgets"))
    @require_capability("manage_settings")
    def widgets_page(request: Request) -> Response:
        if not supported("widgets"):
            return flash_redirect(admin_url("themes"), "The active theme does not support widgets.", "err")
        areas = loader.active.widget_areas
        if request.method == "POST":
            data = {}
            for area in areas:
                rows = _indexed(request.form, f"w_{area}_", ("title", "type", "content"))
                data[area] = [
                    {"title": r["title"].strip()[:100],
                     "type": "html" if r["type"] == "html" else "text",
                     "content": r["content"][:10000]}
                    for r in rows if r["title"].strip() or r["content"].strip()
                ]
            Setting.set_value("widgets", json.dumps(data))
            return flash_redirect(admin_url("widgets"), "Widgets saved.", "ok")
        stored = _json_setting("widgets", {})
        return page(request, "widgets.html", "appearance", "widgets",
                    areas=[(slug, label, stored.get(slug, [])) for slug, label in areas.items()])

    # ── Theme File Editor ────────────────────────────────────────────────────

    def _theme_files(theme_dir: str) -> list[str]:
        found = []
        for root, dirs, files in os.walk(theme_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            if os.path.relpath(root, theme_dir).count(os.sep) >= 4:
                dirs[:] = []
            for name in files:
                if os.path.splitext(name)[1].lower() in EDITABLE:
                    found.append(os.path.relpath(os.path.join(root, name), theme_dir).replace(os.sep, "/"))
        return sorted(found)

    @router.any(admin_url("theme-editor"))
    @require_capability("manage_settings")
    def theme_editor(request: Request) -> Response:
        if config.DISALLOW_FILE_EDIT:
            return Response.html("<h1>403 - File editing is disabled (DISALLOW_FILE_EDIT).</h1>", status=403)
        installed = {t.slug: t for t in loader.available()}
        source = request.form if request.method == "POST" else request.query_string
        slug = source.get("theme") or loader.active.slug
        if slug not in installed:
            return Response.not_found()
        theme_dir = installed[slug].path
        files = _theme_files(theme_dir)
        filename = source.get("file") or ("theme.py" if "theme.py" in files else (files[0] if files else ""))
        target = os.path.abspath(os.path.join(theme_dir, filename)) if filename else ""
        if filename and (filename not in files or not target.startswith(os.path.abspath(theme_dir) + os.sep)):
            return Response.not_found()

        error = None
        content = ""
        if filename:
            with open(target, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        if request.method == "POST" and filename:
            content = request.form.get("content", "").replace("\r\n", "\n")
            if len(content.encode("utf-8")) > MAX_EDIT_BYTES:
                error = "The file is too large to save."
            elif filename.endswith(".py"):
                try:
                    compile(content, filename, "exec")
                except SyntaxError as exc:
                    error = f"Python syntax error on line {exc.lineno}: {exc.msg}"
            if not error:
                with open(target, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(content)
                active = loader.active
                if slug in (active.slug, active.parent_slug):
                    problem = _activate(active.slug)
                    if problem:
                        return flash_redirect(admin_url("theme-editor", theme=slug, file=filename),
                                              f"File saved, but the theme failed to reload: {problem}", "err")
                return flash_redirect(admin_url("theme-editor", theme=slug, file=filename), "File edited successfully.", "ok")
        return page(request, "theme_editor.html", "appearance", "editor",
                    themes=list(installed.values()), slug=slug, files=files, filename=filename,
                    content=content, error=error,
                    file_urls={f: admin_url("theme-editor", theme=slug, file=f) for f in files},
                    is_active=slug == loader.active.slug)
