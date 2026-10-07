"""
app.py – PyServer: full pure-Python web application.

Start:  python app.py
        LOG_LEVEL=DEBUG python app.py
        DB_PATH=prod.db  python app.py
"""

import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

_CONFIG_PATH = os.environ.get(
    "PYSERVER_CONFIG",
    os.path.join(os.path.dirname(__file__), "instance", "pyserver.json"),
)
if __name__ == "__main__" and not os.environ.get("DB_PATH") and not os.path.isfile(_CONFIG_PATH):
    from core.server import Server
    from database.installer import InstallerRouter

    Server(InstallerRouter(), host=os.environ.get("HOST", "127.0.0.1"), port=8080).serve()
    raise SystemExit(0)

# ── Bootstrap DB ──────────────────────────────────────────────────────────────
from database.init_db import init_db

DB_PATH = os.environ.get("DB_PATH")
if DB_PATH:
    init_db(DB_PATH, seed=True)
else:
    from database.installer import load_config
    _database_config = load_config()
    if _database_config is None:
        raise RuntimeError("Database is not configured. Run app.py to open the installer.")
    init_db(_database_config, seed=False)

# ── Core ──────────────────────────────────────────────────────────────────────
from core.router        import Router
from core.server        import Server
from core.request       import Request
from core.response      import Response
from cookie.hooks         import HookRegistry
from blocks.theme_loader  import ThemeLoader, ThemeError
from cookie.template_engine import TemplateEngine
from blocks.flash         import set_flash, inject_flash, clear_flash
from blocks.csrf          import csrf_token_for, validate_csrf, CSRFError
from blocks.logger        import get_logger

log = get_logger("app")

# ── Auth ──────────────────────────────────────────────────────────────────────
from change_password.middleware  import AuthMiddleware
from modules.auth.sessions    import sessions
from modules.auth.permissions import require_login, require_capability, can, ROLE_HIERARCHY
from modules.auth.service     import (
    register as auth_register,
    login    as auth_login,
    logout   as auth_logout,
    change_password, update_role,
    AuthError, RegistrationError,
)

# ── Models ────────────────────────────────────────────────────────────────────
from change_password.users.model     import User
from change_password.settings.model  import Setting
from change_password.content.models  import Post
from change_password.content.service import (
    list_posts, get_post_by_slug, get_page_by_slug,
    get_revisions, create_post, update_post,
    delete_post as svc_delete_post,
    restore_revision, NotFoundError, ValidationError,
)
from database.orm import QuerySet

# ── Theme system ──────────────────────────────────────────────────────────────
THEMES_DIR = os.path.join(os.path.dirname(__file__), "themes")
hooks      = HookRegistry()
loader     = ThemeLoader(THEMES_DIR, hooks=hooks)

_active_slug = Setting.get_value("active_theme", "default")
try:    loader.activate(_active_slug)
except ThemeError: loader.activate("default")

# Admin/auth pages use internal templates (not themed)
_admin_tpl = TemplateEngine(
    base_dir=os.path.join(os.path.dirname(__file__), "templates")
)

# ── Shared context helpers ────────────────────────────────────────────────────

def _base_ctx(request: Request) -> dict:
    ctx = {
        "site_name":    Setting.get_value("site_name", "PyServer"),
        "site_tagline": Setting.get_value("site_tagline", "Built with pure Python"),
        "current_user": request.user,
        "error":        None,
        "flash_ok":     None,
        "flash_err":    None,
        "flash_info":   None,
        "footer_links": [("Home","/"), ("Dashboard","/dashboard"), ("Admin","/py-admin")],
        "csrf_token":   csrf_token_for(request),
        "posts":        [],
        "post":         None,
        "page":         None,
        "query":        "",
        "results":      [],
        "page_title":   None,
        "page_message": None,
        "current_page": 1,
        "total_pages": None,
        "prev_page": None,
        "next_page": None,
    }
    inject_flash(request, ctx)
    return ctx

