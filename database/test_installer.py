"""End-to-end installer tests using a small fake MySQL connector."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import mysql.connector

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
    def test_database_then_admin_setup(self):
        connections = []

        def fake_connect(**kwargs):
            connection = FakeConnection()
            connections.append((kwargs, connection))
            return connection

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "private" / "pyserver.json"
            router = installer.InstallerRouter()
            with patch.object(installer, "CONFIG_PATH", config_path), patch.object(
                mysql.connector, "connect", side_effect=fake_connect
            ):
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
                admin_csrf = re.search(r'name="_csrf" value="([^"]+)"', admin_page.body).group(1)
                done = router.router.dispatch(request("POST", "/install/admin", {
                    "_csrf": admin_csrf,
                    "admin_name": "First Admin",
                    "admin_email": "admin@example.test",
                    "admin_password": "long-and-private-password",
                    "admin_password_confirm": "long-and-private-password",
                }, cookie))
                self.assertEqual(done.status, 302)
                self.assertEqual(done.headers["Location"], "/py-admin")
                self.assertTrue(config_path.is_file())
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["database"], "pyserver_test")
                self.assertEqual(saved["user"], "installer")
                self.assertEqual(saved["password"], "")

                all_sql = "\n".join(cursor.sql for _, connection in connections for cursor in connection.statements)
                self.assertIn("CREATE TABLE IF NOT EXISTS users", all_sql)
                self.assertIn("CREATE TABLE IF NOT EXISTS post_revisions", all_sql)
                self.assertIn("INSERT INTO users", all_sql)

                admin_response = router.dispatch(request("GET", "/py-admin"))
                self.assertEqual(admin_response.status, 401)

        pool.close()

    def test_database_name_validation_does_not_connect(self):
        router = installer.InstallerRouter()
        first = router.router.dispatch(request("GET", "/"))
        cookie = next(value for value in first._cookies if value.startswith("pyinstall=")).split(";", 1)[0]
        csrf = re.search(r'name="_csrf" value="([^"]+)"', first.body).group(1)
        with patch.object(mysql.connector, "connect") as connect_mock:
            response = router.router.dispatch(request("POST", "/install/database", {
                "_csrf": csrf, "host": "localhost", "port": "3306",
                "database": "bad-name; DROP DATABASE", "db_user": "admin",
                "db_password": "secret",
            }, cookie))
        self.assertEqual(response.status, 400)
        self.assertIn("database name", response.body.lower())
        connect_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()