"""
modules/content/models.py – Post, Page, and PostRevision models.

Schema overview
---------------
  posts
    id, title, slug, body, excerpt, author_id
    content_type   "post" | "page"
    status         "draft" | "published" | "archived"
    published_at   ISO timestamp, NULL until first publish
    meta_title     SEO override (falls back to title)
    meta_desc      SEO description
    views          integer hit counter
    revision       monotonic integer, bumped on every save
    created_at, updated_at

  post_revisions
    id, post_id, revision
    title, slug, body, excerpt, status
    changed_by     author_id who made this change
    change_note    optional free-text summary
    created_at     when this snapshot was taken
"""

from __future__ import annotations

from database.orm import Model, Field


# ─────────────────────────────────────────────────────────────────────────────
# Post  (covers both blog posts and CMS pages via content_type)
# ─────────────────────────────────────────────────────────────────────────────

class Post(Model):
    _table = "posts"

    post_author = Field("INTEGER", nullable=False, default=0, index=True)
    post_date = Field("TEXT", nullable=False, default="")
    post_date_gmt = Field("TEXT", nullable=False, default="")
    post_content = Field("TEXT", nullable=False, default="")
    post_title = Field("TEXT", nullable=False, default="")
    post_excerpt = Field("TEXT", nullable=False, default="")
    post_status = Field("TEXT", nullable=False, default="draft", index=True)
    comment_status = Field("TEXT", nullable=False, default="open")
    ping_status = Field("TEXT", nullable=False, default="open")
    post_password = Field("TEXT", nullable=False, default="")
    post_name = Field("TEXT", nullable=False, default="")
    to_ping = Field("TEXT", nullable=False, default="")
    pinged = Field("TEXT", nullable=False, default="")
    post_modified = Field("TEXT", nullable=False, default="")
    post_modified_gmt = Field("TEXT", nullable=False, default="")
    post_content_filtered = Field("TEXT", nullable=False, default="")
    guid = Field("TEXT", nullable=False, default="")
    menu_order = Field("INTEGER", nullable=False, default=0)
    post_type = Field("TEXT", nullable=False, default="post", index=True)
    post_mime_type = Field("TEXT", nullable=False, default="")
    comment_count = Field("INTEGER", nullable=False, default=0)

    # Core content
    title        = Field("TEXT",    nullable=False)
    slug         = Field("TEXT",    nullable=False, unique=True, index=True)
    body         = Field("TEXT",    nullable=False, default="")
    excerpt      = Field("TEXT",    default="")          # short teaser / summary

    # Taxonomy / ownership
    content_type = Field("TEXT",    nullable=False, default="post")   # post | page
    author_id    = Field("INTEGER", nullable=False, index=True)

    # Lifecycle
    status       = Field("TEXT",    nullable=False, default="draft", index=True)
    published_at = Field("TEXT")                                     # NULL = never published
    revision     = Field("INTEGER", nullable=False, default=1)

    # SEO
    meta_title   = Field("TEXT",    default="")
    meta_desc    = Field("TEXT",    default="")

    # Analytics
    views        = Field("INTEGER", nullable=False, default=0)

    def save(self) -> None:
        self.post_author = self.author_id or 0
        self.post_date = self.post_date or self.created_at
        self.post_date_gmt = self.post_date_gmt or self.post_date
        self.post_content = self.body
        self.post_title = self.title
        self.post_excerpt = self.excerpt or ""
        self.post_status = self.status
        self.post_name = self.slug
        self.post_modified = self.updated_at or self.post_date
        self.post_modified_gmt = self.post_modified
        self.post_type = self.content_type
        self.guid = self.guid or self.slug
        super().save()

    # ── Computed properties ───────────────────────────────────────────

    @property
    def is_published(self) -> bool:
        return self.status == "published"

    @property
    def is_draft(self) -> bool:
        return self.status == "draft"

    @property
    def is_page(self) -> bool:
        return self.content_type == "page"

    @property
    def display_title(self) -> str:
        return self.meta_title or self.title

    @property
    def display_excerpt(self) -> str:
        """Return explicit excerpt, or auto-generate from body (first 200 chars)."""
        if self.excerpt:
            return self.excerpt
        if self.body:
            text = self.body.replace("\n", " ").strip()
            return text[:200].rsplit(" ", 1)[0] + "…" if len(text) > 200 else text
        return ""

    # ── Status transitions ────────────────────────────────────────────

    def publish(self) -> None:
        from datetime import datetime
        if not self.is_published:
            self.status = "published"
            if not self.published_at:
                self.published_at = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
            self.save()

    def unpublish(self) -> None:
        if self.is_published:
            self.status = "draft"
            self.save()

    def archive(self) -> None:
        self.status = "archived"
        self.save()

    # ── Analytics ─────────────────────────────────────────────────────

    def increment_views(self) -> None:
        Post.objects.filter(id=self.id).update(views=self.views + 1)
        self.views += 1

    def __repr__(self) -> str:
        return (f"<{self.content_type.title()} id={self.id} "
                f"slug={self.slug!r} status={self.status!r}>")