def theme_render(template: str, request: Request, extra: dict = None) -> str:
    ctx = _base_ctx(request)
    if extra: ctx.update(extra)
    return loader.render(template, ctx)

def admin_render(template: str, request: Request, extra: dict = None) -> str:
    ctx = _base_ctx(request)
    if extra: ctx.update(extra)
    return _admin_tpl.render_file(template, ctx)

def _redirect_with_flash(location: str, message: str, kind: str = "ok") -> Response:
    resp = Response.redirect(location)
    set_flash(resp, message, kind)
    return resp

# ── Router ────────────────────────────────────────────────────────────────────
router = Router()

# ── Theme assets ─────────────────────────────────────────────────────────────
_MIME = {"css":"text/css","js":"application/javascript","svg":"image/svg+xml",
         "png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg",
         "ico":"image/x-icon","woff2":"font/woff2","woff":"font/woff"}

@router.get("/themes/<slug>/assets/<filename>")
def theme_asset(request: Request, slug: str, filename: str) -> Response:
    data = loader.serve_asset(slug, filename)
    if data is None: return Response.not_found()
    ext  = filename.rsplit(".", 1)[-1].lower()
    mime = _MIME.get(ext, "application/octet-stream")
    resp = Response(status=200, content_type=mime)
    if mime.startswith("text") or mime == "image/svg+xml":
        resp.body = data.decode("utf-8", errors="replace")
    else:
        resp._raw_bytes = data
    return resp

# Patch encode for binary assets
_orig_encode = Response.encode
def _encode_with_raw(self):
    if hasattr(self, "_raw_bytes"):
        reason  = self.STATUS_MESSAGES.get(self.status, "Unknown")
        headers = {"Content-Type": self.content_type,
                   "Content-Length": str(len(self._raw_bytes)), **self.headers}
        return self.status, reason, headers, self._raw_bytes
    return _orig_encode(self)
Response.encode = _encode_with_raw

# ── Public themed routes ──────────────────────────────────────────────────────

@router.get("/")
def home(request: Request) -> Response:
    posts, total = list_posts(status="published", per_page=6)
    html = theme_render("index", request, {
        "posts": posts, "total_posts": total,
        "current_page": 1, "per_page": 6, "total_pages": None,
        "prev_page": None, "next_page": None,
    })
    resp = Response.html(html)
    clear_flash(resp)
    return resp

@router.get("/posts")
def post_list(request: Request) -> Response:
    page     = max(1, int(request.query_string.get("page", "1")))
    per_page = int(Setting.get_value("posts_per_page", "10"))
    posts, total = list_posts(status="published", page=page, per_page=per_page)
    pages = (total + per_page - 1) // per_page
    html  = theme_render("index", request, {
        "posts": posts, "total_posts": total,
        "current_page": page, "per_page": per_page, "total_pages": pages,
        "show_hero": False,
        "prev_page": page - 1 if page > 1 else None,
        "next_page": page + 1 if page < pages else None,
    })
    return Response.html(html)

@router.get("/search")
def search(request: Request) -> Response:
    q = request.query_string.get("q", "").strip()
    results, total = [], 0
    if len(q) >= 2:
        title_matches = (QuerySet(Post)
                         .filter(content_type="post", status="published")
                         .filter(title__like=f"%{q}%")
                         .order_by("-created_at").limit(20).all())
        body_matches  = (QuerySet(Post)
                         .filter(content_type="post", status="published")
                         .filter(body__like=f"%{q}%")
                         .order_by("-created_at").limit(20).all())
        seen = set()
        for p in title_matches + body_matches:
            if p.id not in seen:
                seen.add(p.id); results.append(p)
        total = len(results)
        results = results[:20]
    html = theme_render("search", request, {"query": q, "results": results, "total": total})
    return Response.html(html)

