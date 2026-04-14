"""
test_orm.py – tests and sample queries for the ORM layer.
Run with: python test_orm.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database.orm           import connect
from database.init_db       import init_db
from modules.users.model    import User
from modules.posts.model    import Post
from modules.settings.model import Setting

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
_failures = 0

def check(label: str, condition: bool, detail: str = ""):
    global _failures
    print(f"  {PASS if condition else FAIL}  {label}" + (f"  ({detail})" if detail else ""))
    if not condition:
        _failures += 1

# ── Fresh in-memory DB ────────────────────────────────────────────────────────
init_db(":memory:", seed=True)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Settings ─────────────────────────────────────────────────────────")

check("get_value shorthand",
      Setting.get_value("site_name") == "PyServer")

check("set_value upsert (new)",
      Setting.set_value("theme", "dark").value == "dark")

check("set_value upsert (existing)",
      Setting.set_value("theme", "light").value == "light" and
      Setting.get_value("theme") == "light")

check("as_bool",
      Setting.objects.get(key="maintenance").as_bool() == False)

check("as_int",
      Setting.objects.get(key="posts_per_page").as_int() == 10)

check("filter by group",
      Setting.objects.filter(group="general").count() >= 3)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── User CRUD ─────────────────────────────────────────────────────────")

# CREATE
eve = User.objects.create(
    name="Eve New", email="eve@example.com",
    password="pw_eve", role="member",
)
check("create returns instance",   isinstance(eve, User))
check("auto-assigned id",          eve.id is not None)
check("created_at set",            eve.created_at is not None)

# READ
fetched = User.objects.get(id=eve.id)
check("get by id",                 fetched.email == "eve@example.com")

all_users = User.objects.all()
check("all() returns list",        isinstance(all_users, list))
check("all() count >= 4",          len(all_users) >= 4)

# UPDATE via instance
eve.bio = "New bio"
eve.save()
check("save() updates field",      User.objects.get(id=eve.id).bio == "New bio")

# UPDATE via queryset
rows = User.objects.filter(email="eve@example.com").update(role="editor")
check("queryset update returns count", rows == 1)
check("queryset update applied",   User.objects.get(id=eve.id).role == "editor")

# DELETE
eve_id = eve.id
eve.delete()
check("delete() clears id",        eve.id is None)
check("deleted from DB",           not User.objects.filter(id=eve_id).exists())

# ─────────────────────────────────────────────────────────────────────────────
print("\n── User filters & lookups ───────────────────────────────────────────")

check("filter exact",
      User.objects.filter(role="admin").count() == 1)

check("filter __ne",
      User.objects.filter(active__ne=0).count() >= 3)

check("filter __like",
      User.objects.filter(name__like="%Admin%").first().role == "admin")

check("filter __in",
      User.objects.filter(role__in=["admin", "editor"]).count() >= 2)

check("filter active=1",
      User.objects.filter(active=1).count() >= 3)

check("filter active=0 (inactive)",
      User.objects.filter(active=0).count() >= 1)

check("exclude",
      User.objects.exclude(role="admin").filter(active=1).count() >= 2)

check("order_by ASC",
      User.objects.order_by("name").all()[0].name < User.objects.order_by("name").all()[-1].name)

check("order_by DESC",
      User.objects.order_by("-name").all()[0].name > User.objects.order_by("-name").all()[-1].name)

check("limit",
      len(User.objects.order_by("id").limit(2).all()) == 2)

check("offset",
      User.objects.order_by("id").limit(1).offset(1).all()[0].id !=
      User.objects.order_by("id").limit(1).all()[0].id)

check("values()",
      all("email" in r for r in User.objects.values("id", "email")))

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Post CRUD ─────────────────────────────────────────────────────────")

alice = User.objects.get(email="alice@example.com")

post = Post.objects.create(
    title="Test Post",
    slug="test-post",
    body="Body text.",
    author_id=alice.id,
)
check("post created",              post.id is not None)
check("default status is draft",   post.status == "draft")

post.publish()
check("publish() sets status",     Post.objects.get(id=post.id).status == "published")

post.archive()
check("archive() sets status",     Post.objects.get(id=post.id).status == "archived")

post.increment_views()
check("increment_views()",         Post.objects.get(id=post.id).views == 1)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── Post filters ─────────────────────────────────────────────────────")

check("filter published",
      Post.objects.filter(status="published").count() >= 2)

check("filter draft",
      Post.objects.filter(status="draft").count() >= 1)

check("filter by author",
      Post.objects.filter(author_id=alice.id).count() >= 2)

check("filter views__gte",
      Post.objects.filter(views__gte=50).count() >= 2)

check("order by views DESC",
      Post.objects.filter(status="published")
                  .order_by("-views")
                  .first().views >= 50)

check("count()",
      Post.objects.count() >= 4)

check("exists() true",
      Post.objects.filter(slug="hello-world").exists())

check("exists() false",
      not Post.objects.filter(slug="no-such-slug").exists())

# ─────────────────────────────────────────────────────────────────────────────
print("\n── DoesNotExist / MultipleObjectsReturned ───────────────────────────")

try:
    User.objects.get(email="nobody@nowhere.com")
    check("DoesNotExist raised", False)
except User.DoesNotExist:
    check("DoesNotExist raised", True)

try:
    User.objects.get(active=1)   # multiple active users
    check("MultipleObjectsReturned raised", False)
except User.MultipleObjectsReturned:
    check("MultipleObjectsReturned raised", True)

# ─────────────────────────────────────────────────────────────────────────────
print("\n── to_dict / repr ───────────────────────────────────────────────────")

alice = User.objects.get(email="alice@example.com")
d = alice.to_dict()
check("to_dict has keys",    set(d.keys()) >= {"id","name","email","role","active"})
check("repr format",         "User" in repr(alice) and "id=" in repr(alice))
check("model equality",      alice == User.objects.get(email="alice@example.com"))

# ─────────────────────────────────────────────────────────────────────────────
print()
if _failures:
    print(f"\033[91m  {_failures} test(s) FAILED\033[0m\n")
    sys.exit(1)
else:
    print(f"\033[92m  All tests passed.\033[0m\n")
