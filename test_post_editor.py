"""
test_post_editor.py – end-to-end tests for post CRUD routes and theme editor.
Run with: python test_post_editor.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

os.environ["DB_PATH"] = ":memory:"
import app as _app   # single import, no reload

from modules.users.model    import User
from modules.auth.passwords import hash_password
from modules.content.models import Post, PostRevision
from modules.content.service import get_revisions
from database.orm           import QuerySet
from urllib.parse           import urlencode
from core.request           import Request
from core.response          import Response

# Ensure content tables exist
Post.create_table()
PostRevision.create_table()

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
_failures = 0

def check(label, cond, detail=""):
    global _failures
    print(f"  {PASS if cond else FAIL}  {label}" + (f"  [{detail}]" if detail else ""))
    if not cond: _failures += 1

def go(method, path, form=None, cookie=""):
    h = {}; b = b""
    if form:
        b = urlencode(form).encode()
        h["Content-Type"]   = "application/x-www-form-urlencoded"
        h["Content-Length"] = str(len(b))
    if cookie:
        h["Cookie"] = f"pysess={cookie}"
    return _app.auth.dispatch(Request(method, path, h, b))

def session_cookie(resp):
    for c in getattr(resp, "_cookies", []):
        if c.startswith("pysess=") and "Max-Age=0" not in c:
            return c.split(";")[0].replace("pysess=", "")
    return None

# ── Seed test users ───────────────────────────────────────────────────────────
editor = User.objects.create(
    name="Ed Editor", email="ed@x.com",
    password=hash_password("edpass1234"), role="editor", active=1,
)
member = User.objects.create(
    name="Mem Member", email="mem@x.com",
    password=hash_password("mempass1234"), role="member", active=1,
)
admin_u = User.objects.create(
    name="Admin User", email="adm@x.com",
    password=hash_password("admpass1234"), role="admin", active=1,
)

e_sess = session_cookie(go("POST", "/login", {"email":"ed@x.com",  "password":"edpass1234"}))
m_sess = session_cookie(go("POST", "/login", {"email":"mem@x.com", "password":"mempass1234"}))
a_sess = session_cookie(go("POST", "/login", {"email":"adm@x.com", "password":"admpass1234"}))

# ─────────────────────────────────────────────────────────────────────────────
print("\n── GET /posts/new ───────────────────────────────────────────────────")

r = go("GET", "/posts/new", cookie=e_sess)
check("editor: 200",                     r.status == 200)
check("has textarea",                    "textarea" in r.body.lower())
check("has title input",                 "title" in r.body.lower())
check("has save button",                 "save" in r.body.lower())
check("has publish button (editor)",     "publish" in r.body.lower())
check("default theme layout",            "<!DOCTYPE" in r.body)

r = go("GET", "/posts/new")
check("anon: 401",                       r.status == 401)

r = go("GET", "/posts/new", cookie=m_sess)
check("member: 403",                     r.status == 403)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── POST /posts/new (create) ─────────────────────────────────────────")

r = go("POST", "/posts/new",
       {"title": "Hello World", "body": "<p>First post</p>", "action": "save"},
       e_sess)
check("create draft → 302",              r.status == 302)
loc   = r.headers.get("Location", "")
slug1 = loc.split("/posts/")[1].split("/edit")[0]
check("redirect has slug",               bool(slug1))

# Verify in DB
from modules.content.service import get_post_by_slug
post = get_post_by_slug(slug1)
check("post saved to DB",                post.title == "Hello World")
check("status = draft",                  post.status == "draft")
check("revision = 1",                    post.revision == 1)
check("revision snapshot created",       len(get_revisions(post.id)) >= 1)

# Blank title → error
r = go("POST", "/posts/new",
       {"title": "", "body": "<p>x</p>", "action": "save"}, e_sess)
check("blank title → 200 + error",       r.status == 200)
check("error text in body",              "blank" in r.body.lower() or "required" in r.body.lower() or "title" in r.body.lower())

# Blank body → error
r = go("POST", "/posts/new",
       {"title": "T", "body": "", "action": "save"}, e_sess)
check("blank body → 200 + error",        r.status == 200)

# Create + publish in one step
r = go("POST", "/posts/new",
       {"title": "Live Post", "body": "<p>Published</p>", "action": "publish"},
       e_sess)
check("create+publish → 302",            r.status == 302)
pub_slug = r.headers.get("Location", "").split("/posts/")[1].split("/edit")[0]
pub_post = get_post_by_slug(pub_slug)
check("status = published immediately",  pub_post.status == "published")
check("published_at set",                pub_post.published_at is not None)

# Explicit slug
r = go("POST", "/posts/new",
       {"title": "Custom Slug Post", "body": "<p>x</p>",
        "slug": "my-custom-url", "action": "save"}, e_sess)
check("custom slug honoured",            r.status == 302)
custom = get_post_by_slug("my-custom-url")
check("post found by custom slug",       custom.title == "Custom Slug Post")

# ─────────────────────────────────────────────────────────────────────────────
print("\n── GET /posts/<slug>/edit ────────────────────────────────────────────")

r = go("GET", f"/posts/{slug1}/edit", cookie=e_sess)
check("edit page 200",                   r.status == 200)
check("title prefilled",                 "Hello World" in r.body)
check("body prefilled",                  "First post" in r.body)

r = go("GET", f"/posts/{slug1}/edit?saved=1", cookie=e_sess)
check("saved=1 shows flash",             "saved" in r.body.lower() or "Post saved" in r.body)

r = go("GET", f"/posts/{slug1}/edit", cookie=m_sess)
check("member can't edit: 403",          r.status == 403)

r = go("GET", "/posts/nonexistent/edit", cookie=e_sess)
check("missing post → 404",              r.status == 404)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── POST /posts/<slug>/edit (update) ─────────────────────────────────")

r = go("POST", f"/posts/{slug1}/edit",
       {"title": "Updated Title", "body": "<p>New body</p>", "action": "save"},
       e_sess)
check("update → 302",                    r.status == 302)
new_slug = r.headers.get("Location", "").split("/posts/")[1].split("/edit")[0]
updated  = get_post_by_slug(new_slug)
check("title updated",                   updated.title == "Updated Title")
check("body updated",                    "New body" in updated.body)
check("revision incremented",            updated.revision >= 2)
check("new revision snapshot saved",     len(get_revisions(updated.id)) >= 2)

# Publish via edit
r = go("POST", f"/posts/{new_slug}/edit",
       {"title": "Updated Title", "body": "<p>New body</p>", "action": "publish"},
       e_sess)
check("publish via edit → 302",          r.status == 302)
published = get_post_by_slug(new_slug)
check("status = published",              published.status == "published")
check("published_at set",                published.published_at is not None)

# Unpublish
r = go("POST", f"/posts/{new_slug}/edit",
       {"title": "Updated Title", "body": "<p>New body</p>", "action": "unpublish"},
       e_sess)
check("unpublish via edit → 302",        r.status == 302)
check("status = draft",                  get_post_by_slug(new_slug).status == "draft")

# ─────────────────────────────────────────────────────────────────────────────
print("\n── GET /posts/<slug> (public view after publish) ────────────────────")

# Publish the post
go("POST", f"/posts/{new_slug}/edit",
   {"title": "Updated Title", "body": "<p>New body</p>", "action": "publish"}, e_sess)

r = go("GET", f"/posts/{new_slug}")
check("published post: 200 for anon",    r.status == 200)
check("title shown",                     "Updated Title" in r.body)
check("body shown",                      "New body" in r.body)
check("themed with layout",              "<!DOCTYPE" in r.body)

# Draft not accessible to anon
go("POST", f"/posts/{new_slug}/edit",
   {"title": "Updated Title", "body": "<p>x</p>", "action": "unpublish"}, e_sess)
r = go("GET", f"/posts/{new_slug}")
check("draft: anon → 302 redirect",      r.status == 302)

r = go("GET", f"/posts/{new_slug}", cookie=e_sess)
check("draft: editor can view",          r.status == 200)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Revision restore ─────────────────────────────────────────────────")

# Update title (slug may change) then track the new slug
r_fin = go("POST", f"/posts/{new_slug}/edit",
           {"title": "Final Title", "body": "<p>Final</p>", "action": "save"}, e_sess)
final_slug = r_fin.headers.get("Location", f"/posts/{new_slug}/edit").split("/posts/")[1].split("/edit")[0]

revs = get_revisions(get_post_by_slug(final_slug).id)
check("multiple revisions exist",        len(revs) >= 3)

first_rev = revs[-1].revision   # oldest
r = go("POST", f"/posts/{final_slug}/restore",
       {"revision": str(first_rev)}, e_sess)
check("restore → 302",                   r.status == 302)

restored_slug = r.headers.get("Location", "").split("/posts/")[1].split("/edit")[0]
restored_post = get_post_by_slug(restored_slug)
check("content restored",                restored_post.title != "Final Title" or
                                         len(get_revisions(restored_post.id)) > len(revs))

# ─────────────────────────────────────────────────────────────────────────────
print("\n── DELETE /posts/<slug>/delete ──────────────────────────────────────")

throw_r = go("POST", "/posts/new",
             {"title": "Throwaway", "body": "<p>x</p>", "action": "save"}, e_sess)
throw_slug = throw_r.headers.get("Location","").split("/posts/")[1].split("/edit")[0]
throw_id   = get_post_by_slug(throw_slug).id

r = go("GET", f"/posts/{throw_slug}/delete", cookie=m_sess)
check("member can't delete: 403",        r.status == 403)

r = go("GET", f"/posts/{throw_slug}/delete", cookie=e_sess)
check("editor can delete → 302",         r.status == 302)
check("redirect to dashboard",           "/dashboard" in r.headers.get("Location",""))

r = go("GET", f"/posts/{throw_slug}")
check("deleted post → 404",              r.status == 404)

orphan_revs = QuerySet(PostRevision).filter(post_id=throw_id).count()
check("revisions cascade-deleted",       orphan_revs == 0)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Theme: editor renders in both themes ─────────────────────────────")

# Default theme
r = go("GET", "/posts/new", cookie=e_sess)
check("default editor: 200",             r.status == 200)
check("default editor: has textarea",    "textarea" in r.body.lower())
check("default editor: has nav",         "<header" in r.body)

# Switch to minimal
go("POST", "/admin/theme", {"theme": "minimal"}, a_sess)
r = go("GET", "/posts/new", cookie=e_sess)
check("minimal editor: 200",             r.status == 200)
check("minimal editor: has textarea",    "textarea" in r.body.lower())
check("minimal editor: serif font",      "Lora" in r.body or "serif" in r.body)

# Switch back
go("POST", "/admin/theme", {"theme": "default"}, a_sess)
check("back to default",                 _app.loader.active.slug == "default")

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Route ordering (new before slug param) ───────────────────────────")

route_patterns = [r[0].pattern for r in _app.router._routes]
new_idx  = next(i for i,p in enumerate(route_patterns) if p == "/posts/new")
slug_idx = next(i for i,p in enumerate(route_patterns) if p == r"/posts/([^/]+)")
check("/posts/new registered before /posts/<slug>", new_idx < slug_idx)

edit_idx = next(i for i,p in enumerate(route_patterns) if "edit" in p)
check("/posts/<slug>/edit before /posts/<slug>",    edit_idx < slug_idx)

# ─────────────────────────────────────────────────────────────────────────────
print()
if _failures:
    print(f"\033[91m  {_failures} test(s) FAILED\033[0m\n")
    import sys; sys.exit(1)
else:
    print(f"\033[92m  All post editor tests passed.\033[0m\n")
