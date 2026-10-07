"""
modules/content/slugs.py – slug generation and uniqueness enforcement.

Produces URL-safe slugs:
  "Hello World!"        → "hello-world"
  "Héllo Wörld"         → "hello-world"   (ASCII-folded)
  "  Multiple   Spaces" → "multiple-spaces"

Uniqueness is guaranteed against the posts table; collisions get a
numeric suffix:
  "hello-world"  → already taken → "hello-world-2" → "hello-world-3" …
"""

from __future__ import annotations

import re
import unicodedata


# ── Core slug transform ───────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """
    Convert arbitrary text to a lowercase, hyphen-separated URL slug.

    Steps
    -----
    1. Unicode-normalise to NFKD, then discard non-ASCII code points.
    2. Lower-case.
    3. Replace any non-alphanumeric run with a single hyphen.
    4. Strip leading/trailing hyphens.
    """
    # Normalise accented characters (é → e, ö → o, …)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")

    text = text.lower()

    # Replace anything that isn't a letter, digit, or hyphen with a hyphen
    text = re.sub(r"[^a-z0-9]+", "-", text)

    # Collapse multiple hyphens and strip edges
    text = re.sub(r"-{2,}", "-", text).strip("-")

    return text or "untitled"


# ── Unique-slug helper ────────────────────────────────────────────────────────

def unique_slug(
    title: str,
    *,
    table: str = "posts",
    exclude_id: int | None = None,
    max_length: int = 200,
) -> str:
    """
    Return a slug derived from *title* that does not already exist in *table*.

    Parameters
    ----------
    title      : source text (e.g. the post title).
    table      : DB table to check uniqueness against.
    exclude_id : primary key to ignore (for updates where the slug belongs
                 to the row being edited).
    max_length : hard cap on slug length before the numeric suffix.
    """
    from database.orm import get_connection
    from change_password.content.models import Post

    base = slugify(title)[:max_length]
    slug = base
    conn = get_connection()
    table = Post._table
    n    = 1

    while True:
        if exclude_id is not None:
            row = conn.execute(
                f'SELECT id FROM "{table}" WHERE slug = ? AND id != ?',
                [slug, exclude_id],
            ).fetchone()
        else:
            row = conn.execute(
                f'SELECT id FROM "{table}" WHERE slug = ?',
                [slug],
            ).fetchone()

        if row is None:
            return slug   # available

        n    += 1
        slug  = f"{base}-{n}"
