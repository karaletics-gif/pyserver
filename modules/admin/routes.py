"""
modules/admin/routes.py – multi-page /py-admin interface (dashboard, posts, media,
pages, comments, appearance, users, tools, settings).

URLs mirror the WordPress admin layout with py-admin and .py in place of wp-admin and .php.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from core import config
from core.request import Request
from core.response import Response
from cms.content.service import (
    NotFoundError, ValidationError, create_page, delete_post as svc_delete_post,
)
from cms.content.slugs import slugify, unique_slug
from cms.content.models import Post
from cms.content.post_types import format_url, get_post_type, get_post_types
from cms.settings.model import Setting
from cms.users.model import User
from database.orm import QuerySet
from database.py_schema import Comment
from modules.admin.menu import build_bar, build_menu, type_key, type_urls
from modules.auth.permissions import ROLE_HIERARCHY, can, require_capability

ADMIN = "/py-admin"
PER_PAGE = 20
UPLOAD_URL = "/py-content/uploads"
ALLOWED_UPLOADS = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
}
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "admin"
_STATIC_TYPES = {"css": "text/css; charset=utf-8", "js": "application/javascript; charset=utf-8"}


def url(page: str, **params) -> str:
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return f"{ADMIN}/{page}.py" + (f"?{query}" if query else "")


def _now() -> str:
    return datetime.utcnow().isoformat(sep=" ", timespec="seconds")


def register_admin_routes(router, render, flash_redirect, loader) -> None:
    """
    render(template, request, extra) -> str      internal template renderer
    flash_redirect(location, message, kind)      redirect with a flash notice
    loader                                       ThemeLoader (for Appearance)
    """

    def page(request: Request, template: str, section: str, sub: str = "all", **extra) -> Response:
        from blocks.flash import clear_flash

        comment_count = QuerySet(Comment).count()
        ctx = {
            "menu": build_menu(request, section, sub),
            "section": section,
            "comment_count": comment_count,
            "admin_url": ADMIN,
        }
        ctx["bar_left"], ctx["bar_right"] = build_bar(
            request, Setting.get_value("site_name", "PyServer"), comment_count)
        ctx.update(extra)
        response = Response.html(render(f"admin/{template}", request, ctx))
        clear_flash(response)
        return response

    # ── Static assets ────────────────────────────────────────────────────────

    @router.get(f"{ADMIN}/assets/<filename>")
    def admin_asset(request: Request, filename: str) -> Response:
        path = STATIC_DIR / Path(filename).name
        mime = _STATIC_TYPES.get(path.suffix.lstrip(".").lower())
        if not mime or not path.is_file():
            return Response.not_found()
        return Response(body=path.read_text(encoding="utf-8"), content_type=mime)

    # ── Dashboard ────────────────────────────────────────────────────────────

    @router.get(ADMIN)
    @require_capability("manage_users")
    def admin_root(request: Request) -> Response:
        return dashboard(request)

    @router.get(url("index"))
    @require_capability("manage_users")
    def dashboard(request: Request) -> Response:
        posts = QuerySet(Post).filter(content_type="post").order_by("-created_at").all()
        return page(
            request, "index.html", "dashboard",
            stats={
                "posts": len(posts),
                "published": sum(1 for p in posts if p.status == "published"),
                "drafts": sum(1 for p in posts if p.status == "draft"),
                "pages": QuerySet(Post).filter(content_type="page").count(),
                "users": QuerySet(User).count(),
                "comments": QuerySet(Comment).count(),
                "media": QuerySet(Post).filter(content_type="attachment").count(),
            },
            recent_posts=posts[:6],
            type_counts=[
                {"label": cfg["label"], "count": QuerySet(Post).filter(content_type=slug).count(),
                 "url": type_urls(slug)[0]}
                for slug, cfg in get_post_types().items() if not cfg["builtin"]
            ],
            recent_comments=QuerySet(Comment).order_by("-created_at").limit(5).all(),
            active_theme=loader.active,
            can_write=can(request.user, "write_post"),
        )

    # ── Posts and pages list ─────────────────────────────────────────────────

    @router.any(url("edit"))
    @require_capability("manage_users")
    def edit_list(request: Request) -> Response:
        types = get_post_types()
        post_type = request.query_string.get("post_type", "post")
        if post_type not in types:
            return Response.not_found()
        config_type = types[post_type]
        if request.method == "POST":
            return _list_action(request, post_type)

        status = request.query_string.get("post_status", "")
        if status not in ("published", "draft"):
            status = ""
        search = request.query_string.get("s", "").strip()
        try:
            paged = max(1, int(request.query_string.get("paged", "1")))
        except ValueError:
            paged = 1

        base = QuerySet(Post).filter(content_type=post_type)
        counts = {
            "": base.count(),
            "published": QuerySet(Post).filter(content_type=post_type, status="published").count(),
            "draft": QuerySet(Post).filter(content_type=post_type, status="draft").count(),
        }
        query = QuerySet(Post).filter(content_type=post_type)
        if status:
            query = query.filter(status=status)
        rows = query.order_by("-created_at").all()
        if search:
            needle = search.lower()
            rows = [p for p in rows if needle in p.title.lower() or needle in (p.body or "").lower()]
        total = len(rows)
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        rows = rows[(paged - 1) * PER_PAGE: paged * PER_PAGE]

        authors = {u.id: u.name for u in QuerySet(User).all()}
        label = config_type["label"]
        type_param = None if post_type == "post" else post_type

        def link(**params):
            return url("edit", post_type=type_param, **params)

        def edit_link(p):
            pattern = config_type["edit_url"]
            return format_url(pattern, p) if pattern else url("post", post=p.id)

        entries = [{
            "post": p,
            "author": authors.get(p.author_id, "Unknown"),
            "edit_url": edit_link(p),
            "view_url": format_url(config_type["view_url"], p) if config_type["public"] else "",
            "date_label": "Published" if p.status == "published" else "Last Modified",
            "date": (p.published_at or p.updated_at or p.created_at or "")[:16],
        } for p in rows]
        return page(
            request, "posts.html", type_key(post_type),
            list_title=label, post_type=post_type, entries=entries, search=search,
            total=total, status_links=[
                {"label": "All", "count": counts[""], "url": link(), "current": status == ""},
                {"label": "Published", "count": counts["published"],
                 "url": link(post_status="published"), "current": status == "published"},
                {"label": "Draft", "count": counts["draft"],
                 "url": link(post_status="draft"), "current": status == "draft"},
            ],
            paged=paged, pages=pages,
            prev_url=link(post_status=status, s=search, paged=paged - 1) if paged > 1 else "",
            next_url=link(post_status=status, s=search, paged=paged + 1) if paged < pages else "",
            new_url=type_urls(post_type)[1],
            new_label=f"Add {config_type['singular']}",
        )

    def _list_action(request: Request, post_type: str) -> Response:
        back = url("edit", post_type=None if post_type == "post" else post_type)
        if request.form.get("action") == "delete" and can(request.user, "delete_post"):
            try:
                svc_delete_post(int(request.form.get("id", "0")))
                return flash_redirect(back, "Item deleted.", "ok")
            except (ValueError, NotFoundError):
                return flash_redirect(back, "Item not found.", "err")
        return Response.redirect(back)

    # ── Generic editor for pages and custom post types (posts use the theme editor) ──

    def _editor(request: Request, post_type: str, item, form, error, sub: str) -> Response:
        config_type = get_post_types()[post_type]
        return page(
            request, "post_edit.html", type_key(post_type), sub, item=item, form=form,
            error=error, can_publish=can(request.user, "publish_post"),
            post_type=post_type, type_singular=config_type["singular"],
            view_url=format_url(config_type["view_url"], item) if item and config_type["public"] else "",
        )

    @router.any(url("post-new"))
    @require_capability("write_post")
    def post_new(request: Request) -> Response:
        post_type = request.query_string.get("post_type", "post")
        config_type = get_post_type(post_type)
        if config_type is None:
            return Response.not_found()
        if config_type["new_url"]:
            return Response.redirect(config_type["new_url"])
        if request.method == "GET":
            return _editor(request, post_type, None, {}, None, "new")
        form = request.form
        title = form.get("title", "").strip()
        if not title:
            return _editor(request, post_type, None, form, "A title is required.", "new")
        publish = form.get("action") == "publish" and can(request.user, "publish_post")
        try:
            if post_type == "page":
                created = create_page(
                    title, form.get("body", "").strip(), request.user.id,
                    slug=form.get("slug", "").strip() or None,
                    status="published" if publish else "draft",
                )
            else:
                created = QuerySet(Post).create(
                    title=title, body=form.get("body", "").strip(), excerpt="",
                    slug=unique_slug(form.get("slug", "").strip() or title, table="posts"),
                    content_type=post_type, author_id=request.user.id,
                    status="published" if publish else "draft",
                    published_at=_now() if publish else None,
                )
            return flash_redirect(
                url("post", post=created.id), f"{config_type['singular']} saved.", "ok")
        except (ValidationError, ValueError) as exc:
            return _editor(request, post_type, None, form, str(exc), "new")

    @router.any(url("post"))
    @require_capability("write_post")
    def post_edit(request: Request) -> Response:
        types = get_post_types()
        try:
            item = QuerySet(Post).get(id=int(request.query_string.get("post", "0")))
        except (ValueError, Post.DoesNotExist):
            return Response.not_found()
        post_type = item.content_type
        if post_type not in types:
            return Response.not_found()
        if types[post_type]["edit_url"]:
            return Response.redirect(format_url(types[post_type]["edit_url"], item))
        if request.method == "GET":
            return _editor(request, post_type, item, {}, None, "all")
        form = request.form
        title = form.get("title", "").strip()
        if not title:
            return _editor(request, post_type, item, form, "A title is required.", "all")
        item.title = title
        item.body = form.get("body", "").strip()
        item.slug = unique_slug(form.get("slug", "").strip() or title, table="posts", exclude_id=item.id)
        action = form.get("action")
        if can(request.user, "publish_post"):
            if action == "publish":
                item.status = "published"
                item.published_at = item.published_at or _now()
            elif action == "unpublish":
                item.status = "draft"
        item.save()
        return flash_redirect(url("post", post=item.id), f"{types[post_type]['singular']} updated.", "ok")

    # ── Media library ────────────────────────────────────────────────────────

    @router.any(url("upload"))
    @require_capability("manage_users")
    def media_library(request: Request) -> Response:
        if request.method == "POST":
            if request.form.get("action") == "delete":
                _delete_media(request.form.get("id", ""))
                return flash_redirect(url("upload"), "Media file deleted.", "ok")
            return Response.redirect(url("upload"))
        search = request.query_string.get("s", "").strip().lower()
        items = QuerySet(Post).filter(content_type="attachment").order_by("-created_at").all()
        if search:
            items = [m for m in items if search in m.title.lower()]
        return page(request, "upload.html", "media", media=items, search=search, upload_url=UPLOAD_URL)

    @router.any(url("media-new"))
    @require_capability("manage_users")
    def media_new(request: Request) -> Response:
        if request.method == "GET":
            return page(request, "media_new.html", "media", "new", error=None,
                        max_mb=config.MAX_UPLOAD_MB,
                        allowed=", ".join(sorted(ALLOWED_UPLOADS)))
        try:
            _save_upload(request)
            return flash_redirect(url("upload"), "File uploaded.", "ok")
        except ValueError as exc:
            return page(request, "media_new.html", "media", "new", error=str(exc),
                        max_mb=config.MAX_UPLOAD_MB,
                        allowed=", ".join(sorted(ALLOWED_UPLOADS)))

    def _save_upload(request: Request) -> None:
        upload = request.files.get("file")
        if not upload or not upload[0]:
            raise ValueError("Choose a file to upload.")
        filename, _declared, data = upload
        extension = Path(filename).suffix.lstrip(".").lower()
        if extension not in ALLOWED_UPLOADS:
            raise ValueError("That file type is not allowed.")
        if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
            raise ValueError(f"The file is larger than {config.MAX_UPLOAD_MB} MB.")
        stem = slugify(Path(filename).stem)
        stored = f"{stem}-{secrets.token_hex(4)}.{extension}"
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (config.UPLOAD_DIR / stored).write_bytes(data)
        QuerySet(Post).create(
            title=Path(filename).stem, slug=unique_slug(stem, table="posts"), body="",
            excerpt="", content_type="attachment", author_id=request.user.id,
            status="inherit", post_mime_type=ALLOWED_UPLOADS[extension].split(";")[0],
            guid=f"{UPLOAD_URL}/{stored}",
        )

    def _delete_media(raw_id: str) -> None:
        try:
            item = QuerySet(Post).filter(content_type="attachment").get(id=int(raw_id))
        except (ValueError, Post.DoesNotExist):
            return
        stored = Path(item.guid).name
        target = config.UPLOAD_DIR / stored
        if target.is_file() and target.parent == config.UPLOAD_DIR:
            target.unlink()
        item.delete()

    @router.get(f"{UPLOAD_URL}/<filename>")
    def serve_upload(request: Request, filename: str) -> Response:
        name = Path(filename).name
        mime = ALLOWED_UPLOADS.get(Path(name).suffix.lstrip(".").lower())
        target = config.UPLOAD_DIR / name
        if name != filename or not mime or not target.is_file():
            return Response.not_found()
        data = target.read_bytes()
        response = Response(status=200, content_type=mime)
        response._raw_bytes = data
        response.set_header("X-Content-Type-Options", "nosniff")
        response.set_header("Cache-Control", "public, max-age=3600")
        return response

    # ── Comments ─────────────────────────────────────────────────────────────

    @router.get(url("edit-comments"))
    @require_capability("manage_users")
    def comments_list(request: Request) -> Response:
        titles = {p.id: p.title for p in QuerySet(Post).all()}
        comments = QuerySet(Comment).order_by("-created_at").limit(100).all()
        return page(request, "comments.html", "comments", comments=comments, titles=titles)

    # ── Appearance ───────────────────────────────────────────────────────────

    @router.get(url("themes"))
    @require_capability("manage_settings")
    def themes_page(request: Request) -> Response:
        return page(request, "themes.html", "appearance", themes=loader.available(),
                    active_theme=loader.active)

    # ── Users ────────────────────────────────────────────────────────────────

    @router.get(url("users"))
    @require_capability("manage_users")
    def users_list(request: Request) -> Response:
        role = request.query_string.get("role", "")
        everyone = QuerySet(User).order_by("created_at").all()
        users = [u for u in everyone if not role or u.role == role]
        links = [{"label": "All", "count": len(everyone), "url": url("users"), "current": not role}]
        for name in ROLE_HIERARCHY:
            links.append({
                "label": name.title(), "count": sum(1 for u in everyone if u.role == name),
                "url": url("users", role=name), "current": role == name,
            })
        return page(request, "users.html", "users", users=users, role_links=links,
                    role_options=ROLE_HIERARCHY)

    # ── Tools and settings ───────────────────────────────────────────────────

    @router.get(url("tools"))
    @require_capability("manage_users")
    def tools_page(request: Request) -> Response:
        return page(request, "tools.html", "tools", upload_dir=str(config.UPLOAD_DIR))

    @router.get(url("options-general"))
    @require_capability("manage_settings")
    def settings_page(request: Request) -> Response:
        fields = [
            ("site_name", "Site Title", Setting.get_value("site_name", "")),
            ("site_tagline", "Tagline", Setting.get_value("site_tagline", "")),
            ("posts_per_page", "Posts per page", Setting.get_value("posts_per_page", "10")),
        ]
        return page(request, "settings.html", "settings", settings_fields=fields)
