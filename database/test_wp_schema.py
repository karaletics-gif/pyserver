"""Regression tests for py_-prefixed app and imported WordPress schemas."""

from __future__ import annotations

import os
import hashlib
import sqlite3
import tempfile
import unittest

from change_password.content.models import Post
from change_password.settings.model import Setting
from change_password.users.model import User
from database.init_db import init_db
from database.orm import QuerySet, get_connection, pool


def make_phpass(password: str) -> str:
    alphabet = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    salt = "12345678"
    count_char = alphabet[8]
    digest = hashlib.md5(salt.encode() + password.encode()).digest()
    for _ in range(1 << 8):
        digest = hashlib.md5(digest + password.encode()).digest()
    encoded = []
    index = 0
    while index < len(digest):
        value = digest[index]
        index += 1
        encoded.append(alphabet[value & 63])
        if index < len(digest):
            value |= digest[index] << 8
        encoded.append(alphabet[(value >> 6) & 63])
        if index >= len(digest):
            break
        index += 1
        if index < len(digest):
            value |= digest[index] << 16
        encoded.append(alphabet[(value >> 12) & 63])
        if index >= len(digest):
            break
        index += 1
        encoded.append(alphabet[(value >> 18) & 63])
    return "$P$" + count_char + salt + "".join(encoded)


class PrefixMigrationTests(unittest.TestCase):
    def _db_path(self):
        handle, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        os.unlink(path)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        self.addCleanup(lambda: pool.close(path))
        return path

    def test_legacy_pyserver_tables_are_renamed_and_preserved(self):
        path = self._db_path()
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, created_at TEXT, updated_at TEXT,
                name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
                role TEXT NOT NULL, bio TEXT, active INTEGER NOT NULL
            );
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY, created_at TEXT, updated_at TEXT,
                title TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, body TEXT NOT NULL,
                author_id INTEGER NOT NULL, status TEXT NOT NULL, views INTEGER NOT NULL
            );
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY, created_at TEXT, updated_at TEXT,
                key TEXT NOT NULL UNIQUE, value TEXT, value_type TEXT NOT NULL,
                "group" TEXT NOT NULL, label TEXT
            );
            INSERT INTO users VALUES (7,'2024','2024','First Admin','owner@example.test','pbkdf2$1$x$y','admin','',1);
            INSERT INTO posts VALUES (11,'2024','2024','Imported post','imported-post','Imported body',7,'published',4);
            INSERT INTO settings VALUES (3,'2024','2024','site_name','Imported Site','string','general','Site name');
        """)
        conn.commit()
        conn.close()

        init_db(path)
        self.assertEqual(QuerySet(User).get(email="owner@example.test").id, 7)
        post = QuerySet(Post).get(slug="imported-post")
        self.assertEqual((post.title, post.body, post.author_id), ("Imported post", "Imported body", 7))
        self.assertEqual(Setting.get_value("site_name"), "Imported Site")
        names = {row["name"] for row in get_connection().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("py_users", names)
        self.assertIn("py_posts", names)
        self.assertIn("py_options", names)
        self.assertNotIn("users", names)

    def test_wordpress_tables_backfill_login_and_content_aliases(self):
        path = self._db_path()
        conn = sqlite3.connect(path)
        wordpress_hash = make_phpass("WP-Admin-Strong-2026!")
        conn.executescript("""
            CREATE TABLE wp_users (
                ID INTEGER PRIMARY KEY, user_login TEXT, user_pass TEXT, user_nicename TEXT,
                user_email TEXT, user_url TEXT, user_registered TEXT, user_activation_key TEXT,
                user_status INTEGER, display_name TEXT
            );
            CREATE TABLE wp_posts (
                ID INTEGER PRIMARY KEY, post_author INTEGER, post_date TEXT, post_date_gmt TEXT,
                post_content TEXT, post_title TEXT, post_excerpt TEXT, post_status TEXT,
                comment_status TEXT, ping_status TEXT, post_password TEXT, post_name TEXT,
                to_ping TEXT, pinged TEXT, post_modified TEXT, post_modified_gmt TEXT,
                post_content_filtered TEXT, guid TEXT, menu_order INTEGER, post_type TEXT,
                post_mime_type TEXT, comment_count INTEGER
            );
            CREATE TABLE wp_options (
                ID INTEGER PRIMARY KEY, option_name TEXT UNIQUE, option_value TEXT, autoload TEXT
            );
            CREATE TABLE wp_usermeta (
                umeta_id INTEGER PRIMARY KEY, user_id INTEGER, meta_key TEXT, meta_value TEXT
            );
        """)
        conn.execute(
            "INSERT INTO wp_users VALUES (9,?,?,?,?,?,?,?,?,?)",
            ("siteowner", wordpress_hash, "siteowner", "owner@example.test", "", "2024", "", 0, "Site Owner"),
        )
        conn.execute(
            "INSERT INTO wp_posts VALUES (21,9,'2024','2024','WordPress body','WordPress title','Excerpt','publish','open','open','','wp-post','','','2024','2024','', 'https://example.test/?p=21',0,'post','',0)"
        )
        conn.execute("INSERT INTO wp_options VALUES (4,'site_name','Imported WP','yes')")
        conn.execute(
            "INSERT INTO wp_usermeta VALUES (12,9,'wp_capabilities',?)",
            ('a:1:{s:13:"administrator";b:1;}',),
        )
        conn.commit()
        conn.close()

        init_db(path)
        user = QuerySet(User).get(email="owner@example.test")
        post = QuerySet(Post).get(slug="wp-post")
        self.assertEqual((user.id, user.name, user.role, user.active), (9, "Site Owner", "admin", 1))
        self.assertEqual((post.id, post.title, post.body, post.status, post.content_type),
                         (21, "WordPress title", "WordPress body", "published", "post"))
        self.assertEqual(Setting.get_value("site_name"), "Imported WP")
        from modules.auth.service import login
        from modules.auth.passwords import needs_rehash
        logged_in_user, token = login("owner@example.test", "WP-Admin-Strong-2026!")
        self.assertEqual(logged_in_user.id, 9)
        self.assertTrue(token)
        self.assertFalse(needs_rehash(QuerySet(User).get(id=9).password))
        prefixed = {row["name"] for row in get_connection().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"py_users", "py_posts", "py_options", "py_usermeta", "py_postmeta",
                         "py_terms", "py_term_taxonomy", "py_term_relationships", "py_comments",
                         "py_commentmeta", "py_links", "py_termmeta"} <= prefixed)
        self.assertNotIn("wp_users", prefixed)


if __name__ == "__main__":
    unittest.main()
