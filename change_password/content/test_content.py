"""
test_content.py – tests for the content system (models + service API).
Run with: python test_content.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database.orm           import connect
from modules.content.models import Post, PostRevision
from modules.content.slugs  import slugify, unique_slug
from modules.content.service import (
    create_post, update_post, get_post_by_slug,
    publish_post, unpublish_post, delete_post, list_posts,
    create_page, get_page_by_slug, list_pages,
    get_revisions, restore_revision,
    NotFoundError, ValidationError,
)

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
_failures = 0

def check(label: str, condition: bool, detail: str = ""):
    global _failures
    mark = PASS if condition else FAIL
    print(f"  {mark}  {label}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        _failures += 1

def check_raises(label: str, exc_type, fn):
    global _failures
    try:
        fn()
        print(f"  {FAIL}  {label}  (no exception raised)")
        _failures += 1
    except exc_type as e:
        print(f"  {PASS}  {label}  [{e}]")
    except Exception as e:
        print(f"  {FAIL}  {label}  (wrong exception {type(e).__name__}: {e})")
        _failures += 1

# ── Bootstrap ─────────────────────────────────────────────────────────────────
connect(":memory:")
Post.create_table()
PostRevision.create_table()

AUTHOR = 1   # pretend user id


# ─────────────────────────────────────────────────────────────────────────────
print("\n── slugify() ────────────────────────────────────────────────────────")

check("basic",             slugify("Hello World")          == "hello-world")
check("punctuation",       slugify("Hello, World!")        == "hello-world")
check("accents",           slugify("Héllo Wörld")          == "hello-world")
check("extra spaces",      slugify("  Too   Many  Spaces") == "too-many-spaces")
check("numbers",           slugify("Python 3.12 Release")  == "python-3-12-release")
check("all special",       slugify("!@#$%")                == "untitled")
check("already a slug",    slugify("already-a-slug")       == "already-a-slug")
check("mixed case",        slugify("CamelCaseTitle")       == "camelcasetitle")


# ─────────────────────────────────────────────────────────────────────────────
print("\n── create_post() ────────────────────────────────────────────────────")

p1 = create_post("First Post", "Body of first post.", AUTHOR)
check("returns Post",        isinstance(p1, Post))
check("id assigned",         p1.id is not None)
check("slug generated",      p1.slug == "first-post")
check("status = draft",      p1.status == "draft")
check("content_type = post", p1.content_type == "post")
check("revision = 1",        p1.revision == 1)
check("published_at = None", p1.published_at is None)
check("created_at set",      p1.created_at is not None)

# Auto-excerpt
long_body = "Word " * 60
p_long = create_post("Long Post", long_body, AUTHOR)
check("auto-excerpt truncates",  len(p_long.display_excerpt) <= 210)
check("auto-excerpt ends in …",  p_long.display_excerpt.endswith("…"))

# Explicit slug
p2 = create_post("Second Post", "Body.", AUTHOR, slug="my-custom-slug")
check("explicit slug honoured",  p2.slug == "my-custom-slug")

# Slug collision → numeric suffix
p3 = create_post("First Post", "Dupe title.", AUTHOR)
check("collision → suffix",      p3.slug == "first-post-2")

p4 = create_post("First Post", "Another dupe.", AUTHOR)
check("second collision",        p4.slug == "first-post-3")

# Publish on creation
p_pub = create_post("Live Post", "Body.", AUTHOR, status="published")
check("published at creation",   p_pub.is_published)
check("published_at set",        p_pub.published_at is not None)

# Validation
check_raises("blank title raises",   ValidationError,
             lambda: create_post("", "body", AUTHOR))
check_raises("blank body raises",    ValidationError,
             lambda: create_post("Title", "", AUTHOR))
check_raises("bad status raises",    ValidationError,
             lambda: create_post("T", "b", AUTHOR, status="typo"))


# ─────────────────────────────────────────────────────────────────────────────
print("\n── Revision created on create_post() ───────────────────────────────")

revs = get_revisions(p1.id)
check("one revision after create",  len(revs) == 1)
check("rev.revision == 1",          revs[0].revision == 1)
check("rev.title matches",          revs[0].title == "First Post")
check("rev.changed_by == author",   revs[0].changed_by == AUTHOR)
check("rev.change_note set",        revs[0].change_note == "Initial creation")


# ─────────────────────────────────────────────────────────────────────────────
print("\n── update_post() ────────────────────────────────────────────────────")

p1 = update_post(p1.id, AUTHOR, title="First Post (Edited)", change_note="Title fix")
check("title updated",       p1.title == "First Post (Edited)")
check("slug updated",        "first-post-edited" in p1.slug)
check("revision bumped",     p1.revision == 2)

p1 = update_post(p1.id, AUTHOR, body="New body text.")
check("body updated",        p1.body == "New body text.")

p1 = update_post(p1.id, AUTHOR, status="published")
check("status to published", p1.is_published)
check("published_at set",    p1.published_at is not None)

p1 = update_post(p1.id, AUTHOR, slug="override-slug")
check("explicit slug set",   p1.slug == "override-slug")

# Revision history grows
revs = get_revisions(p1.id)
check(f"revisions after 4 updates: {len(revs)}", len(revs) >= 4)


# ─────────────────────────────────────────────────────────────────────────────
print("\n── get_post_by_slug() ───────────────────────────────────────────────")

found = get_post_by_slug("override-slug")
check("found by slug",       found.id == p1.id)

check_raises("not found raises",  NotFoundError,
             lambda: get_post_by_slug("does-not-exist"))


# ─────────────────────────────────────────────────────────────────────────────
print("\n── publish / unpublish ──────────────────────────────────────────────")

draft = create_post("Draft Post", "body", AUTHOR)
check("starts draft",           draft.is_draft)

draft = publish_post(draft.id, AUTHOR)
check("publish_post()",         draft.is_published)
check("published_at populated", draft.published_at is not None)

draft = unpublish_post(draft.id)
check("unpublish_post()",       draft.is_draft)

# publish_post is idempotent
already_pub = create_post("Already Live", "body", AUTHOR, status="published")
same = publish_post(already_pub.id, AUTHOR)
check("publish idempotent",     same.is_published)


# ─────────────────────────────────────────────────────────────────────────────
print("\n── list_posts() ─────────────────────────────────────────────────────")

posts, total = list_posts()
check("returns tuple",           isinstance(posts, list) and isinstance(total, int))
check("total >= created posts",  total >= 5)

pub_posts, pub_total = list_posts(status="published")
check("filter by published",     all(p.is_published for p in pub_posts))

author_posts, _ = list_posts(author_id=AUTHOR)
check("filter by author",        all(p.author_id == AUTHOR for p in author_posts))

page1, t1 = list_posts(page=1, per_page=2)
page2, _  = list_posts(page=2, per_page=2)
check("pagination: 2 per page",  len(page1) == 2)
check("pagination: page 2 differs", page1[0].id != page2[0].id)


# ─────────────────────────────────────────────────────────────────────────────
print("\n── delete_post() ────────────────────────────────────────────────────")

throwaway = create_post("Delete Me", "body", AUTHOR)
tid = throwaway.id
rev_count_before = len(get_revisions(tid))
check("revisions exist before delete", rev_count_before >= 1)

delete_post(tid)
check_raises("deleted post not found", NotFoundError,
             lambda: get_post_by_slug(throwaway.slug))

# Revisions should also be gone
from database.orm import QuerySet
orphan_revs = QuerySet(PostRevision).filter(post_id=tid).count()
check("revisions cascade-deleted", orphan_revs == 0)


# ─────────────────────────────────────────────────────────────────────────────
print("\n── restore_revision() ───────────────────────────────────────────────")

target = create_post("Original Title", "Original body.", AUTHOR)
update_post(target.id, AUTHOR, title="Mutated Title", body="Mutated body.")
update_post(target.id, AUTHOR, title="Mutated Again",  body="Mutated body v2.")

target_revs = get_revisions(target.id)
check("3+ revisions before restore", len(target_revs) >= 3)

# Restore to revision 1
restored = restore_revision(target.id, revision_no=1, restored_by=AUTHOR)
check("title restored",   restored.title == "Original Title")
check("body restored",    restored.body  == "Original body.")

# Revision history still grows (pre-restore snapshot + restore note)
after_revs = get_revisions(restored.id)
check("history preserved after restore", len(after_revs) > len(target_revs))

check_raises("restore missing revision raises", NotFoundError,
             lambda: restore_revision(target.id, revision_no=999, restored_by=AUTHOR))


# ─────────────────────────────────────────────────────────────────────────────
print("\n── Pages ────────────────────────────────────────────────────────────")

about = create_page("About Us", "<h1>About</h1>", AUTHOR)
check("page created",              isinstance(about, Post))
check("content_type = page",       about.content_type == "page")
check("page slug generated",       about.slug == "about-us")
check("page status = draft",       about.status == "draft")

contact = create_page("Contact", "Contact body.", AUTHOR, status="published")
check("page published at creation", contact.is_published)

found_page = get_page_by_slug("about-us")
check("get_page_by_slug",           found_page.id == about.id)

check_raises("page slug not in post lookup", NotFoundError,
             lambda: get_post_by_slug("about-us"))

all_pages = list_pages()
check("list_pages() works",         len(all_pages) >= 2)
check("list_pages only pages",      all(p.content_type == "page" for p in all_pages))

pub_pages = list_pages(status="published")
check("list_pages filtered",        all(p.is_published for p in pub_pages))


# ─────────────────────────────────────────────────────────────────────────────
print("\n── display_excerpt ──────────────────────────────────────────────────")

p_ex = create_post("Excerpt Test", "Short body.", AUTHOR, excerpt="Custom teaser.")
check("explicit excerpt used",     p_ex.display_excerpt == "Custom teaser.")

p_no_ex = create_post("No Excerpt", "Body with enough words to check truncation " * 5, AUTHOR)
check("auto-excerpt generated",    len(p_no_ex.display_excerpt) > 0)
check("auto-excerpt ≤ 210 chars",  len(p_no_ex.display_excerpt) <= 210)


# ─────────────────────────────────────────────────────────────────────────────
print()
if _failures:
    print(f"\033[91m  {_failures} test(s) FAILED\033[0m\n")
    sys.exit(1)
else:
    print(f"\033[92m  All {60 + 8} tests passed.\033[0m\n")
