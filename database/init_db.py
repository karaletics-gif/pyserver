"""
database/init_db.py – connect, migrate, and optionally seed the database.

Usage
-----
    from database.init_db import init_db
    init_db("app.db", seed=True)
"""

from __future__ import annotations

from database.orm            import connect
from change_password.users.model     import User
from modules.posts.model     import Post
from change_password.settings.model  import Setting


def init_db(path: str = ":memory:", seed: bool = False) -> None:
    """
    Open the database, create all tables, and (optionally) seed sample rows.
    Safe to call on every startup – uses IF NOT EXISTS everywhere.
    """
    connect(path)

    # ── Create tables ──────────────────────────────────────────────────
    User.create_table()
    Post.create_table()
    Setting.create_table()

    if seed:
        _seed()

    print(f"  ✔  Database ready: {path}")


def _seed() -> None:
    """Insert sample data only if the tables are empty."""

    # ── Settings ───────────────────────────────────────────────────────
    if not Setting.objects.exists():
        Setting.objects.create(key="site_name",    value="PyServer",     group="general", label="Site name")
        Setting.objects.create(key="site_tagline", value="Built with pure Python", group="general")
        Setting.objects.create(key="posts_per_page", value="10",         group="content", value_type="int")
        Setting.objects.create(key="maintenance",  value="false",        group="general", value_type="bool")
        print("    → Settings seeded")

    # ── Users ──────────────────────────────────────────────────────────
    if not User.objects.exists():
        alice = User.objects.create(
            name="Alice Admin", email="alice@example.com",
            password="hashed_pw_alice", role="admin",
            bio="Founder and lead developer.",
        )
        bob = User.objects.create(
            name="Bob Editor", email="bob@example.com",
            password="hashed_pw_bob", role="editor",
            bio="Content strategist.",
        )
        User.objects.create(
            name="Carol Member", email="carol@example.com",
            password="hashed_pw_carol", role="member",
        )
        User.objects.create(
            name="Dave Inactive", email="dave@example.com",
            password="hashed_pw_dave", role="member",
            active=0,
        )
        print("    → Users seeded")
    else:
        alice = User.objects.get(email="alice@example.com")
        bob   = User.objects.get(email="bob@example.com")

    # ── Posts ──────────────────────────────────────────────────────────
    if not Post.objects.exists():
        Post.objects.create(
            title="Hello World",
            slug="hello-world",
            body="Our first post. Welcome to PyServer!",
            author_id=alice.id,
            status="published",
            views=142,
        )
        Post.objects.create(
            title="Building a Pure-Python Web Server",
            slug="pure-python-web-server",
            body="In this post we walk through building an HTTP server from scratch…",
            author_id=alice.id,
            status="published",
            views=89,
        )
        Post.objects.create(
            title="ORM Patterns in Python",
            slug="orm-patterns-python",
            body="Active Record vs Data Mapper – which pattern suits Python best?",
            author_id=bob.id,
            status="published",
            views=57,
        )
        Post.objects.create(
            title="Draft: Template Engine Deep-Dive",
            slug="template-engine-deep-dive",
            body="Work in progress…",
            author_id=bob.id,
            status="draft",
        )
        print("    → Posts seeded")
