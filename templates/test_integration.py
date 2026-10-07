"""
test_integration.py – end-to-end HTTP integration tests.
Run with: python test_integration.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

os.environ["DB_PATH"] = ":memory:"
import importlib, app as _app
importlib.reload(_app)

from core.request  import Request
from core.response import Response
from urllib.parse  import urlencode

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
_failures = 0

def check(label, cond, detail=""):
    global _failures
    print(f"  {PASS if cond else FAIL}  {label}" + (f"  [{detail}]" if detail else ""))
    if not cond: _failures += 1

def dispatch(method, path, form=None, cookie=""):
    headers = {}
    body    = b""
    if cookie and method.upper() not in ("GET", "HEAD", "OPTIONS", "TRACE"):
        from blocks.csrf import csrf_token_for
        csrf = csrf_token_for(Request("GET", "/", {"Cookie": cookie}, b""))
        form = {**(form or {}), "_csrf": csrf}
    if form:
        body = urlencode(form).encode()
        headers["Content-Type"]   = "application/x-www-form-urlencoded"
        headers["Content-Length"] = str(len(body))
    if cookie:
        headers["Cookie"] = cookie
    req  = Request(method=method, path=path, headers=headers, body=body)
    return _app.auth.dispatch(req)

def session_cookie(resp):
    for c in getattr(resp, "_cookies", []):
        if c.startswith("pysess=") and "Max-Age=0" not in c:
            return c.split(";")[0].replace("pysess=", "")
    return None

# ── Seed a real admin user directly via ORM ───────────────────────────────────
from change_password.users.model import User
from modules.auth.passwords import hash_password
from database.orm import QuerySet

real_admin = User.objects.create(
    name="Real Admin", email="realadmin@test.com",
    password=hash_password("adminpass9999"), role="admin", active=1
)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Public pages ─────────────────────────────────────────────────────")

r = dispatch("GET", "/")
check("home 200",             r.status == 200)
check("home: site title",     "PyServer" in r.body)
check("home: seeded content", "Hello World" in r.body)

r = dispatch("GET", "/login")
check("login page 200",       r.status == 200)
check("login: has form",      'action="/login"' in r.body)

r = dispatch("GET", "/register")
check("register page 200",    r.status == 200)
check("register: has form",   'action="/register"' in r.body)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Unauthenticated redirects ─────────────────────────────────────────")

r = dispatch("GET", "/dashboard")
check("dashboard → 302",      r.status == 302)
check("redirect to /login",   r.headers.get("Location") == "/login")

r = dispatch("GET", "/py-admin")
check("admin → 401",          r.status == 401)
r = dispatch("GET", "/admin")
check("legacy admin URL redirects", r.status == 302 and r.headers.get("Location") == "/py-admin")

r = dispatch("GET", "/account/password")
check("account/pw → 302",     r.status == 302)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Registration flow ────────────────────────────────────────────────")

r = dispatch("POST", "/register", form={
    "name": "Jane Test", "email": "jane@test.com", "password": "janepw1234"
})
check("POST /register → 302",     r.status == 302)
check("redirects to /dashboard",  r.headers.get("Location") == "/dashboard")
jane_sess = session_cookie(r)
check("session cookie issued",    jane_sess is not None)

# Duplicate
r = dispatch("POST", "/register", form={
    "name": "Jane2", "email": "jane@test.com", "password": "janepw1234"
})
check("duplicate → 200 + error",  r.status == 200)
check("error text present",       "already exists" in r.body.lower())

# Validation
r = dispatch("POST", "/register", form={"name":"", "email":"bad", "password":"short"})
check("invalid fields → 200 + error", r.status == 200)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Login / logout ───────────────────────────────────────────────────")

r = dispatch("POST", "/login", form={"email":"jane@test.com", "password":"janepw1234"})
check("POST /login → 302",         r.status == 302)
check("redirects to /dashboard",   r.headers.get("Location") == "/dashboard")
sess1 = session_cookie(r)
check("session cookie issued",     sess1 is not None)

r = dispatch("POST", "/login", form={"email":"jane@test.com", "password":"WRONG"})
check("bad password → 200 + error", r.status == 200)
check("error text: invalid",        "invalid" in r.body.lower())

r = dispatch("GET", "/login", cookie=f"pysess={sess1}")
check("already-logged-in → 302",   r.status == 302)

r = dispatch("POST", "/logout", cookie=f"pysess={sess1}")
check("logout → 302",              r.status == 302)
check("session cookie cleared",    any("Max-Age=0" in c for c in getattr(r, "_cookies", [])))

r = dispatch("GET", "/dashboard", cookie=f"pysess={sess1}")
check("post-logout dashboard → 302", r.status == 302)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Dashboard ────────────────────────────────────────────────────────")

r = dispatch("POST", "/login", form={"email":"jane@test.com","password":"janepw1234"})
sess2 = session_cookie(r)

r = dispatch("GET", "/dashboard", cookie=f"pysess={sess2}")
check("dashboard 200",           r.status == 200)
check("shows user name",         "Jane Test" in r.body)
check("shows stats",             "Total posts" in r.body)
check("shows account section",   "Account" in r.body)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Change password ──────────────────────────────────────────────────")

r = dispatch("GET", "/account/password", cookie=f"pysess={sess2}")
check("GET change-pw 200",  r.status == 200)
check("has form",           "old_password" in r.body)

# Mismatch
r = dispatch("POST", "/account/password", cookie=f"pysess={sess2}", form={
    "old_password": "janepw1234",
    "new_password": "newjane5678",
    "confirm_password": "DIFFERENT",
})
check("mismatch → 200 + error",  r.status == 200)
check("mismatch error text",     "match" in r.body.lower())

# Correct change
r = dispatch("POST", "/account/password", cookie=f"pysess={sess2}", form={
    "old_password":     "janepw1234",
    "new_password":     "newjane5678",
    "confirm_password": "newjane5678",
})
check("correct change → 200",       r.status == 200)
check("success message shown",      "updated" in r.body.lower() or "success" in r.body.lower())
new_sess = session_cookie(r)
check("fresh session cookie set",   new_sess is not None)

r = dispatch("POST", "/login", form={"email":"jane@test.com","password":"janepw1234"})
check("old password rejected",  r.status == 200)

r = dispatch("POST", "/login", form={"email":"jane@test.com","password":"newjane5678"})
check("new password works",     r.status == 302)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Admin panel ──────────────────────────────────────────────────────")

r = dispatch("POST", "/login", form={"email":"realadmin@test.com","password":"adminpass9999"})
check("admin login → 302",     r.status == 302)
admin_sess = session_cookie(r)
check("admin session set",     admin_sess is not None)

r = dispatch("GET", "/py-admin", cookie=f"pysess={admin_sess}")
check("admin panel 200",            r.status == 200)
check("shows users table",          "Users" in r.body)
check("shows settings form",        "Site" in r.body or "settings" in r.body.lower())
check("shows role selects",         "role" in r.body.lower())

# Member cannot reach admin
r = dispatch("POST", "/login", form={"email":"jane@test.com","password":"newjane5678"})
mem_sess = session_cookie(r)
r = dispatch("GET", "/py-admin", cookie=f"pysess={mem_sess}")
check("member → 403",               r.status == 403)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Admin: save settings ─────────────────────────────────────────────")

r = dispatch("POST", "/admin/settings", cookie=f"pysess={admin_sess}", form={
    "site_name":      "IntegrationSite",
    "site_tagline":   "Testing",
    "posts_per_page": "5",
})
check("save settings → 302",  r.status == 302)

from change_password.settings.model import Setting
check("site_name persisted",  Setting.get_value("site_name") == "IntegrationSite")
check("posts_per_page saved", Setting.get_value("posts_per_page") == "5")

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Admin: role change ───────────────────────────────────────────────")

jane_db = QuerySet(User).get(email="jane@test.com")
r = dispatch("POST", f"/admin/users/{jane_db.id}/role",
             cookie=f"pysess={admin_sess}", form={"role": "editor"})
check("role change → 302",         r.status == 302)
check("role change sets flash",    any("pyflash=" in c for c in getattr(r, "_cookies", [])))
jane_fresh = QuerySet(User).get(id=jane_db.id)
check("role persisted as editor",  jane_fresh.role == "editor")

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Admin: toggle user active state ──────────────────────────────────")

jane_db = QuerySet(User).get(email="jane@test.com")
was_active = jane_db.active

r = dispatch("POST", f"/admin/users/{jane_db.id}/toggle",
             cookie=f"pysess={admin_sess}")
check("toggle → 302",              r.status == 302)

jane_toggled = QuerySet(User).get(id=jane_db.id)
check("active state flipped",      jane_toggled.active != was_active)

# Toggle back
dispatch("POST", f"/admin/users/{jane_db.id}/toggle", cookie=f"pysess={admin_sess}")
jane_restored = QuerySet(User).get(id=jane_db.id)
check("toggle back restored",      jane_restored.active == was_active)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── AuthMiddleware injection ─────────────────────────────────────────")

from change_password.middleware import AuthMiddleware

captured = {}

class CapturingRouter:
    def dispatch(self, req):
        captured["user"]  = req.user
        captured["auth"]  = req.is_authenticated
        captured["admin"] = req.is_admin
        return Response.html("ok")

mw = AuthMiddleware(CapturingRouter())

r = dispatch("POST", "/login", form={"email":"realadmin@test.com","password":"adminpass9999"})
a_tok = session_cookie(r)
req_in = Request("GET", "/", {"Cookie": f"pysess={a_tok}"}, b"")
mw.dispatch(req_in)
check("middleware: user resolved",      captured.get("user") is not None)
check("middleware: is_authenticated",   captured.get("auth") is True)
check("middleware: is_admin",           captured.get("admin") is True)

req_anon = Request("GET", "/", {}, b"")
mw.dispatch(req_anon)
check("middleware: anon user=None",     captured.get("user") is None)
check("middleware: anon auth=False",    captured.get("auth") is False)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── require_capability decorator ─────────────────────────────────────")

from modules.auth.permissions import require_capability, require_login, can

class FU:
    def __init__(self, role): self.role = role; self.active = 1
    def is_admin(self): return self.role == "admin"

admin_u  = FU("admin")
editor_u = FU("editor")
member_u = FU("member")

def dummy(req, **kw): return Response.html("OK")

protected = require_capability("manage_users")(dummy)

class Req:
    def __init__(self, u): self.user = u; self.headers = {}

check("admin can manage_users",       protected(Req(admin_u)).status == 200)
check("editor cannot manage_users",   protected(Req(editor_u)).status == 403)
check("member cannot manage_users",   protected(Req(member_u)).status == 403)
check("anon → 401",                   protected(Req(None)).status == 401)

login_only = require_login(dummy)
check("require_login: auth passes",    login_only(Req(member_u)).status == 200)
check("require_login: anon → 302",    login_only(Req(None)).status == 302)

check("can(): admin write_post",       can(admin_u, "write_post"))
check("can(): editor publish_post",    can(editor_u, "publish_post"))
check("can(): member read only",       can(member_u, "read") and not can(member_u, "write_post"))

# ─────────────────────────────────────────────────────────────────────────────
print()
if _failures:
    print(f"\033[91m  {_failures} test(s) FAILED\033[0m\n")
    sys.exit(1)
else:
    print(f"\033[92m  All integration tests passed.\033[0m\n")