# ── Post editor routes (before parametric slug!) ──────────────────────────────

def _editor_ctx(request, post=None, editing=False, error=None,
                flash_ok=None, form_title="", form_body=""):
    revisions = get_revisions(post.id) if (editing and post and post.id) else []
    return {
        "post": post, "editing": editing, "revisions": revisions,
        "can_publish": can(request.user, "publish_post"),
        "can_delete":  can(request.user, "delete_post"),
        "error": error, "flash_ok": flash_ok,
        "form_title": form_title, "form_body": form_body,
    }

@router.any("/posts/new")
@require_capability("write_post")
def new_post(request: Request) -> Response:
    if request.method == "GET":
        return Response.html(theme_render("editor", request, _editor_ctx(request)))
    action = request.form.get("action", "save")
    title  = request.form.get("title", "").strip()
    body   = request.form.get("body",  "").strip()
    try:
        status = "published" if action == "publish" and can(request.user,"publish_post") else "draft"
        post   = create_post(
            title=title, body=body, author_id=request.user.id,
            slug       = request.form.get("slug","").strip() or None,
            excerpt    = request.form.get("excerpt","").strip(),
            status     = status,
            meta_title = request.form.get("meta_title","").strip(),
            meta_desc  = request.form.get("meta_desc","").strip(),
        )
        return _redirect_with_flash(f"/posts/{post.slug}/edit", "Post saved.")
    except Exception as e:
        ctx = _editor_ctx(request, error=str(e), form_title=title, form_body=body)
        return Response.html(theme_render("editor", request, ctx))

@router.any("/posts/<slug>/edit")
@require_capability("write_post")
def edit_post(request: Request, slug: str) -> Response:
    try:
        post = get_post_by_slug(slug)
    except NotFoundError:
        return Response.html(loader.render_404({"current_user": request.user}), status=404)

    if request.method == "GET":
        flash = get_revisions(post.id)   # just to check
        ctx   = _editor_ctx(request, post=post, editing=True)
        # Read flash from cookie
        from blocks.flash import get_flash as _gf
        f = _gf(request)
        if f and f["kind"] == "ok": ctx["flash_ok"] = f["message"]
        resp = Response.html(theme_render("editor", request, ctx))
        clear_flash(resp)
        return resp

    action = request.form.get("action", "save")
    new_status = None
    if action == "publish"   and can(request.user,"publish_post"):  new_status = "published"
    elif action == "unpublish" and can(request.user,"publish_post"): new_status = "draft"
    try:
        post = update_post(
            post.id, changed_by=request.user.id,
            title      = request.form.get("title","").strip() or None,
            body       = request.form.get("body", "").strip() or None,
            slug       = request.form.get("slug", "").strip() or None,
            excerpt    = request.form.get("excerpt","").strip(),
            meta_title = request.form.get("meta_title","").strip(),
            meta_desc  = request.form.get("meta_desc","").strip(),
            status     = new_status,
            change_note= f"Edited ({action})",
        )
        return _redirect_with_flash(f"/posts/{post.slug}/edit", "Post saved.")
    except Exception as e:
        ctx = _editor_ctx(request, post=post, editing=True, error=str(e))
        return Response.html(theme_render("editor", request, ctx))

@router.post("/posts/<slug>/delete")
@require_capability("delete_post")
def delete_post_route(request: Request, slug: str) -> Response:
    try:
        post = get_post_by_slug(slug)
        svc_delete_post(post.id)
    except NotFoundError:
        pass
    return _redirect_with_flash("/dashboard", "Post deleted.")

@router.post("/posts/<slug>/restore")
@require_capability("write_post")
def restore_revision_route(request: Request, slug: str) -> Response:
    try:
        post     = get_post_by_slug(slug)
        rev_no   = int(request.form.get("revision", 0))
        restored = restore_revision(post.id, rev_no, restored_by=request.user.id)
        return _redirect_with_flash(f"/posts/{restored.slug}/edit", f"Restored to revision {rev_no}.")
    except Exception:
        return Response.redirect(f"/posts/{slug}/edit")

