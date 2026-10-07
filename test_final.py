"""
test_final.py – comprehensive end-to-end test suite for the complete PyServer.
Tests all features: routing, auth, content, themes, API, flash, search, CSRF, logging.

Run with: python test_final.py
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))
os.environ["DB_PATH"] = ":memory:"

import app as _app   # single import
from urllib.parse import urlencode
from core.request   import Request
from core.response  import Response
from change_password.users.model import User
from modules.auth.passwords  import hash_password
from change_password.content.models import Post, PostRevision
from change_password.content.service import create_post, get_revisions
from change_password.settings.model import Setting
from database.orm            import QuerySet

Post.create_table()
PostRevision.create_table()

# ── Test helpers ──────────────────────────────────────────────────────────────
PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
_failures = []

def check(label: str, cond: bool, detail: str = ""):
    mark = PASS if cond else FAIL
    print(f"  {mark}  {label}" + (f"  [{detail}]" if detail else ""))
    if not cond: _failures.append(label)

def section(title: str):
    print(f"\n── {title} {'─' * max(0, 60-len(title))}")

def go(method: str, path: str, form=None, cookie: str = ""):
    h = {}; b = b""
    if cookie and method.upper() not in ("GET", "HEAD", "OPTIONS", "TRACE"):
        from blocks.csrf import csrf_token_for
        from core.request import Request as _Request
        csrf = csrf_token_for(_Request("GET", "/", {"Cookie": f"pysess={cookie}"}))
        if isinstance(form, dict):
            form = {**form, "_csrf": csrf}
        else:
            h["X-CSRF-Token"] = csrf
    if form and isinstance(form, dict):
        b = urlencode(form).encode()
        h["Content-Type"]   = "application/x-www-form-urlencoded"
        h["Content-Length"] = str(len(b))
    elif form and isinstance(form, str):
        b = form.encode()
        h["Content-Type"]   = "application/json"
        h["Content-Length"] = str(len(b))
    if cookie:
        h["Cookie"] = f"pysess={cookie}"
    return _app.auth.dispatch(Request(method, path, h, b))

def session_cookie(resp) -> str | None:
    for c in getattr(resp, "_cookies", []):
        if c.startswith("pysess=") and "Max-Age=0" not in c:
            return c.split(";")[0].replace("pysess=", "")
    return None

def flash_cookie(resp) -> str | None:
    for c in getattr(resp, "_cookies", []):
        if c.startswith("pyflash=") and "Max-Age=0" not in c:
            return c
    return None

def jbody(resp) -> dict:
    try:    return json.loads(resp.body)
    except: return {}

# ── Seed users ────────────────────────────────────────────────────────────────
admin  = User.objects.create(name="Admin User",  email="admin@test.com",  password=hash_password("adminpass1"), role="admin",  active=1)
editor = User.objects.create(name="Editor User", email="editor@test.com", password=hash_password("editorpass1"), role="editor", active=1)
member = User.objects.create(name="Member User", email="member@test.com", password=hash_password("memberpass1"), role="member", active=1)

a_sess = session_cookie(go("POST", "/login", {"email": "admin@test.com",  "password": "adminpass1"}))
e_sess = session_cookie(go("POST", "/login", {"email": "editor@test.com", "password": "editorpass1"}))
m_sess = session_cookie(go("POST", "/login", {"email": "member@test.com", "password": "memberpass1"}))

# Seed some posts
pub1 = create_post("First Post",   "<p>Hello world</p>",  author_id=admin.id,  status="published")
pub2 = create_post("Second Post",  "<p>More content</p>", author_id=editor.id, status="published")
draft = create_post("Draft Post",  "<p>Not live yet</p>", author_id=admin.id,  status="draft")
page1 = Post.objects.create(title="About Us", slug="about-us", body="<p>About</p>",
        content_type="page", author_id=admin.id, status="published", revision=1)

# ─────────────────────────────────────────────────────────────────────────────
section("Public pages")
r = go("GET", "/")
check("homepage 200",            r.status == 200)
check("shows published post",    "First Post" in r.body)
check("hides draft post",        "Draft Post" not in r.body)
check("has DOCTYPE",             "<!DOCTYPE" in r.body)
check("has nav header",          "<header" in r.body)
check("has footer",              "<footer" in r.body)

r = go("GET", "/posts")
check("post list 200",           r.status == 200)
check("shows both posts",        "First Post" in r.body and "Second Post" in r.body)

r = go("GET", f"/posts/{pub1.slug}")
check("single post 200",         r.status == 200)
check("title in page",           "First Post" in r.body)
check("body content shown",      "Hello world" in r.body)

r = go("GET", "/posts/nonexistent-slug-xyz")
check("missing post 404",        r.status == 404)
check("404 page themed",         "<!DOCTYPE" in r.body)

r = go("GET", "/pages/about-us")
check("CMS page 200",            r.status == 200)
check("page content shown",      "About Us" in r.body)

r = go("GET", f"/posts/{draft.slug}")
check("draft redirects anon",    r.status == 302)
check("redirect to login",       r.headers.get("Location") == "/login")

r = go("GET", f"/posts/{draft.slug}", cookie=a_sess)
check("draft visible to admin",  r.status == 200)

# ─────────────────────────────────────────────────────────────────────────────
section("Search")
r = go("GET", "/search?q=First")
check("search 200",              r.status == 200)
check("result shown",            "First Post" in r.body)
check("draft not in results",    "Draft Post" not in r.body)

r = go("GET", "/search?q=nothing-here-xyz")
check("no results 200",          r.status == 200)
check("no results message",      "No results" in r.body or "0 result" in r.body)

r = go("GET", "/search?q=")
check("empty query handled",     r.status == 200)

r = go("GET", "/search?q=F")
check("1-char query handled",    r.status == 200)

# ─────────────────────────────────────────────────────────────────────────────
section("Auth: login / register / logout")
r = go("GET", "/login")
check("login page 200",          r.status == 200)
check("has form",                'action="/login"' in r.body)

r = go("POST", "/login", {"email": "admin@test.com", "password": "wrongpass"})
check("bad login 200 + error",   r.status == 200)
check("error message shown",     "invalid" in r.body.lower())

r = go("GET", "/login", cookie=a_sess)
check("logged-in GET /login → 302", r.status == 302)

r = go("POST", "/logout", cookie=a_sess)
check("logout 302",              r.status == 302)
check("clears cookie",           any("Max-Age=0" in c for c in getattr(r, "_cookies", [])))

# Re-login admin
a_sess = session_cookie(go("POST", "/login", {"email": "admin@test.com", "password": "adminpass1"}))

r = go("GET", "/register")
check("register page 200",       r.status == 200)

r = go("POST", "/register", {"name": "New User", "email": "new@test.com", "password": "newpass123"})
check("register → 302",          r.status == 302)
check("session cookie set",      session_cookie(r) is not None)

r = go("POST", "/register", {"name": "X", "email": "new@test.com", "password": "newpass123"})
check("duplicate email → error", r.status == 200)

r = go("POST", "/register", {"name": "", "email": "bad", "password": "short"})
check("invalid fields → error",  r.status == 200)

# ─────────────────────────────────────────────────────────────────────────────
section("Auth: protection and capabilities")
r = go("GET", "/dashboard")
check("dashboard → 302 anon",    r.status == 302)

r = go("GET", "/py-admin")
check("admin → 401 anon",        r.status == 401)

r = go("GET", "/py-admin", cookie=m_sess)
check("admin → 403 member",      r.status == 403)

r = go("GET", "/dashboard", cookie=m_sess)
check("dashboard 200 member",    r.status == 200)

r = go("GET", "/py-admin", cookie=a_sess)
check("admin 200 admin",         r.status == 200)
check("admin page has sidebar",   "Administration navigation" in r.body)

r = go("GET", "/posts/new", cookie=m_sess)
check("posts/new → 403 member",  r.status == 403)

r = go("GET", "/posts/new", cookie=e_sess)
check("posts/new → 200 editor",  r.status == 200)

# ─────────────────────────────────────────────────────────────────────────────
section("Post CRUD")
r = go("POST", "/posts/new",
       {"title": "Test Post", "body": "<p>Content</p>", "action": "save"}, e_sess)
check("create draft → 302",      r.status == 302)
new_slug = r.headers.get("Location", "").split("/posts/")[1].split("/edit")[0]
check("slug in redirect",        bool(new_slug) and new_slug != "")

from change_password.content.service import get_post_by_slug
new_post = get_post_by_slug(new_slug)
check("post saved to DB",        new_post.title == "Test Post")
check("status = draft",          new_post.status == "draft")
check("revision = 1",            new_post.revision == 1)

r = go("GET", f"/posts/{new_slug}/edit?saved=1", cookie=e_sess)
check("edit page 200",           r.status == 200)
check("title in form",           "Test Post" in r.body)

r = go("POST", f"/posts/{new_slug}/edit",
       {"title": "Updated Post", "body": "<p>New body</p>", "action": "publish"}, e_sess)
check("update+publish → 302",    r.status == 302)
updated_slug = r.headers.get("Location", "").split("/posts/")[1].split("/edit")[0]
updated = get_post_by_slug(updated_slug)
check("title updated",           updated.title == "Updated Post")
check("status = published",      updated.status == "published")
check("revision incremented",    updated.revision >= 2)

# Revision restore
revs = get_revisions(updated.id)
check("revisions exist",         len(revs) >= 2)
r = go("POST", f"/posts/{updated_slug}/restore",
       {"revision": str(revs[-1].revision)}, e_sess)
check("restore → 302",           r.status == 302)

# Delete
throwaway = create_post("Throwaway", "<p>x</p>", author_id=editor.id)
r = go("POST", f"/posts/{throwaway.slug}/delete", cookie=e_sess)
check("delete → 302",            r.status == 302)
r = go("GET", f"/posts/{throwaway.slug}")
check("deleted post → 404",      r.status == 404)

# ─────────────────────────────────────────────────────────────────────────────
section("Flash messages")
from blocks.flash import set_flash, get_flash, inject_flash
from core.response import Response as _Resp

resp = _Resp.redirect("/test")
set_flash(resp, "Item saved!", kind="ok")
check("flash cookie set",        any("pyflash=" in c for c in resp._cookies))

class _R:
    headers = {"Cookie": next(c for c in resp._cookies if "pyflash=" in c).split(";")[0]}
flash = get_flash(_R())
check("flash message read",      flash["message"] == "Item saved!")
check("flash kind = ok",         flash["kind"] == "ok")

ctx = {}
inject_flash(_R(), ctx)
check("inject_flash sets flash_ok", ctx["flash_ok"] == "Item saved!")

# Flash from settings save
r = go("POST", "/admin/settings",
       {"site_name": "TestSite", "site_tagline": "Testing", "posts_per_page": "10"}, a_sess)
check("settings save → 302",     r.status == 302)
check("flash cookie on response", flash_cookie(r) is not None)
check("setting persisted",       Setting.get_value("site_name") == "TestSite")

# Flash from delete
delete_me = create_post("Delete Me", "<p>x</p>", author_id=admin.id)
r = go("POST", f"/posts/{delete_me.slug}/delete", cookie=a_sess)
check("delete flash set",        flash_cookie(r) is not None)

# ─────────────────────────────────────────────────────────────────────────────
section("JSON API")
r = go("GET", "/api/health")
check("health 200",              r.status == 200)
d = jbody(r)
check("health status=ok",        d.get("status") == "ok")
check("health db=ok",            d.get("db") == "ok")

r = go("GET", "/api/settings")
check("settings 200",            r.status == 200)
check("has site_name",           "site_name" in jbody(r).get("data", {}))

r = go("GET", "/api/posts")
check("list posts 200",          r.status == 200)
d = jbody(r)
check("has data key",            "data" in d)
check("has total",               "total" in d and d["total"] >= 2)
check("has pages",               "pages" in d)
check("has per_page",            "per_page" in d)

r = go("GET", f"/api/posts/{pub1.slug}")
check("get post 200",            r.status == 200)
d = jbody(r)["data"]
check("post has id",             "id" in d)
check("post has title",          d["title"] == "First Post")
check("post has excerpt",        "excerpt" in d)
check("post has body",           "body" in d)
check("post has revision",       "revision" in d)

r = go("GET", "/api/posts/no-such-post-xyz")
check("missing post → 404",      r.status == 404)
check("json error shape",        "error" in jbody(r))

# Create via API
r = go("POST", "/api/posts", json.dumps({"title": "API Post", "body": "<p>API body</p>"}), e_sess)
check("create 201",              r.status == 201)
api_slug = jbody(r)["data"]["slug"]
check("slug in response",        bool(api_slug))
check("status=draft",            jbody(r)["data"]["status"] == "draft")

# Update via PUT (send with auth cookie to see draft)
r = go("PUT", f"/api/posts/{api_slug}", json.dumps({"title": "Updated via API"}), e_sess)
check("update 200",              r.status == 200)
check("title updated",           jbody(r)["data"]["title"] == "Updated via API")
api_slug = jbody(r)["data"]["slug"]  # track new slug after title rename

# Publish via API
r = go("PUT", f"/api/posts/{api_slug}", json.dumps({"status": "published"}), e_sess)
check("publish via API 200",     r.status in (200, 200))
if r.status == 200:
    check("published",           jbody(r)["data"]["status"] == "published")
else:
    check("published",           False, f"status={r.status}")

# Delete via API
r = go("DELETE", f"/api/posts/{api_slug}", None, e_sess)
check("delete 200",              r.status == 200)
check("deleted=true",            jbody(r).get("deleted") is True)

# Permissions
r = go("POST", "/api/posts", json.dumps({"title": "T", "body": "B"}))
check("anon create → 401",       r.status == 401)

r = go("POST", "/api/posts", json.dumps({"title": "", "body": "B"}), e_sess)
check("blank title → 400",       r.status == 400)
check("code=VALIDATION_ERROR",   jbody(r).get("code") == "VALIDATION_ERROR")

# API Search
r = go("GET", "/api/search?q=First")
check("api search 200",          r.status == 200)
d = jbody(r)
check("search has query",        d.get("query") == "First")
check("search found result",     d.get("total", 0) >= 1)

r = go("GET", "/api/search?q=x")
check("short query → 400",       r.status == 400)

# ─────────────────────────────────────────────────────────────────────────────
section("CSRF protection")
from blocks.csrf import csrf_token_for, validate_csrf, CSRFError

# Use a real session (a_sess) for CSRF tests
class _Req:
    def __init__(self, ck, method="GET"):
        self.method  = method
        self.headers = {"Cookie": f"pysess={ck}"}
        self._form   = {}
    @property
    def form(self): return self._form

req1 = _Req(a_sess)
tok1 = csrf_token_for(req1)
check("token generated",         len(tok1) == 32)
check("token is hex",            all(c in "0123456789abcdef" for c in tok1))

req2 = _Req(a_sess)  # fresh object, same session
tok2 = csrf_token_for(req2)
check("same token on repeat",    tok1 == tok2)

req_get = _Req(a_sess, "GET")
try:    validate_csrf(req_get); check("GET skips csrf", True)
except: check("GET skips csrf", False)

req_post = _Req(a_sess, "POST"); req_post._form = {"_csrf": tok1}
try:    validate_csrf(req_post); check("valid token passes", True)
except: check("valid token passes", False)

req_bad = _Req(a_sess, "POST"); req_bad._form = {"_csrf": "bad_token"}
try:
    validate_csrf(req_bad)
    check("bad token raises CSRFError", False)
except CSRFError:
    check("bad token raises CSRFError", True)

# ─────────────────────────────────────────────────────────────────────────────
section("Theme system")
check("active theme: default",   _app.loader.active.slug == "default")
check("available: 2 themes",     len(_app.loader.available()) >= 2)

r = go("GET", "/")
check("default theme in body",   "theme-default" in r.body)
check("search in nav",           "action=\"/search\"" in r.body or "/search" in r.body)

r = go("POST", "/admin/theme", {"theme": "minimal"}, a_sess)
check("switch to minimal → 302", r.status == 302)
check("minimal is active",       _app.loader.active.slug == "minimal")

r = go("GET", "/")
check("minimal: serif font",     "Lora" in r.body or "serif" in r.body)
check("minimal: theme-minimal",  "theme-minimal" in r.body)

r = go("POST", "/admin/theme", {"theme": "default"}, a_sess)
check("switched back",           _app.loader.active.slug == "default")

r = go("POST", "/admin/theme", {"theme": "nonexistent_theme"}, a_sess)
check("bad theme: still default", _app.loader.active.slug == "default")

# Theme assets
import os
asset_path = "themes/default/assets/style.css"
os.makedirs(os.path.dirname(asset_path), exist_ok=True)
with open(asset_path, "w") as f: f.write("body{color:red}")
r = go("GET", "/themes/default/assets/style.css")
check("asset served 200",        r.status == 200)
check("correct content-type",    "css" in r.content_type)

r = go("GET", "/themes/default/assets/../../theme.py")
check("path traversal blocked",  r.status == 404)

# ─────────────────────────────────────────────────────────────────────────────
section("Admin panel")
r = go("GET", "/py-admin", cookie=a_sess)
check("admin panel 200",         r.status == 200)
check("has theme switcher",      "Themes" in r.body)
check("has users table",         "Users" in r.body)
check("has settings form",       "Site" in r.body)

r = go("POST", "/admin/users/{}/toggle".format(member.id), None, a_sess)
check("toggle user → 302",       r.status == 302)
toggled = QuerySet(User).get(id=member.id)
check("active flipped",          toggled.active == 0)
go("POST", "/admin/users/{}/toggle".format(member.id), None, a_sess)
check("toggled back",            QuerySet(User).get(id=member.id).active == 1)

r = go("POST", f"/admin/users/{editor.id}/role", {"role": "member"}, a_sess)
check("role change → 302",       r.status == 302)
check("role persisted",          QuerySet(User).get(id=editor.id).role == "member")
go("POST", f"/admin/users/{editor.id}/role", {"role": "editor"}, a_sess)

# ─────────────────────────────────────────────────────────────────────────────
section("Change password")
r = go("GET", "/account/password", cookie=e_sess)
check("change-pw page 200",      r.status == 200)

r = go("POST", "/account/password", {
    "old_password": "editorpass1",
    "new_password": "neweditor456",
    "confirm_password": "neweditor456",
}, e_sess)
check("change pw 200",           r.status == 200)
check("success message",         "updated" in r.body.lower() or "success" in r.body.lower())
new_e_sess = session_cookie(r)
check("new session issued",      new_e_sess is not None)

r = go("POST", "/account/password", {
    "old_password": "neweditor456",
    "new_password": "abc",
    "confirm_password": "xyz",
}, new_e_sess or e_sess)
check("mismatch → error",        "match" in r.body.lower() or "error" in r.body.lower())

# ─────────────────────────────────────────────────────────────────────────────
section("Logger")
from blocks.logger import get_logger, Logger
log = get_logger("test_final")
check("get_logger returns Logger", isinstance(log, Logger))
log.info("test info message", key="val")
log.warning("test warning")
log.debug("debug (may be suppressed)")
log.error("test error msg")
check("logger doesn't crash",    True)

# ─────────────────────────────────────────────────────────────────────────────
section("Pagination")
# Create enough posts for pagination
for i in range(8):
    create_post(f"Page Post {i}", f"<p>body {i}</p>", author_id=admin.id, status="published")

from change_password.settings.model import Setting
Setting.set_value("posts_per_page", "3")

r = go("GET", "/posts?page=1")
check("page 1 200",              r.status == 200)
check("pagination controls shown", "page=2" in r.body or "Next" in r.body)

r = go("GET", "/posts?page=2")
check("page 2 200",              r.status == 200)

r = go("GET", "/posts?page=999")
check("out-of-range page 200",   r.status == 200)

Setting.set_value("posts_per_page", "10")

# ─────────────────────────────────────────────────────────────────────────────
section("Route ordering")
patterns = [r[0].pattern for r in _app.router._routes]
new_idx  = next(i for i,p in enumerate(patterns) if p == "/posts/new")
slug_idx = next(i for i,p in enumerate(patterns) if p == r"/posts/([^/]+)")
edit_idx = next(i for i,p in enumerate(patterns) if "edit" in p and "posts" in p)
check("/posts/new before /posts/<slug>", new_idx < slug_idx)
check("/posts/<slug>/edit before /posts/<slug>", edit_idx < slug_idx)

api_slug_idx = next(i for i,p in enumerate(patterns) if p == r"/api/posts/([^/]+)")
api_col_idx  = next(i for i,p in enumerate(patterns) if p == "/api/posts")
check("/api/posts before /api/posts/<slug>", api_col_idx < api_slug_idx)

# ─────────────────────────────────────────────────────────────────────────────
section("500 error handler")
import os as _os
_os.environ["DEBUG"] = "1"

@_app.router.get("/test-500-route-xyz")
def broken_route(request):
    raise RuntimeError("Intentional test error")

r = go("GET", "/test-500-route-xyz")
check("500 returns 500 status",  r.status == 500)
check("500 page has error text", "500" in r.body or "error" in r.body.lower())
check("500 response omits traceback", "Traceback" not in r.body)
del _os.environ["DEBUG"]

# ─────────────────────────────────────────────────────────────────────────────
print()
total = len(_failures)
if total:
    print(f"\033[91m  {total} test(s) FAILED:\033[0m")
    for f in _failures: print(f"    • {f}")
    print()
    sys.exit(1)
else:
    passed = sum(1 for line in open(__file__) if "check(" in line and not line.strip().startswith("#"))
    print(f"\033[92m  All {passed} tests passed.\033[0m\n")
