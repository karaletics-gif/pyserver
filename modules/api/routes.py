"""
modules/api/routes.py – JSON REST API for PyServer.

Endpoints
---------
  GET  /api/posts              list published posts (paginated)
  GET  /api/posts/<slug>       single post
  POST /api/posts              create post          [write_post]
  PUT  /api/posts/<slug>       update post          [write_post]
  DEL  /api/posts/<slug>       delete post          [delete_post]

  GET  /api/settings           public site settings
  GET  /api/health             health check

All endpoints return JSON.  Auth via session cookie (same as browser),
or X-Session-Token header for API clients.

Error shape: {"error": "message", "code": "SNAKE_CASE"}
Success list: {"data": [...], "total": N, "page": P, "per_page": PP}
Success item: {"data": {...}}
"""

from __future__ import annotations

from core.response  import Response
from core.request   import Request
from core.router    import Router

from modules.auth.permissions import can
from change_password.content.service  import (
    list_posts, get_post_by_slug, create_post, update_post,
    delete_post, NotFoundError, ValidationError,
)
from change_password.settings.model   import Setting


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json_err(message: str, code: str = "ERROR", status: int = 400) -> Response:
    return Response.json({"error": message, "code": code}, status=status)


def _require_auth(request) -> Response | None:
    """Return a 401 response if not authenticated, else None."""
    if not request.is_authenticated:
        return _json_err("Authentication required.", "UNAUTHENTICATED", 401)
    return None


def _require_cap(request, capability: str) -> Response | None:
    """Return a 403 response if user lacks capability, else None."""
    if not can(request.user, capability):
        return _json_err(
            f"Requires capability: {capability}", "FORBIDDEN", 403
        )
    return None


def _post_to_dict(post) -> dict:
    return {
        "id":           post.id,
        "title":        post.title,
        "slug":         post.slug,
        "excerpt":      post.display_excerpt,
        "status":       post.status,
        "author_id":    post.author_id,
        "views":        post.views,
        "revision":     post.revision,
        "published_at": post.published_at,
        "created_at":   post.created_at,
        "updated_at":   post.updated_at,
    }


def _post_to_dict_full(post) -> dict:
    d = _post_to_dict(post)
    d.update({
        "body":       post.body,
        "meta_title": post.meta_title,
        "meta_desc":  post.meta_desc,
    })
    return d


# ── Route registration ────────────────────────────────────────────────────────