# ── Post / page view (must come after specific routes) ───────────────────────

@router.get("/posts/<slug>")
def single_post(request: Request, slug: str) -> Response:
    try:
        post = get_post_by_slug(slug)
        if not post.is_published and not request.is_authenticated:
            return Response.redirect("/login")
        post.increment_views()
        html = theme_render("single", request, {"post": post})
        return Response.html(html)
    except NotFoundError:
        html = loader.render_404({"current_user": request.user})
        return Response.html(html, status=404)

@router.get("/pages/<slug>")
def cms_page(request: Request, slug: str) -> Response:
    try:
        page = get_page_by_slug(slug)
        html = theme_render("page", request, {"page": page})
        return Response.html(html)
    except NotFoundError:
        html = loader.render_404({"current_user": request.user})
        return Response.html(html, status=404)

# ── Auth ──────────────────────────────────────────────────────────────────────

@router.any("/login")
def login_page(request: Request) -> Response:
    if request.user: return Response.redirect("/dashboard")
    if request.method == "GET":
        return Response.html(admin_render("login.html", request, {"prefill_email": ""}))
    email = request.form.get("email", "")
    try:
        user, token = auth_login(email, request.form.get("password",""))
    except AuthError as e:
        return Response.html(admin_render("login.html", request,
                                          {"error": str(e), "prefill_email": email}))
    resp = Response.redirect("/dashboard")
    resp.set_cookie(sessions.make_cookie(token))
    return resp

@router.any("/register")
def register_page(request: Request) -> Response:
    if request.user: return Response.redirect("/dashboard")
    if request.method == "GET":
        return Response.html(admin_render("register.html", request,
                                          {"prefill_name":"","prefill_email":""}))
    name  = request.form.get("name","")
    email = request.form.get("email","")
    pw    = request.form.get("password","")
    try:
        auth_register(name, email, pw)
        user, token = auth_login(email, pw)
    except (RegistrationError, AuthError) as e:
        return Response.html(admin_render("register.html", request,
                                          {"error": str(e), "prefill_name": name,
                                           "prefill_email": email}))
    resp = Response.redirect("/dashboard")
    resp.set_cookie(sessions.make_cookie(token))
    return resp

@router.post("/logout")
def logout(request: Request) -> Response:
    auth_logout(request)
    resp = Response.redirect("/login")
    resp.set_cookie(sessions.clear_cookie())
    return resp

# ── Protected ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
@require_login
def dashboard(request: Request) -> Response:
    all_posts = QuerySet(Post).filter(content_type="post").all()
    resp = Response.html(admin_render("dashboard.html", request, {
        "stats": {
            "total":     len(all_posts),
            "published": sum(1 for p in all_posts if p.status == "published"),
            "drafts":    sum(1 for p in all_posts if p.status == "draft"),
        },
        "recent_posts": sorted(all_posts, key=lambda p: p.created_at, reverse=True)[:8],
        "can_write":    can(request.user, "write_post"),
    }))
    clear_flash(resp)
    return resp

@router.any("/account/password")
@require_login
def change_pw_page(request: Request) -> Response:
    if request.method == "GET":
        resp = Response.html(admin_render("change_password.html", request, {"success": None}))
        clear_flash(resp)
        return resp
    new_pw  = request.form.get("new_password","")
    confirm = request.form.get("confirm_password","")
    if new_pw != confirm:
        return Response.html(admin_render("change_password.html", request,
                                          {"error":"Passwords do not match.","success":None}))
    try:
        change_password(request.user.id, request.form.get("old_password",""), new_pw)
        user, token = auth_login(request.user.email, new_pw)
    except AuthError as e:
        return Response.html(admin_render("change_password.html", request,
                                          {"error":str(e),"success":None}))
    resp = Response.html(admin_render("change_password.html", request,
                                      {"error":None,"success":"Password updated."}))
    resp.set_cookie(sessions.make_cookie(token))
    return resp

