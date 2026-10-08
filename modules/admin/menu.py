"""
modules/admin/menu.py – admin sidebar menu and top admin bar, extensible through hooks.

Filters (register from theme.py or plugin code with @hooks.filter(name)):

  admin.menu      (items, request)            top-level sidebar items
  admin.submenu   (children, parent_key, request)  sub menu of one sidebar item
  admin.bar       (items, request)            top admin bar items

Example:

    from modules.admin.menu import menu_item, submenu_item, bar_item

    @hooks.filter("admin.menu")
    def reports_menu(items, request):
        items.append(menu_item("reports", "Reports", "/py-admin/reports.py",
                               icon="\u2263", position=65, capability="manage_users",
                               children=[submenu_item("Overview", "/py-admin/reports.py", "all"),
                                         submenu_item("Export", "/py-admin/export.py", "export")]))
        return items

    @hooks.filter("admin.submenu")
    def extra_user_links(children, parent_key, request):
        if parent_key == "users":
            children.append(submenu_item("Invitations", "/py-admin/invites.py", "invites"))
        return children

    @hooks.filter("admin.bar")
    def bar(items, request):
        items.append(bar_item("help", "Help", "/docs", align="right"))
        return items
"""

from __future__ import annotations

from urllib.parse import urlencode

from cookie.hooks import hooks
from cms.content.post_types import get_post_types
from modules.auth.permissions import can

ADMIN = "/py-admin"


def admin_url(page: str, **params) -> str:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return f"{ADMIN}/{page}.py" + (f"?{query}" if query else "")


def submenu_item(label: str, url: str, key: str = "") -> dict:
    return {"key": key or label.lower().replace(" ", "-"), "label": label, "url": url, "active": False}


def menu_item(key: str, label: str, url: str, icon: str = "\u25cf", position: int = 50,
              children: list[dict] | None = None, capability: str | None = None) -> dict:
    return {
        "key": key, "label": label, "url": url, "icon": icon, "position": position,
        "children": list(children or []), "capability": capability, "active": False,
    }


def bar_item(key: str, label: str, url: str = "#", align: str = "left", position: int = 50,
             badge: str | int | None = None, children: list[dict] | None = None) -> dict:
    return {
        "key": key, "label": label, "url": url, "align": align, "position": position,
        "badge": badge, "children": list(children or []),
    }


def type_key(slug: str) -> str:
    """Menu section key for a post type (kept as posts/pages for the built-ins)."""
    return {"post": "posts", "page": "pages", "pattern": "appearance"}.get(slug, slug)


def type_urls(slug: str) -> tuple[str, str]:
    """(list url, new url) for a post type."""
    config = get_post_types()[slug]
    return (
        admin_url("edit", post_type=None if slug == "post" else slug),
        config["new_url"] or admin_url("post-new", post_type=slug),
    )


def _builtin_items() -> list[dict]:
    items = [
        menu_item("dashboard", "Dashboard", admin_url("index"), "\u2302", 2),
        menu_item("media", "Media", admin_url("upload"), "\u25a3", 10, [
            submenu_item("Library", admin_url("upload"), "all"),
            submenu_item("Add Media File", admin_url("media-new"), "new")]),
        menu_item("comments", "Comments", admin_url("edit-comments"), "\u2709", 30),
        menu_item("appearance", "Appearance", admin_url("themes"), "\u2726", 60),
        menu_item("users", "Users", admin_url("users"), "\u263a", 70, [
            submenu_item("All Users", admin_url("users"), "all")]),
        menu_item("tools", "Tools", admin_url("tools"), "\u2692", 80),
        menu_item("settings", "Settings", admin_url("options-general"), "\u2699", 90),
    ]
    for slug, config in get_post_types().items():
        if not config["show_in_menu"]:
            continue
        list_url, new_url = type_urls(slug)
        items.append(menu_item(
            type_key(slug), config["label"], list_url, config["icon"], config["menu_position"],
            [submenu_item(f"All {config['label']}", list_url, "all"),
             submenu_item(f"Add {config['singular']}", new_url, "new")],
        ))
    return items


def _path(url: str) -> str:
    return url.split("?")[0]


def build_menu(request, section: str, sub: str) -> list[dict]:
    items = hooks.apply_filters("admin.menu", _builtin_items(), request)
    visible = []
    for item in sorted(items, key=lambda i: i.get("position", 50)):
        if item.get("capability") and not can(request.user, item["capability"]):
            continue
        item["children"] = hooks.apply_filters("admin.submenu", item.get("children", []), item["key"], request)
        item["active"] = item["key"] == section or _path(item["url"]) == request.path and "?" not in item["url"]
        for child in item["children"]:
            child["active"] = item["active"] and (child.get("key") == sub)
        visible.append(item)
    return visible


def build_bar(request, site_name: str, comment_count: int) -> tuple[list[dict], list[dict]]:
    new_children = []
    for slug, config in get_post_types().items():
        if config["show_in_menu"]:
            new_children.append({"label": config["singular"], "url": type_urls(slug)[1]})
    new_children.append({"label": "Media", "url": admin_url("media-new")})
    items = [
        bar_item("site", site_name, "/", position=10),
        bar_item("comments", "\u2709", admin_url("edit-comments"), position=20, badge=comment_count),
        bar_item("new", "+ New", "#", position=30, children=new_children),
        bar_item("profile", f"Howdy, {request.user.name}", f"{ADMIN}/users/{request.user.id}/edit",
                 align="right", position=90),
    ]
    items = hooks.apply_filters("admin.bar", items, request)
    ordered = sorted(items, key=lambda i: i.get("position", 50))
    return ([i for i in ordered if i.get("align", "left") != "right"],
            [i for i in ordered if i.get("align") == "right"])
