"""
modules/content/service.py – high-level content API.

All public functions are the recommended way to interact with posts and pages.
They handle slug generation, revision snapshotting, status transitions, and
validation in one place so callers (routes, tests, CLI) never touch the ORM
directly.

Public API
----------
  # Posts
  create_post(title, body, author_id, **kwargs)      → Post
  update_post(post_id, changed_by, **kwargs)          → Post
  get_post_by_slug(slug)                              → Post
  publish_post(post_id, published_by)                 → Post
  unpublish_post(post_id)                             → Post
  delete_post(post_id)                                → None
  list_posts(status, page, per_page, author_id)       → (posts, total)

  # Pages
  create_page(title, body, author_id, **kwargs)       → Post  (content_type='page')
  list_pages(status)                                  → list[Post]

  # Revisions
  get_revisions(post_id)                              → list[PostRevision]
  restore_revision(post_id, revision, restored_by)    → Post
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from database.orm          import QuerySet
from change_password.content.models import Post, PostRevision
from change_password.content.slugs  import unique_slug


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class ContentError(Exception):
    """Base for all content-service errors."""

class NotFoundError(ContentError):
    pass

class ValidationError(ContentError):
    pass

class SlugConflictError(ContentError):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_slug(
    title: str,
    explicit_slug: str | None,
    exclude_id: int | None = None,
) -> str:
    """Return a validated, unique slug for a post."""
    if explicit_slug:
        from change_password.content.slugs import slugify
        slug = slugify(explicit_slug)
    else:
        slug = None  # will be generated from title

    return unique_slug(
        slug or title,
        table="posts",
        exclude_id=exclude_id,
    )


def _get_post_or_raise(post_id: int, content_type: str | None = None) -> Post:
    try:
        qs = QuerySet(Post).filter(id=post_id)
        if content_type:
            qs = qs.filter(content_type=content_type)
        return qs.get(id=post_id)
    except Post.DoesNotExist:
        kind = content_type or "post/page"
        raise NotFoundError(f"No {kind} with id={post_id}.")


def _validate_status(status: str) -> None:
    valid = {"draft", "published", "archived"}
    if status not in valid:
        raise ValidationError(f"Invalid status {status!r}. Must be one of {valid}.")


def _bump_revision(post: Post, changed_by: int, note: str = "") -> None:
    """Snapshot current state, then increment the revision counter."""
    PostRevision.snapshot(post, changed_by=changed_by, note=note)
    post.revision = (post.revision or 1) + 1


# ─────────────────────────────────────────────────────────────────────────────
# Posts
# ─────────────────────────────────────────────────────────────────────────────

def create_post(
    title:     str,
    body:      str,
    author_id: int,
    *,
    slug:       str | None = None,
    excerpt:    str = "",
    status:     str = "draft",
    meta_title: str = "",
    meta_desc:  str = "",
    change_note: str = "Initial creation",
) -> Post:
    """
    Create a new blog post.

    Parameters
    ----------
    title      : required.
    body       : required.
    author_id  : required – must be an existing user id.
    slug       : optional override; auto-generated from title if omitted.
    excerpt    : short teaser; auto-derived from body if omitted.
    status     : "draft" (default) or "published".
    meta_title : SEO title override.
    meta_desc  : SEO description.
    change_note: note stored with the initial revision.
    """
    if not title.strip():
        raise ValidationError("title cannot be blank.")
    if not body.strip():
        raise ValidationError("body cannot be blank.")
    _validate_status(status)

    final_slug   = _resolve_slug(title, slug)
    published_at = (
        datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        if status == "published" else None
    )

    post = Post.objects.create(
        title        = title.strip(),
        slug         = final_slug,
        body         = body,
        excerpt      = excerpt,
        content_type = "post",
        author_id    = author_id,
        status       = status,
        published_at = published_at,
        meta_title   = meta_title,
        meta_desc    = meta_desc,
        revision     = 1,
    )

    # Store revision-1 snapshot
    PostRevision.snapshot(post, changed_by=author_id, note=change_note)
    return post


def update_post(
    post_id:    int,
    changed_by: int,
    *,
    title:      str | None = None,
    body:       str | None = None,
    slug:       str | None = None,
    excerpt:    str | None = None,
    status:     str | None = None,
    meta_title: str | None = None,
    meta_desc:  str | None = None,
    change_note: str = "",
) -> Post:
    """
    Update a post. Only supplied fields are changed.

    Snapshots the *current* state before applying updates, then bumps
    the revision counter.
    """
    post = _get_post_or_raise(post_id, content_type="post")

    if status is not None:
        _validate_status(status)

    # Snapshot before mutation
    _bump_revision(post, changed_by=changed_by, note=change_note or "Updated")

    # Apply changes
    if title is not None:
        post.title = title.strip()
    if body is not None:
        post.body  = body
    if excerpt is not None:
        post.excerpt = excerpt
    if meta_title is not None:
        post.meta_title = meta_title
    if meta_desc is not None:
        post.meta_desc  = meta_desc

    # Slug: regenerate if title changed and no explicit slug given,
    # or use the explicit slug if provided
    if slug is not None or title is not None:
        post.slug = _resolve_slug(
            title or post.title,
            slug,
            exclude_id=post.id,
        )

    if status is not None and status != post.status:
        post.status = status
        if status == "published" and not post.published_at:
            post.published_at = datetime.utcnow().isoformat(sep=" ", timespec="seconds")

    post.save()
    return post


def get_post_by_slug(slug: str) -> Post:
    """
    Fetch a single post by its slug.
    Raises NotFoundError if it doesn't exist.
    """
    try:
        return QuerySet(Post).filter(content_type="post").get(slug=slug)
    except Post.DoesNotExist:
        raise NotFoundError(f"No post with slug={slug!r}.")


def get_post_by_id(post_id: int) -> Post:
    return _get_post_or_raise(post_id, content_type="post")


def publish_post(post_id: int, published_by: int) -> Post:
    """Transition a post to 'published', recording a revision."""
    post = _get_post_or_raise(post_id)
    if post.is_published:
        return post   # idempotent
    _bump_revision(post, changed_by=published_by, note="Published")
    post.publish()
    return post


def unpublish_post(post_id: int) -> Post:
    """Revert a published post to 'draft'."""
    post = _get_post_or_raise(post_id)
    post.unpublish()
    return post


def delete_post(post_id: int) -> None:
    """
    Hard-delete a post and all its revisions.
    Raises NotFoundError if post doesn't exist.
    """
    post = _get_post_or_raise(post_id)
    QuerySet(PostRevision).filter(post_id=post_id).delete()
    post.delete()


def list_posts(
    *,
    status:    str | None = None,
    author_id: int | None = None,
    page:      int = 1,
    per_page:  int = 10,
) -> tuple[list[Post], int]:
    """
    Return (posts_on_this_page, total_count).

    Example
    -------
    posts, total = list_posts(status="published", page=2, per_page=5)
    """
    qs = QuerySet(Post).filter(content_type="post")
    if status:
        qs = qs.filter(status=status)
    if author_id:
        qs = qs.filter(author_id=author_id)

    total  = qs.count()
    offset = (page - 1) * per_page
    posts  = qs.order_by("-created_at").limit(per_page).offset(offset).all()
    return posts, total


# ─────────────────────────────────────────────────────────────────────────────
# Pages
# ─────────────────────────────────────────────────────────────────────────────

def create_page(
    title:     str,
    body:      str,
    author_id: int,
    *,
    slug:       str | None = None,
    status:     str = "draft",
    meta_title: str = "",
    meta_desc:  str = "",
) -> Post:
    """Create a CMS page (content_type='page')."""
    if not title.strip():
        raise ValidationError("title cannot be blank.")
    _validate_status(status)

    final_slug   = _resolve_slug(title, slug)
    published_at = (
        datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        if status == "published" else None
    )

    page = Post.objects.create(
        title        = title.strip(),
        slug         = final_slug,
        body         = body,
        excerpt      = "",
        content_type = "page",
        author_id    = author_id,
        status       = status,
        published_at = published_at,
        meta_title   = meta_title,
        meta_desc    = meta_desc,
        revision     = 1,
    )
    PostRevision.snapshot(page, changed_by=author_id, note="Page created")
    return page


def get_page_by_slug(slug: str) -> Post:
    try:
        return QuerySet(Post).filter(content_type="page").get(slug=slug)
    except Post.DoesNotExist:
        raise NotFoundError(f"No page with slug={slug!r}.")


def list_pages(*, status: str | None = None) -> list[Post]:
    qs = QuerySet(Post).filter(content_type="page")
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("title").all()


# ─────────────────────────────────────────────────────────────────────────────
# Revisions
# ─────────────────────────────────────────────────────────────────────────────

def get_revisions(post_id: int) -> list[PostRevision]:
    """All revisions for a post, newest first."""
    return PostRevision.for_post(post_id)


def restore_revision(
    post_id:     int,
    revision_no: int,
    restored_by: int,
) -> Post:
    """
    Overwrite the live post with the content from a historical revision.

    The current state is snapshotted before the restore, so nothing is lost.
    """
    post = _get_post_or_raise(post_id)

    try:
        rev = (
            QuerySet(PostRevision)
            .filter(post_id=post_id, revision=revision_no)
            .order_by("id")        # earliest snapshot for that revision number
            .all()
        )
        if not rev:
            raise PostRevision.DoesNotExist()
        rev = rev[0]
    except PostRevision.DoesNotExist:
        raise NotFoundError(
            f"Revision {revision_no} not found for post id={post_id}."
        )

    # Snapshot current state before overwriting
    _bump_revision(
        post,
        changed_by=restored_by,
        note=f"Pre-restore snapshot (restoring to rev {revision_no})",
    )

    post.title   = rev.title
    post.body    = rev.body
    post.excerpt = rev.excerpt
    post.slug    = _resolve_slug(rev.slug, rev.slug, exclude_id=post.id)
    post.save()

    PostRevision.snapshot(
        post,
        changed_by=restored_by,
        note=f"Restored from revision {revision_no}",
    )
    return post