# ── Admin ─────────────────────────────────────────────────────────────────────

def _admin_ctx(request, **extra):
    return {
        "users":        QuerySet(User).order_by("created_at").all(),
        "role_options": ROLE_HIERARCHY,
        "settings_fields": [
            ("site_name",      "Site name",      Setting.get_value("site_name","")),
            ("site_tagline",   "Tagline",        Setting.get_value("site_tagline","")),
            ("posts_per_page", "Posts per page", Setting.get_value("posts_per_page","10")),
        ],
        "themes":       loader.available(),
        "active_theme": loader.active,
        **extra,
    }

@router.get("/admin")
def legacy_admin_route(request: Request) -> Response:
    return Response.redirect("/py-admin")

@router.get("/py-admin")
@require_capability("manage_users")
def admin_panel(request: Request) -> Response:
    all_posts = QuerySet(Post).filter(content_type="post").all()
    ctx = _admin_ctx(
        request,
        stats={
            "total": len(all_posts),
            "published": sum(1 for post in all_posts if post.status == "published"),
            "drafts": sum(1 for post in all_posts if post.status == "draft"),
        },
        recent_posts=sorted(all_posts, key=lambda post: post.created_at, reverse=True)[:8],
        can_write=can(request.user, "write_post"),
    )
    resp = Response.html(admin_render("admin.html", request, ctx))
    clear_flash(resp)
    return resp

@router.post("/admin/users/<uid>/role")
@require_capability("manage_roles")
def admin_change_role(request: Request, uid: str) -> Response:
    try:
        update_role(int(uid), request.form.get("role",""), changed_by=request.user)
        return _redirect_with_flash("/py-admin#users", "Role updated.")
    except AuthError as e:
        return Response.html(admin_render("admin.html", request,
                                          _admin_ctx(request, flash_err=str(e))))

@router.post("/admin/users/<uid>/toggle")
@require_capability("manage_users")
def admin_toggle_user(request: Request, uid: str) -> Response:
    try:
        u = QuerySet(User).get(id=int(uid))
        u.active = 0 if u.active else 1
        u.save()
        if not u.active: sessions.delete_for_user(u.id)
        msg = f"User '{u.name}' {'activated' if u.active else 'deactivated'}."
    except Exception as e:
        msg = str(e)
    return _redirect_with_flash("/py-admin#users", msg)

@router.post("/admin/settings")
@require_capability("manage_settings")
def admin_save_settings(request: Request) -> Response:
    for key in ("site_name","site_tagline","posts_per_page"):
        val = request.form.get(key)
        if val is not None: Setting.set_value(key, val.strip())
    return _redirect_with_flash("/py-admin#settings", "Settings saved.")

@router.post("/admin/theme")
@require_capability("manage_settings")
def admin_switch_theme(request: Request) -> Response:
    slug = request.form.get("theme","").strip()
    try:
        loader.switch(slug)
        Setting.set_value("active_theme", slug)
        return _redirect_with_flash("/py-admin#themes", f"Theme switched to '{loader.active.name}'.")
    except ThemeError as e:
        return Response.html(admin_render("admin.html", request,
                                          _admin_ctx(request, flash_err=f"Theme error: {e}")))

# ── JSON API ──────────────────────────────────────────────────────────────────
from modules.api.routes import register_api_routes
register_api_routes(router)

# ── Middleware with logging ───────────────────────────────────────────────────

from blocks.middleware import LoggingMiddleware

auth   = AuthMiddleware(router)
logged = LoggingMiddleware(auth)
server = Server(logged, host=os.environ.get("HOST", "127.0.0.1"), port=8080)

if __name__ == "__main__":
    server.serve()
