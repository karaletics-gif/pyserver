"""
database/init_db.py – connect, migrate, and optionally seed the database.

Usage
-----
    from database.init_db import init_db
    init_db("app.db", seed=True)
"""

from __future__ import annotations

import os

from database.orm import connect, connect_mysql, get_connection
from change_password.users.model import User
from change_password.content.models import Post, PostRevision
from change_password.settings.model import Setting
from modules.auth.passwords import hash_password


def init_db(path: str | dict = ":memory:", seed: bool = False) -> None:
    """
    Open the database, create all tables, and (optionally) seed sample rows.
    Safe to call on every startup – uses IF NOT EXISTS everywhere.
    """
    if isinstance(path, dict):
        connect_mysql(path)
        display_path = "mysql://{}:{}/{}".format(
            path.get("host", "127.0.0.1"), path.get("port", 3306), path["database"]
        )
    else:
        connect(path)
        display_path = path

    # ── Create tables ──────────────────────────────────────────────────
    User.create_table()
    Post.create_table()
    _migrate_posts()
    PostRevision.create_table()
    Setting.create_table()

    if seed:
        _seed()

    print(f"  ✔  Database ready: {display_path}")


def _migrate_posts() -> None:
    """Add content-system columns when opening a database from the legacy model."""
    conn = get_connection()
    if getattr(conn, "dialect", "sqlite") == "mysql":
        columns = {
            row["COLUMN_NAME"]
            for row in conn.execute(
                "SELECT COLUMN_NAME FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = ?",
                ("posts",),
            ).fetchall()
        }
    else:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(posts)")}
    if getattr(conn, "dialect", "sqlite") == "mysql":
        migrations = {
            "excerpt": "LONGTEXT NULL",
            "content_type": "VARCHAR(16) NOT NULL DEFAULT 'post'",
            "published_at": "VARCHAR(32) NULL",
            "revision": "BIGINT NOT NULL DEFAULT 1",
            "meta_title": "LONGTEXT NULL",
            "meta_desc": "LONGTEXT NULL",
        }
    else:
        migrations = {
            "excerpt": "TEXT NOT NULL DEFAULT ''",
            "content_type": "TEXT NOT NULL DEFAULT 'post'",
            "published_at": "TEXT",
            "revision": "INTEGER NOT NULL DEFAULT 1",
            "meta_title": "TEXT NOT NULL DEFAULT ''",
            "meta_desc": "TEXT NOT NULL DEFAULT ''",
        }
    for name, definition in migrations.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE posts ADD COLUMN "{name}" {definition}')
    conn.commit()


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
            password=hash_password(os.urandom(32).hex()), role="admin",
            bio="Founder and lead developer.",
        )
        bob = User.objects.create(
            name="Bob Editor", email="bob@example.com",
            password=hash_password(os.urandom(32).hex()), role="editor",
            bio="Content strategist.",
        )
        User.objects.create(
            name="Carol Member", email="carol@example.com",
            password=hash_password(os.urandom(32).hex()), role="member",
        )
        User.objects.create(
            name="Dave Inactive", email="dave@example.com",
            password=hash_password(os.urandom(32).hex()), role="member",
            active=0,
        )
        print("    → Users seeded")
    else:
        try:
            alice = User.objects.get(email="alice@example.com")
        except User.DoesNotExist:
            alice = User.objects.create(
                name="Alice Admin", email="alice@example.com",
                password=hash_password(os.urandom(32).hex()), role="admin",
                bio="Founder and lead developer.",
            )
        try:
            bob = User.objects.get(email="bob@example.com")
        except User.DoesNotExist:
            bob = User.objects.create(
                name="Bob Editor", email="bob@example.com",
                password=hash_password(os.urandom(32).hex()), role="editor",
                bio="Content strategist.",
            )

    admin_password = os.environ.get("PYSERVER_ADMIN_PASSWORD")
    if admin_password:
        alice.password = hash_password(admin_password)
        alice.save()

    # ── Posts ──────────────────────────────────────────────────────────
    if not Post.objects.exists():
        from change_password.content.service import create_post

        for title, body, author_id, slug, views in (
            ("Hello World", "Our first post. Welcome to PyServer!",
             alice.id, "hello-world", 142),
            ("Building a Pure-Python Web Server",
             "In this post we walk through building an HTTP server from scratch…",
             alice.id, "pure-python-web-server", 89),
            ("ORM Patterns in Python",
             "Active Record vs Data Mapper – which pattern suits Python best?",
             bob.id, "orm-patterns-python", 57),
        ):
            post = create_post(title, body, author_id, status="published", slug=slug)
            post.views = views
            post.save()
        create_post("Draft: Template Engine Deep-Dive", "Work in progress…",
                    bob.id, status="draft", slug="template-engine-deep-dive")
        print("    → Posts seeded")
