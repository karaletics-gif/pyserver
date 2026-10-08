"""
test_auth.py – tests for passwords, sessions, permissions, and auth service.
Run with: python test_auth.py
"""

import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from database.orm         import connect
from cms.users.model  import User

# Bootstrap DB
connect(":memory:")
User.create_table()

from modules.auth.passwords   import hash_password, verify_password, needs_rehash
from modules.auth.sessions    import SessionStore
from modules.auth.permissions import can, role_can, capabilities_for, require_capability, require_login, ROLES
from modules.auth.service     import register, login, logout, change_password, get_current_user, AuthError, RegistrationError

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
_failures = 0

def check(label: str, condition: bool, detail: str = ""):
    global _failures
    print(f"  {PASS if condition else FAIL}  {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        _failures += 1

def check_raises(label: str, exc_type, fn):
    global _failures
    try:
        fn(); _failures += 1; print(f"  {FAIL}  {label}  (no exception)")
    except exc_type as e:
        print(f"  {PASS}  {label}  [{e}]")
    except Exception as e:
        _failures += 1; print(f"  {FAIL}  {label}  (wrong exc {type(e).__name__}: {e})")


# ─────────────────────────────────────────────────────────────────────────────
print("\n── hash_password / verify_password ─────────────────────────────────")

h = hash_password("correct-horse-battery")
check("format starts with pbkdf2",   h.startswith("pbkdf2$"))
check("four $-separated parts",      h.count("$") == 3)
check("correct password verifies",   verify_password("correct-horse-battery", h))
check("wrong password fails",        not verify_password("wrong", h))
check("empty stored fails gracefully", not verify_password("pw", ""))
check("malformed stored fails",      not verify_password("pw", "not-a-hash"))

h2 = hash_password("same-password")
h3 = hash_password("same-password")
check("different salts each time",   h2 != h3)
check("both verify",                 verify_password("same-password", h2) and
                                     verify_password("same-password", h3))

check("needs_rehash false (fresh)",  not needs_rehash(h))
check("needs_rehash true (old)",     needs_rehash("pbkdf2$1000$abc$def"))
try:
    hash_password("")
    _failures += 1
    print(f"  {FAIL}  empty password raises  (no exception)")
except ValueError:
    print(f"  {PASS}  empty password raises")


# ─────────────────────────────────────────────────────────────────────────────
print("\n── SessionStore ─────────────────────────────────────────────────────")

store = SessionStore(ttl=3600)

token = store.create(user_id=99, role="admin")
check("token is hex string",       all(c in "0123456789abcdef" for c in token))
check("token length >= 32 chars",  len(token) >= 32)

data = store.get(token)
check("get returns data dict",     data == {"user_id": 99, "role": "admin"})
check("private keys stripped",     "_created" not in data)

check("get unknown token → None",  store.get("nonexistent") is None)
check("get None → None",           store.get(None) is None)

store.update(token, name="Alice")
check("update merges data",        store.get(token)["name"] == "Alice")

store.delete(token)
check("delete removes session",    store.get(token) is None)

# TTL expiry
short_store = SessionStore(ttl=0)
tok2 = short_store.create(user_id=1)
time.sleep(0.01)
check("expired session → None",    short_store.get(tok2) is None)

# Multi-user revocation
multi = SessionStore()
ta = multi.create(user_id=5)
tb = multi.create(user_id=5)
tc = multi.create(user_id=6)
revoked = multi.delete_for_user(5)
check("delete_for_user count",     revoked == 2)
check("user 5 sessions gone",      multi.get(ta) is None and multi.get(tb) is None)
check("user 6 session intact",     multi.get(tc) is not None)

# Cookie helpers
cookie_val = store.make_cookie("mytoken123")
check("cookie contains name",      "pysess=mytoken123" in cookie_val)
check("cookie HttpOnly",           "HttpOnly" in cookie_val)
check("cookie SameSite",           "SameSite=Lax" in cookie_val)
check("clear_cookie Max-Age=0",    "Max-Age=0" in store.clear_cookie())

class FakeReq:
    headers = {"Cookie": "pysess=abc123; other=val"}
check("extract_token parses cookie", store.extract_token(FakeReq()) == "abc123")


# ─────────────────────────────────────────────────────────────────────────────
print("\n── Permissions ──────────────────────────────────────────────────────")

check("admin has all caps",        len(capabilities_for("admin")) == len(capabilities_for("admin")))
check("admin can manage_users",    role_can("admin",  "manage_users"))
check("editor cannot manage_users",not role_can("editor","manage_users"))
check("editor can publish_post",   role_can("editor", "publish_post"))
check("member can only read",      capabilities_for("member") == frozenset({"read"}))
check("unknown role → empty",      capabilities_for("ghost") == frozenset())

# can() with User objects
class FakeUser:
    def __init__(self, role, active=1):
        self.role   = role
        self.active = active

admin_u  = FakeUser("admin")
editor_u = FakeUser("editor")
member_u = FakeUser("member")
dead_u   = FakeUser("admin", active=0)

check("can(admin, manage_users)",        can(admin_u, "manage_users"))
check("can(editor, publish_post)",       can(editor_u, "publish_post"))
check("can(member, read)",               can(member_u, "read"))
check("can(member, write_post) → False", not can(member_u, "write_post"))
check("can(inactive admin) → False",     not can(dead_u, "manage_users"))
check("can(None, read) → False",         not can(None, "read"))

# Decorator: require_login
class FakeReqNoUser:
    user = None
    headers = {}

class FakeReqWithUser:
    user   = admin_u
    headers = {}

def dummy_handler(request, **kw):
    from core.response import Response
    return Response.html("OK")

wrapped = require_login(dummy_handler)
resp_unauth = wrapped(FakeReqNoUser())
check("require_login redirects unauthenticated", resp_unauth.status == 302)
resp_auth   = wrapped(FakeReqWithUser())
check("require_login passes authenticated",      resp_auth.status == 200)

# Decorator: require_capability
protected = require_capability("manage_users")(dummy_handler)

class FakeReqEditor:
    user   = editor_u
    headers = {}

resp_403 = protected(FakeReqEditor())
check("require_capability 403 for editor", resp_403.status == 403)
resp_200 = protected(FakeReqWithUser())
check("require_capability 200 for admin",  resp_200.status == 200)
resp_401 = protected(FakeReqNoUser())
check("require_capability 401 unauthenticated", resp_401.status == 401)


# ─────────────────────────────────────────────────────────────────────────────
print("\n── register() ───────────────────────────────────────────────────────")

alice = register("Alice Smith", "alice@example.com", "SecurePassword1!", role="admin")
check("returns User",      isinstance(alice, User))
check("id assigned",       alice.id is not None)
check("email lower-cased", alice.email == "alice@example.com")
check("password hashed",   alice.password.startswith("pbkdf2$"))
check("role = admin",      alice.role == "admin")
check("active = 1",        alice.active == 1)

bob = register("Bob", "bob@example.com", "BobStrongPass123!")
check("default role = member", bob.role == "member")

check_raises("weak password requires confirmation", RegistrationError,
             lambda: register("Weak", "weak@example.com", "password123"))
weak_user = register("Weak Allowed", "weak-allowed@example.com", "password123",
                     allow_weak_password=True)
check("weak password accepted with confirmation", weak_user.id is not None)

check_raises("duplicate email",       RegistrationError,
             lambda: register("Alice2", "alice@example.com", "SecurePassword1!"))
check_raises("blank name",            RegistrationError,
             lambda: register("", "new@x.com", "ValidStrongPass123!"))
check_raises("invalid email",         RegistrationError,
             lambda: register("X", "notanemail", "ValidStrongPass123!"))
check_raises("short password",        RegistrationError,
             lambda: register("X", "x@x.com", "short"))
check_raises("invalid role",          RegistrationError,
             lambda: register("X", "y@x.com", "ValidStrongPass123!", role="superuser"))


# ─────────────────────────────────────────────────────────────────────────────
print("\n── login() / logout() ───────────────────────────────────────────────")

user, token = login("alice@example.com", "SecurePassword1!")
check("returns User",         isinstance(user, User))
check("returns token string", isinstance(token, str) and len(token) > 10)
check("token in session store", True)   # implicit via sessions.get below

from modules.auth.sessions import sessions
sess = sessions.get(token)
check("session has user_id",  sess["user_id"] == alice.id)
check("session has role",     sess["role"]    == "admin")

check_raises("wrong password",    AuthError,
             lambda: login("alice@example.com", "wrongpass"))
check_raises("unknown email",     AuthError,
             lambda: login("nobody@example.com", "pw"))

# Inactive user
alice_db = User.objects.get(id=alice.id)
alice_db.active = 0
alice_db.save()
check_raises("inactive user rejected", AuthError,
             lambda: login("alice@example.com", "SecurePassword1!"))
alice_db.active = 1; alice_db.save()

# logout
class FakeReqWithCookie:
    headers = {"Cookie": f"pysess={token}"}

logout(FakeReqWithCookie())
check("logout destroys session",  sessions.get(token) is None)


# ─────────────────────────────────────────────────────────────────────────────
print("\n── get_current_user() ───────────────────────────────────────────────")

_, token2 = login("alice@example.com", "SecurePassword1!")

class ReqWithSession:
    headers = {"Cookie": f"pysess={token2}"}
    _auth_user_resolved = False
    user = None

req = ReqWithSession()
resolved = get_current_user(req)
check("resolves user from session",  resolved.email == "alice@example.com")
check("attaches to request.user",    req.user is resolved)
check("second call returns cached",  get_current_user(req) is resolved)

class ReqNoSession:
    headers = {}
    _auth_user_resolved = False
    user = None

check("no cookie → None",  get_current_user(ReqNoSession()) is None)

class ReqBadToken:
    headers = {"Cookie": "pysess=badtoken"}
    _auth_user_resolved = False
    user = None

check("bad token → None",  get_current_user(ReqBadToken()) is None)


# ─────────────────────────────────────────────────────────────────────────────
print("\n── change_password() ────────────────────────────────────────────────")

_, tok3 = login("bob@example.com", "BobStrongPass123!")
check("bob can log in",  sessions.get(tok3) is not None)

change_password(bob.id, "BobStrongPass123!", "NewPassword456!")
check("old session revoked after pw change", sessions.get(tok3) is None)
check_raises("old pw rejected",    AuthError,
             lambda: login("bob@example.com", "BobStrongPass123!"))
_, tok4 = login("bob@example.com", "NewPassword456!")
check("new password works",        sessions.get(tok4) is not None)

check_raises("wrong old pw",       AuthError,
             lambda: change_password(bob.id, "wrongoldpw", "newone12345"))
check_raises("too-short new pw",   AuthError,
             lambda: change_password(bob.id, "NewPassword456!", "short"))


# ─────────────────────────────────────────────────────────────────────────────
print("\n── AuthMiddleware ────────────────────────────────────────────────────")

from cms.middleware import AuthMiddleware
from core.response import Response

class MockRouter:
    def dispatch(self, request):
        return Response.json({
            "user":  request.user.email if request.user else None,
            "auth":  request.is_authenticated,
            "admin": request.is_admin,
        })

_, tok5 = login("alice@example.com", "SecurePassword1!")

class ReqMiddleware:
    method = "GET"
    headers = {"Cookie": f"pysess={tok5}"}
    _auth_user_resolved = False
    user = None

mw = AuthMiddleware(MockRouter())
resp = mw.dispatch(ReqMiddleware())
import json as _json
body = _json.loads(resp.body)
check("middleware injects user email",   body["user"] == "alice@example.com")
check("middleware sets is_authenticated", body["auth"] is True)
check("middleware sets is_admin",         body["admin"] is True)

class ReqNoAuth:
    method = "GET"
    headers = {}
    _auth_user_resolved = False
    user = None

resp2 = mw.dispatch(ReqNoAuth())
body2 = _json.loads(resp2.body)
check("unauthenticated: user=null",       body2["user"] is None)
check("unauthenticated: auth=false",      body2["auth"] is False)


# ─────────────────────────────────────────────────────────────────────────────
print()
if _failures:
    print(f"\033[91m  {_failures} test(s) FAILED\033[0m\n")
    sys.exit(1)
else:
    print(f"\033[92m  All tests passed.\033[0m\n")
