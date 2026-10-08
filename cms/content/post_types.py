"""
cms/content/post_types.py – dynamic post type registry.

Built-in types are "post" and "page". Themes (theme.py) and plugins add or change types
through the global hook registry:

    @hooks.filter("post_types.register")
    def add_event_type(types):
        types["event"] = {"label": "Events", "singular": "Event", "icon": "\u2605"}
        return types

or the shorthand:

    register_post_type("event", label="Events", singular="Event")

Config keys (all optional except label):
  label          plural name, used for menu and list titles
  singular       singular name (defaults to label)
  icon           single character shown in the admin menu
  menu_position  sort order in the admin menu (lower first)
  show_in_menu   False hides it from the admin menu
  public         True serves published items at view_url
  view_url       "/events/{slug}" style pattern; {slug}, {id}, {post_type} are available
  edit_url       pattern for the edit screen (default: the admin editor)
  new_url        URL of the "add new" screen (default: the admin editor)
"""

from __future__ import annotations

from typing import Any

from cookie.hooks import hooks

FILTER = "post_types.register"

_BUILTIN: dict[str, dict[str, Any]] = {
    "post": {
        "label": "Posts", "singular": "Post", "icon": "\u270e", "menu_position": 5,
        "public": True, "view_url": "/posts/{slug}",
        "edit_url": "/posts/{slug}/edit", "new_url": "/posts/new",
    },
    "page": {
        "label": "Pages", "singular": "Page", "icon": "\u2750", "menu_position": 20,
        "public": True, "view_url": "/pages/{slug}",
    },
    "pattern": {
        "label": "Patterns", "singular": "Pattern", "icon": "\u25a6", "menu_position": 99,
        "show_in_menu": False, "public": False, "view_url": "",
    },
}


def _normalise(slug: str, config: dict) -> dict:
    result = {
        "slug": slug, "label": slug.title(), "singular": "", "icon": "\u25cf",
        "menu_position": 25, "show_in_menu": True, "public": True,
        "view_url": "/content/{post_type}/{slug}", "edit_url": "", "new_url": "",
        "builtin": slug in _BUILTIN,
    }
    result.update(config)
    result["singular"] = result["singular"] or result["label"]
    return result


def get_post_types() -> dict[str, dict]:
    """All registered post types after plugin/theme filters have run."""
    registered = hooks.apply_filters(FILTER, {k: dict(v) for k, v in _BUILTIN.items()})
    return {slug: _normalise(slug, cfg) for slug, cfg in registered.items()}


def get_post_type(slug: str) -> dict | None:
    return get_post_types().get(slug)


def register_post_type(slug: str, **config: Any) -> None:
    """Convenience wrapper that adds *slug* via the post_types.register filter."""
    def add(types: dict) -> dict:
        types[slug] = config
        return types
    hooks.add_filter(FILTER, add)


def format_url(pattern: str, post) -> str:
    return pattern.format(slug=post.slug, id=post.id, post_type=post.content_type)
