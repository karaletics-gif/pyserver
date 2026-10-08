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
from database.py_schema import PySchema


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

    _migrate_table_prefixes()

    if _table_exists("py_users"):
        _migrate_users()
    if _table_exists("py_posts"):
        _migrate_posts()
    if _table_exists("py_options"):
        _migrate_options()
    PySchema.migrate_existing_tables()

    # ── Create tables ──────────────────────────────────────────────────
    User.create_table()
    Post.create_table()
    PostRevision.create_table()
    Setting.create_table()
    PySchema.create_tables()
    _migrate_imported_roles()
    _verify_tables()

    if seed:
        _seed()

    print(f"  ✔  Database ready: {display_path}")


def _verify_tables() -> None:
    """Fail fast if any required table is still missing after creation."""
    models = (User, Post, PostRevision, Setting, *PySchema.TABLES)
    missing = [m._table for m in models if not _table_exists(m._table)]
    if missing:
        raise RuntimeError("Missing database tables after setup: " + ", ".join(missing))


def _table_exists(table_name: str) -> bool:
    conn = get_connection()
    if getattr(conn, "dialect", "sqlite") == "mysql":
        return conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = ?",
            (table_name,),
        ).fetchone() is not None
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _migrate_table_prefixes() -> None:
    """Rename application tables to the configured WordPress-style prefix."""
    conn = get_connection()
    dialect = getattr(conn, "dialect", "sqlite")
    names = {
        "users": "py_users", "wp_users": "py_users",
        "posts": "py_posts", "wp_posts": "py_posts",
        "post_revisions": "py_post_revisions",
        "wp_usermeta": "py_usermeta",
        "wp_postmeta": "py_postmeta",
        "wp_terms": "py_terms",
        "wp_term_taxonomy": "py_term_taxonomy",
        "wp_term_relationships": "py_term_relationships",
        "wp_comments": "py_comments",
        "wp_commentmeta": "py_commentmeta",
        "wp_links": "py_links",
        "wp_termmeta": "py_termmeta",
        "settings": "py_options", "wp_options": "py_options",
    }
    if dialect == "mysql":
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE()"
        ).fetchall()
        existing = {row["TABLE_NAME"] for row in rows}
    else:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        existing = {row["name"] for row in rows}
    for old_name, new_name in names.items():
        if old_name in existing and new_name not in existing:
            conn.execute(f"RENAME TABLE `{old_name}` TO `{new_name}`" if dialect == "mysql"
                         else f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"')
            existing.add(new_name)
    conn.commit()


def _migrate_posts() -> None:
    """Add CMS compatibility fields and backfill values from WordPress columns."""
    conn = get_connection()
    mysql = getattr(conn, "dialect", "sqlite") == "mysql"
    if mysql:
        columns = {
            row["COLUMN_NAME"]
                for row in conn.execute(
                "SELECT COLUMN_NAME FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = ?",
                ("py_posts",),
            ).fetchall()
        }
    else:
            columns = {row["name"].lower() for row in conn.execute('PRAGMA table_info("py_posts")')}
    migrations = _post_migrations(mysql)
    for name, definition in migrations.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE py_posts ADD COLUMN "{name}" {definition}')
    conn.execute(
        "UPDATE py_posts SET title = COALESCE(NULLIF(title, ''), post_title), "
        "body = COALESCE(NULLIF(body, ''), post_content), "
        "slug = COALESCE(NULLIF(slug, ''), post_name), "
        "author_id = CASE WHEN author_id = 0 THEN post_author ELSE author_id END, "
        "status = CASE COALESCE(NULLIF(status, ''), post_status) "
        "WHEN 'publish' THEN 'published' ELSE COALESCE(NULLIF(status, ''), post_status) END, "
        "excerpt = COALESCE(NULLIF(excerpt, ''), post_excerpt), "
        "content_type = COALESCE(NULLIF(content_type, ''), post_type), "
        "created_at = COALESCE(NULLIF(created_at, ''), post_date), "
           "updated_at = COALESCE(NULLIF(updated_at, ''), post_modified), "
           "id = COALESCE(id, ID)"
    )
    conn.commit()


def _post_migrations(mysql: bool) -> dict[str, str]:
    text = "LONGTEXT NULL" if mysql else "TEXT NOT NULL DEFAULT ''"
    nullable_text = "LONGTEXT NULL" if mysql else "TEXT"
    integer = "BIGINT NOT NULL DEFAULT 0" if mysql else "INTEGER NOT NULL DEFAULT 0"
    return {
        "id": "BIGINT NULL" if mysql else "INTEGER",
        "created_at": "VARCHAR(32) NULL" if mysql else "TEXT",
        "updated_at": "VARCHAR(32) NULL" if mysql else "TEXT",
        "post_author": integer,
        "post_date": "VARCHAR(32) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "post_date_gmt": "VARCHAR(32) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "post_content": text, "post_title": text, "post_excerpt": text,
        "post_status": "VARCHAR(32) NULL" if mysql else "TEXT NOT NULL DEFAULT 'draft'",
        "comment_status": "VARCHAR(20) NULL" if mysql else "TEXT NOT NULL DEFAULT 'open'",
        "ping_status": "VARCHAR(20) NULL" if mysql else "TEXT NOT NULL DEFAULT 'open'",
        "post_password": "VARCHAR(255) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "post_name": "VARCHAR(191) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "to_ping": text, "pinged": text,
        "post_modified": "VARCHAR(32) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "post_modified_gmt": "VARCHAR(32) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "post_content_filtered": text, "guid": "VARCHAR(255) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "menu_order": integer, "post_type": "VARCHAR(32) NULL" if mysql else "TEXT NOT NULL DEFAULT 'post'",
        "post_mime_type": "VARCHAR(100) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "comment_count": integer,
        "title": nullable_text, "slug": "VARCHAR(191) NULL" if mysql else "TEXT",
        "body": nullable_text, "excerpt": nullable_text,
        "content_type": "VARCHAR(32) NULL" if mysql else "TEXT",
        "author_id": integer, "status": "VARCHAR(32) NULL" if mysql else "TEXT",
        "published_at": "VARCHAR(32) NULL" if mysql else "TEXT",
        "revision": "BIGINT NOT NULL DEFAULT 1" if mysql else "INTEGER NOT NULL DEFAULT 1",
        "meta_title": text, "meta_desc": text, "views": integer,
    }


def _migrate_users() -> None:
    conn = get_connection()
    mysql = getattr(conn, "dialect", "sqlite") == "mysql"
    if mysql:
        columns = {row["COLUMN_NAME"].lower() for row in conn.execute(
            "SELECT COLUMN_NAME FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = ?", ("py_users",)
        ).fetchall()}
    else:
        columns = {row["name"].lower() for row in conn.execute('PRAGMA table_info("py_users")')}
    had_user_status = "user_status" in columns
    had_active = "active" in columns
    text = "LONGTEXT NULL" if mysql else "TEXT"
    migrations = {
        "user_login": "VARCHAR(60) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "user_pass": "VARCHAR(255) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "user_email": "VARCHAR(100) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "user_nicename": "VARCHAR(50) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "user_url": "VARCHAR(100) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "user_registered": "VARCHAR(32) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "user_activation_key": "VARCHAR(255) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "user_status": "BIGINT NOT NULL DEFAULT 0" if mysql else "INTEGER NOT NULL DEFAULT 0",
        "display_name": "VARCHAR(250) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "first_name": "VARCHAR(100) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "last_name": "VARCHAR(100) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "nickname": "VARCHAR(100) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "user_url": "VARCHAR(255) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "admin_color_scheme": "VARCHAR(32) NULL" if mysql else "TEXT NOT NULL DEFAULT 'fresh'",
        "rich_editing": "BIGINT NOT NULL DEFAULT 1" if mysql else "INTEGER NOT NULL DEFAULT 1",
        "comment_shortcuts": "BIGINT NOT NULL DEFAULT 0" if mysql else "INTEGER NOT NULL DEFAULT 0",
        "show_admin_bar_front": "BIGINT NOT NULL DEFAULT 1" if mysql else "INTEGER NOT NULL DEFAULT 1",
        "id": "BIGINT NULL" if mysql else "INTEGER",
        "created_at": "VARCHAR(32) NULL" if mysql else "TEXT",
        "updated_at": "VARCHAR(32) NULL" if mysql else "TEXT",
        "name": text, "email": "VARCHAR(191) NULL" if mysql else "TEXT",
        "password": "VARCHAR(255) NULL" if mysql else "TEXT",
        "role": "VARCHAR(32) NULL" if mysql else "TEXT",
        "bio": text, "active": "BIGINT NULL" if mysql else "INTEGER",
    }
    for name, definition in migrations.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE py_users ADD COLUMN "{name}" {definition}')
    updates = [
        "name = COALESCE(NULLIF(name, ''), display_name, user_login)",
        "email = COALESCE(NULLIF(email, ''), user_email)",
        "password = COALESCE(NULLIF(password, ''), user_pass)",
        "role = COALESCE(NULLIF(role, ''), 'member')",
        "id = COALESCE(id, ID)",
    ]
    if had_user_status and not had_active:
        updates.append("active = CASE WHEN user_status = 0 THEN 1 ELSE 0 END")
    elif had_active and not had_user_status:
        updates.append("user_status = CASE WHEN active = 1 THEN 0 ELSE 1 END")
    else:
        updates.append("active = COALESCE(active, 1)")
    conn.execute("UPDATE py_users SET " + ", ".join(updates))
    conn.commit()


def _migrate_options() -> None:
    conn = get_connection()
    mysql = getattr(conn, "dialect", "sqlite") == "mysql"
    if mysql:
        columns = {row["COLUMN_NAME"].lower() for row in conn.execute(
            "SELECT COLUMN_NAME FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = ?", ("py_options",)
        ).fetchall()}
    else:
        columns = {row["name"].lower() for row in conn.execute('PRAGMA table_info("py_options")')}
    text = "LONGTEXT NULL" if mysql else "TEXT"
    migrations = {
        "option_name": "VARCHAR(191) NULL" if mysql else "TEXT NOT NULL DEFAULT ''",
        "option_value": text,
        "autoload": "VARCHAR(20) NULL" if mysql else "TEXT NOT NULL DEFAULT 'yes'",
        "key": "VARCHAR(191) NULL" if mysql else "TEXT",
        "id": "BIGINT NULL" if mysql else "INTEGER",
        "created_at": "VARCHAR(32) NULL" if mysql else "TEXT",
        "updated_at": "VARCHAR(32) NULL" if mysql else "TEXT",
        "value": text,
        "value_type": "VARCHAR(32) NULL" if mysql else "TEXT NOT NULL DEFAULT 'string'",
        "group": "VARCHAR(64) NULL" if mysql else "TEXT NOT NULL DEFAULT 'general'",
        "label": text,
    }
    for name, definition in migrations.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE py_options ADD COLUMN "{name}" {definition}')
    conn.execute(
        "UPDATE py_options SET `key` = COALESCE(NULLIF(`key`, ''), option_name), "
        "value = COALESCE(value, option_value), "
        "value_type = COALESCE(NULLIF(value_type, ''), 'string'), "
        "`group` = COALESCE(NULLIF(`group`, ''), 'general'), "
        "id = COALESCE(id, ID)"
    )
    conn.commit()


def _migrate_imported_roles() -> None:
    """Translate serialized WordPress role capabilities to PyServer roles."""
    if not _table_exists("py_usermeta"):
        return
    conn = get_connection()
    rows = conn.execute(
        "SELECT user_id, meta_value FROM py_usermeta "
        "WHERE meta_key LIKE '%capabilities'"
    ).fetchall()
    for row in rows:
        capabilities = str(row["meta_value"] or "")
        if "administrator" in capabilities:
            role = "admin"
        elif "editor" in capabilities:
            role = "editor"
        else:
            role = "member"
        conn.execute("UPDATE py_users SET role = ? WHERE id = ?", (role, row["user_id"]))
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