def register_api_routes(router: Router) -> None:
    """Call once from app.py to mount all /api/* routes."""

    # ── Health ────────────────────────────────────────────────────────────────

    @router.get("/api/health")
    def api_health(request: Request) -> Response:
        from database.orm import get_connection
        try:
            get_connection().execute("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        return Response.json({
            "status":    "ok" if db_ok else "degraded",
            "db":        "ok" if db_ok else "error",
            "theme":     request.headers.get("X-Active-Theme", "unknown"),
        })

    # ── Settings (public) ─────────────────────────────────────────────────────

    @router.get("/api/settings")
    def api_settings(request: Request) -> Response:
        public_keys = ("site_name", "site_tagline", "posts_per_page", "active_theme")
        return Response.json({
            "data": {k: Setting.get_value(k) for k in public_keys}
        })

    # ── Post list ─────────────────────────────────────────────────────────────

    @router.route("/api/posts", methods=["GET", "POST"])
    def api_posts_collection(request: Request) -> Response:
        if request.method == "POST":
            return api_create_post_handler(request)
        return api_list_posts_handler(request)

    def api_list_posts_handler(request: Request) -> Response:
        try:
            page     = max(1, int(request.query_string.get("page", "1")))
            per_page = min(50, max(1, int(request.query_string.get("per_page", "10"))))
        except ValueError:
            return _json_err("Invalid page or per_page parameter.", "INVALID_PARAM")

        # Authenticated users can see their own drafts
        status = "published"
        if request.is_authenticated:
            status_param = request.query_string.get("status", "published")
            if status_param in ("draft", "published", "archived", "all"):
                status = status_param if status_param != "all" else None

        author_id = None
        if request.query_string.get("author_id"):
            try:
                author_id = int(request.query_string["author_id"])
            except ValueError:
                pass

        posts, total = list_posts(
            status=status,
            author_id=author_id,
            page=page,
            per_page=per_page,
        )
        return Response.json({
            "data":     [_post_to_dict(p) for p in posts],
            "total":    total,
            "page":     page,
            "per_page": per_page,
            "pages":    (total + per_page - 1) // per_page,
        })

    # ── Single post ───────────────────────────────────────────────────────────

    @router.route("/api/posts/<slug>", methods=["GET","PUT","PATCH","DELETE"])
    def api_post_resource(request: Request, slug: str) -> Response:
        if request.method in ("PUT","PATCH"):
            return api_update_post_handler(request, slug)
        if request.method == "DELETE":
            return api_delete_post_handler(request, slug)
        return api_get_post_handler(request, slug)

    def api_get_post_handler(request: Request, slug: str) -> Response:
        try:
            post = get_post_by_slug(slug)
        except NotFoundError:
            return _json_err(f"Post '{slug}' not found.", "NOT_FOUND", 404)

        if not post.is_published and not request.is_authenticated:
            return _json_err("Post not found.", "NOT_FOUND", 404)

        return Response.json({"data": _post_to_dict_full(post)})

    # ── Create post ───────────────────────────────────────────────────────────

    def api_create_post_handler(request: Request) -> Response:
        if err := _require_auth(request):     return err
        if err := _require_cap(request, "write_post"): return err

        body = request.json or {}
        title = str(body.get("title", "")).strip()
        text  = str(body.get("body",  "")).strip()

        if not title:
            return _json_err("'title' is required.", "VALIDATION_ERROR")
        if not text:
            return _json_err("'body' is required.",  "VALIDATION_ERROR")

        status = body.get("status", "draft")
        if status == "published" and not can(request.user, "publish_post"):
            status = "draft"

        try:
            post = create_post(
                title      = title,
                body       = text,
                author_id  = request.user.id,
                slug       = body.get("slug") or None,
                excerpt    = body.get("excerpt", ""),
                status     = status,
                meta_title = body.get("meta_title", ""),
                meta_desc  = body.get("meta_desc",  ""),
            )
        except ValidationError as e:
            return _json_err(str(e), "VALIDATION_ERROR")

        return Response.json({"data": _post_to_dict_full(post)}, status=201)

    # ── Update post ───────────────────────────────────────────────────────────

    def api_update_post_handler(request: Request, slug: str) -> Response:
        if err := _require_auth(request):     return err
        if err := _require_cap(request, "write_post"): return err

        try:
            post = get_post_by_slug(slug)
        except NotFoundError:
            return _json_err(f"Post '{slug}' not found.", "NOT_FOUND", 404)

        body = request.json or {}
        new_status = body.get("status")
        if new_status == "published" and not can(request.user, "publish_post"):
            return _json_err("Requires publish_post capability.", "FORBIDDEN", 403)

        try:
            post = update_post(
                post.id,
                changed_by  = request.user.id,
                title       = body.get("title")      or None,
                body        = body.get("body")        or None,
                slug        = body.get("slug")        or None,
                excerpt     = body.get("excerpt"),
                meta_title  = body.get("meta_title"),
                meta_desc   = body.get("meta_desc"),
                status      = new_status,
                change_note = body.get("change_note", "API update"),
            )
        except ValidationError as e:
            return _json_err(str(e), "VALIDATION_ERROR")

        return Response.json({"data": _post_to_dict_full(post)})

    # ── Delete post ───────────────────────────────────────────────────────────

    def api_delete_post_handler(request: Request, slug: str) -> Response:
        if err := _require_auth(request):      return err
        if err := _require_cap(request, "delete_post"): return err

        try:
            post = get_post_by_slug(slug)
            delete_post(post.id)
        except NotFoundError:
            return _json_err(f"Post '{slug}' not found.", "NOT_FOUND", 404)

        return Response.json({"deleted": True, "slug": slug})

    # ── Search ────────────────────────────────────────────────────────────────

    @router.get("/api/search")
    def api_search(request: Request) -> Response:
        q = request.query_string.get("q", "").strip()
        if len(q) < 2:
            return _json_err("Query must be at least 2 characters.", "INVALID_PARAM")

        from database.orm import QuerySet
        from change_password.content.models import Post

        results = (
            QuerySet(Post)
            .filter(content_type="post", status="published")
            .filter(title__like=f"%{q}%")
            .order_by("-published_at")
            .limit(20)
            .all()
        )

        # Also search body (simple, no FTS index)
        body_results = (
            QuerySet(Post)
            .filter(content_type="post", status="published")
            .filter(body__like=f"%{q}%")
            .order_by("-published_at")
            .limit(20)
            .all()
        )

        # Merge and deduplicate by id
        seen = set()
        combined = []
        for p in results + body_results:
            if p.id not in seen:
                seen.add(p.id)
                combined.append(p)

        return Response.json({
            "query":   q,
            "total":   len(combined),
            "data":    [_post_to_dict(p) for p in combined[:20]],
        })