# ─────────────────────────────────────────────────────────────────────────────
# Page  (thin subclass – sets content_type="page" by default)
# ─────────────────────────────────────────────────────────────────────────────

class Page(Post):
    """
    A CMS page.  Shares the posts table (single-table inheritance);
    queries are automatically scoped to content_type='page'.
    """
    _table = "posts"   # same physical table

    # ── Scoped manager ────────────────────────────────────────────────

    class _PageQuerySet:
        """Thin wrapper that pre-filters every query to content_type='page'."""
        def __init__(self, qs):
            self._qs = qs.filter(content_type="page")

        def __getattr__(self, name):
            attr = getattr(self._qs, name)
            # Chain methods that return a QuerySet should stay scoped
            if callable(attr):
                def wrapper(*a, **kw):
                    result = attr(*a, **kw)
                    # If the result is a QuerySet, re-wrap it
                    from database.orm import QuerySet
                    if isinstance(result, QuerySet):
                        return Page._PageQuerySet(result)
                    return result
                return wrapper
            return attr

    @classmethod
    def _scoped(cls):
        from database.orm import QuerySet
        return cls._PageQuerySet(QuerySet(Post).filter(content_type="page"))

    def save(self) -> None:
        self.content_type = "page"
        super().save()

    def __repr__(self) -> str:
        return f"<Page id={self.id} slug={self.slug!r} status={self.status!r}>"


# ─────────────────────────────────────────────────────────────────────────────
# PostRevision  (immutable snapshot on every meaningful change)
# ─────────────────────────────────────────────────────────────────────────────

class PostRevision(Model):
    _table = "post_revisions"

    post_id     = Field("INTEGER", nullable=False, index=True)
    revision    = Field("INTEGER", nullable=False)          # mirrors post.revision
    title       = Field("TEXT",    nullable=False)
    slug        = Field("TEXT",    nullable=False)
    body        = Field("TEXT",    nullable=False, default="")
    excerpt     = Field("TEXT",    default="")
    status      = Field("TEXT",    nullable=False)
    changed_by  = Field("INTEGER", nullable=False)          # user id
    change_note = Field("TEXT",    default="")              # e.g. "Fixed typo"

    # ── Helpers ───────────────────────────────────────────────────────

    @classmethod
    def for_post(cls, post_id: int) -> list[PostRevision]:
        """All revisions for a post, newest first."""
        from database.orm import QuerySet
        return QuerySet(cls).filter(post_id=post_id).order_by("-revision").all()

    @classmethod
    def snapshot(cls, post: Post, changed_by: int, note: str = "") -> PostRevision:
        """Create an immutable snapshot of *post* right now."""
        return cls.objects.create(
            post_id    = post.id,
            revision   = post.revision,
            title      = post.title,
            slug       = post.slug,
            body       = post.body,
            excerpt    = post.excerpt or "",
            status     = post.status,
            changed_by = changed_by,
            change_note= note,
        )

    def __repr__(self) -> str:
        return (f"<PostRevision post_id={self.post_id} "
                f"rev={self.revision} by={self.changed_by}>")
