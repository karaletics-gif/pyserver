"""End-to-end installer tests using a small fake MySQL connector."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from core.request import Request
from database import installer
from database.orm import pool


class FakeCursor:
    def __init__(self):
        self.lastrowid = None
        self.rowcount = 1
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = params
        if sql.lstrip().upper().startswith("INSERT INTO `USERS`"):
            self.lastrowid = 1

    def fetchone(self):
        if "COUNT(*)" in self.sql.upper():
            return {"COUNT(*)": 0}
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.statements = []

    def cursor(self, **kwargs):
        cursor = FakeCursor()
        self.statements.append(cursor)
        return cursor

    def commit(self):
        pass

    def close(self):
        pass


class FakeMySQLError(Exception):
    errno = 0


def fake_connector(connect):
    connector = types.ModuleType("mysql.connector")
    connector.connect = connect
    connector.Error = FakeMySQLError
    mysql = types.ModuleType("mysql")
    mysql.connector = connector
    return {"mysql": mysql, "mysql.connector": connector}, connector


def request(method, path, form=None, cookie=None):
    headers = {}
    body = b""
    if form is not None:
        body = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if cookie:
        headers["Cookie"] = cookie
    return Request(method, path, headers, body)


class InstallerTests(unittest.TestCase):
    def test_created_first_admin_can_log_in(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "install.sqlite3")
            from database.init_db import init_db
            from modules.auth.service import login

            init_db(db_path)
            try:
                admin = installer.create_admin_user(
                    "First Admin", "Admin@Example.Test", "First-Admin-Strong-2026!"
                )
                authenticated, token = login(
                    "admin@example.test", "First-Admin-Strong-2026!"
                )
                self.assertEqual(authenticated.id, admin.id)
                self.assertEqual(authenticated.role, "admin")
                self.assertTrue(token)
            finally:
                pool.close(db_path)

    def test_database_then_admin_setup(self):
        connections = []

        def fake_connect(**kwargs):
            connection = FakeConnection()
            connections.append((kwargs, connection))
            return connection

        modules, connector = fake_connector(fake_connect)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules), \
                patch("database.init_db._verify_tables"):
            config_path = Path(directory) / "private" / "pyserver.json"
            router = installer.InstallerRouter()
            with patch.object(installer, "CONFIG_PATH", config_path):
                first = router.router.dispatch(request("GET", "/"))
                cookie = next(value for value in first._cookies if value.startswith("pyinstall=")).split(";", 1)[0]
                csrf_match = re.search(r'name="_csrf" value="([^"]+)"', first.body)
                self.assertIsNotNone(csrf_match)
                csrf = csrf_match.group(1)

                db_response = router.router.dispatch(request("POST", "/install/database", {
                    "_csrf": csrf,
                    "host": "db.example.test",
                    "port": "3307",
                    "database": "pyserver_test",
                    "db_user": "installer",
                    "db_password": "",
                }, cookie))
                self.assertEqual(db_response.status, 302)
                self.assertEqual(db_response.headers["Location"], "/install/admin")
                self.assertEqual(len(connections), 2)
                self.assertEqual(connections[0][0]["host"], "db.example.test")
                self.assertEqual(connections[1][0]["database"], "pyserver_test")

                admin_page = router.router.dispatch(request("GET", "/install/admin", cookie=cookie))
                checkbox_tag = re.search(r'<input type="checkbox" name="allow_weak_password"[^>]*>', admin_page.body).group(0)
                self.assertNotIn("checked", checkbox_tag)
                admin_csrf = re.search(r'name="_csrf" value="([^"]+)"', admin_page.body).group(1)
                weak_response = router.router.dispatch(request("POST", "/install/admin", {
                    "_csrf": admin_csrf,
                    "admin_name": "First Admin",
                    "admin_email": "admin@example.test",
                    "admin_password": "weakpass123",
                    "admin_password_confirm": "weakpass123",
                }, cookie))
                self.assertEqual(weak_response.status, 400)
                self.assertIn("at least 12 characters", weak_response.body)
                admin_csrf = re.search(r'name="_csrf" value="([^"]+)"', weak_response.body).group(1)
                done = router.router.dispatch(request("POST", "/install/admin", {
                    "_csrf": admin_csrf,
                    "admin_name": "First Admin",
                    "admin_email": "admin@example.test",
                    "admin_password": "First-Admin-Strong-2026!",
                    "admin_password_confirm": "First-Admin-Strong-2026!",
                }, cookie))
                self.assertEqual(done.status, 302)
                self.assertEqual(done.headers["Location"], "/py-admin")
                self.assertTrue(config_path.is_file())
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["database"], "pyserver_test")
                self.assertEqual(saved["user"], "installer")
                self.assertEqual(saved["password"], "")

                all_sql = "\n".join(cursor.sql for _, connection in connections for cursor in connection.statements)
                self.assertIn("CREATE TABLE IF NOT EXISTS py_users", all_sql)
                self.assertIn("CREATE TABLE IF NOT EXISTS py_post_revisions", all_sql)
                self.assertIn("INSERT INTO py_users", all_sql)
                from modules.auth.passwords import verify_password
                user_insert = next(
                    cursor for _, connection in connections for cursor in connection.statements
                    if cursor.sql.startswith("INSERT INTO py_users")
                )
                columns = re.search(r"INSERT INTO py_users \((.*?)\) VALUES", user_insert.sql).group(1)
                inserted_user = dict(zip(
                    [column.strip().strip("`") for column in columns.split(",")],
                    user_insert.params,
                ))
                self.assertEqual(inserted_user["email"], "admin@example.test")
                self.assertEqual(inserted_user["role"], "admin")
                self.assertTrue(verify_password(
                    "First-Admin-Strong-2026!", inserted_user["password"]
                ))

                admin_response = router.dispatch(request("GET", "/py-admin"))
                self.assertEqual(admin_response.status, 401)

        pool.close()

    def test_database_name_validation_does_not_connect(self):
        router = installer.InstallerRouter()
        first = router.router.dispatch(request("GET", "/"))
        cookie = next(value for value in first._cookies if value.startswith("pyinstall=")).split(";", 1)[0]
        csrf = re.search(r'name="_csrf" value="([^"]+)"', first.body).group(1)
        def unexpected_connect(**kwargs):
            raise AssertionError("connector should not be called for an invalid database name")

        modules, connector = fake_connector(unexpected_connect)
        with patch.dict(sys.modules, modules):
            response = router.router.dispatch(request("POST", "/install/database", {
                "_csrf": csrf, "host": "localhost", "port": "3306",
                "database": "bad-name; DROP DATABASE", "db_user": "admin",
                "db_password": "secret",
            }, cookie))
        self.assertEqual(response.status, 400)
        self.assertIn("database name", response.body.lower())


if __name__ == "__main__":
    unittest.main()