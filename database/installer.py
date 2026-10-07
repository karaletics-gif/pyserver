"""First-run browser installer for MySQL/MariaDB deployments."""

from __future__ import annotations

import html
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

from core.request import Request
from core.response import Response
from core.router import Router


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("PYSERVER_CONFIG", BASE_DIR / "instance" / "pyserver.json"))
_DATABASE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def load_config() -> dict | None:
    if not CONFIG_PATH.is_file():
        return None
    with CONFIG_PATH.open(encoding="utf-8") as stream:
        config = json.load(stream)
    if config.get("engine") != "mysql" or "database" not in config:
        raise RuntimeError(f"Unsupported database configuration: {CONFIG_PATH}")
    return config


def _cookie(request: Request) -> str | None:
    for item in request.headers.get("Cookie", "").split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == "pyinstall":
            return value
    return None


def _layout(title: str, contents: str, error: str = "") -> str:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · PyServer setup</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#eef3f0;color:#21332f;font:16px/1.5 Segoe UI,Arial,sans-serif}}
header{{background:#174f45;color:#fff;padding:20px max(24px,calc((100vw - 980px)/2));font-weight:700}}
main{{max-width:760px;margin:44px auto;padding:0 20px}}h1{{font-size:30px;line-height:1.2;margin:0 0 10px}}h2{{font-size:18px;margin:28px 0 10px}}
.panel{{background:#fff;border:1px solid #d5dfda;padding:28px;margin-top:24px}}
label{{display:block;font-weight:600;margin:14px 0 5px}}input{{width:100%;padding:11px;border:1px solid #aebdb6;border-radius:3px;font:inherit}}
.row{{display:grid;grid-template-columns:1fr 150px;gap:14px}}button{{margin-top:22px;border:0;background:#b45134;color:white;padding:12px 18px;font:inherit;font-weight:700;cursor:pointer}}
.error{{padding:12px;background:#fff0ec;color:#912f1b;border-left:4px solid #b45134}}.hint{{color:#63746e;font-size:14px}}@media(max-width:560px){{.row{{grid-template-columns:1fr}}main{{margin:24px auto}}.panel{{padding:20px}}}}
</style></head><body><header>PyServer CMS <span style="font-weight:400">/ First-run setup</span></header>
<main><p class="hint">Step-by-step installation</p><h1>{html.escape(title)}</h1>{error_html}{contents}</main></body></html>"""


class InstallerRouter:
    """Serve setup until installed, then delegate all requests to the app."""

    def __init__(self):
        self.router = Router()
        self._tokens: dict[str, str] = {}
        self._pending: dict[str, dict] = {}
        self.router.get("/")(self.database_form)
        self.router.get("/install")(self.database_form)
        self.router.post("/install/database")(self.create_database)
        self.router.get("/install/admin")(self.admin_form)
        self.router.post("/install/admin")(self.create_admin)

    def dispatch(self, request: Request) -> Response:
        if CONFIG_PATH.is_file():
            import app
            return app.logged.dispatch(request)
        return self.router.dispatch(request)

    def _setup_session(self, request: Request) -> tuple[str, bool]:
        token = _cookie(request)
        if not token or token not in self._tokens:
            token = secrets.token_urlsafe(24)
            self._tokens[token] = secrets.token_urlsafe(32)
            return token, True
        return token, False

    def _check_csrf(self, request: Request, token: str) -> bool:
        expected = self._tokens.get(token, "")
        return bool(expected) and secrets.compare_digest(
            expected, request.form.get("_csrf", "")
        )

    def _response(self, request: Request, body: str, status: int = 200,
                  session: str | None = None) -> Response:
        if session is None:
            session, _ = self._setup_session(request)
        created = _cookie(request) != session
        response = Response.html(body, status=status)
        if created:
            response.set_cookie(
                f"pyinstall={session}; Max-Age=1800; Path=/; HttpOnly; SameSite=Lax"
            )
        return response

    def database_form(self, request: Request) -> Response:
        session, _ = self._setup_session(request)
        csrf = html.escape(self._tokens[session], quote=True)
        fields = f"""<section class="panel"><p>Connect to a MySQL or MariaDB server. The account must be allowed to create a database.</p>
<form method="post" action="/install/database"><input type="hidden" name="_csrf" value="{csrf}">
<div class="row"><div><label for="host">Database host</label><input id="host" name="host" value="127.0.0.1" required></div><div><label for="port">Port</label><input id="port" name="port" type="number" value="3306" min="1" max="65535" required></div></div>
<label for="database">Database name</label><input id="database" name="database" autocomplete="off" required>
<label for="db_user">Database username</label><input id="db_user" name="db_user" autocomplete="username" required>
<label for="db_password">Database password (optional)</label><input id="db_password" name="db_password" type="password" autocomplete="current-password">
<button type="submit">Connect and create database</button></form></section>"""
        return self._response(request, _layout("Database connection", fields), session=session)

    def create_database(self, request: Request) -> Response:
        session = _cookie(request) or ""
        if not self._check_csrf(request, session):
            return Response.html(_layout("Setup token expired", "<p>Reload the setup page and try again.</p>"), status=403)

        form = request.form
        database = form.get("database", "").strip()
        username = form.get("db_user", "").strip()
        password = form.get("db_password", "")
        host = form.get("host", "127.0.0.1").strip()
        try:
            port = int(form.get("port", "3306"))
        except ValueError:
            port = 0
        if not _DATABASE_NAME.fullmatch(database):
            return self._database_error(request, "Use a database name containing only letters, numbers, and underscores; it must begin with a letter or underscore.")
        if not username or not host or not 1 <= port <= 65535:
            return self._database_error(request, "Enter a host, valid port, and database username.")

        try:
            import mysql.connector

            connection = mysql.connector.connect(
                host=host, port=port, user=username, password=password,
                charset="utf8mb4", connection_timeout=8,
            )
            cursor = connection.cursor()
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            connection.commit()
            cursor.close()
            connection.close()

            config = {
                "engine": "mysql", "host": host, "port": port,
                "database": database, "user": username, "password": password,
            }
            from database.init_db import init_db
            init_db(config, seed=False)
            self._pending[session] = config
            return Response.redirect("/install/admin")
        except Exception as exc:
            return self._database_error(request, f"Could not connect or prepare the database: {exc}")

    def _database_error(self, request: Request, message: str) -> Response:
        session, _ = self._setup_session(request)
        csrf = html.escape(self._tokens[session], quote=True)
        fields = f"""<section class="panel"><p>Connect to a MySQL or MariaDB server. The account must be allowed to create a database.</p>
<form method="post" action="/install/database"><input type="hidden" name="_csrf" value="{csrf}">
<div class="row"><div><label>Database host</label><input name="host" value="{html.escape(request.form.get('host','127.0.0.1'), quote=True)}" required></div><div><label>Port</label><input name="port" type="number" value="{html.escape(request.form.get('port','3306'), quote=True)}" required></div></div>
<label>Database name</label><input name="database" value="{html.escape(request.form.get('database',''), quote=True)}" required>
<label>Database username</label><input name="db_user" value="{html.escape(request.form.get('db_user',''), quote=True)}" required>
<label>Database password (optional)</label><input name="db_password" type="password"><button>Retry database setup</button></form></section>"""
        return self._response(request, _layout("Database connection", fields, message), status=400, session=session)

    def admin_form(self, request: Request) -> Response:
        session, _ = self._setup_session(request)
        if session not in self._pending:
            return Response.redirect("/install")
        csrf = html.escape(self._tokens[session], quote=True)
        fields = f"""<section class="panel"><p>Database created and migrations completed. Create the first administrator account.</p>
<form method="post" action="/install/admin"><input type="hidden" name="_csrf" value="{csrf}">
<label for="admin_name">Administrator name</label><input id="admin_name" name="admin_name" autocomplete="name" required>
<label for="admin_email">Administrator email</label><input id="admin_email" name="admin_email" type="email" autocomplete="email" required>
<label for="admin_password">Administrator password</label><input id="admin_password" name="admin_password" type="password" autocomplete="new-password" minlength="12" required>
<label for="admin_password_confirm">Confirm password</label><input id="admin_password_confirm" name="admin_password_confirm" type="password" autocomplete="new-password" minlength="12" required>
<button type="submit">Create administrator and finish</button></form></section>"""
        return self._response(request, _layout("Create administrator", fields), session=session)

    def create_admin(self, request: Request) -> Response:
        session = _cookie(request) or ""
        if not self._check_csrf(request, session):
            return Response.html(_layout("Setup token expired", "<p>Reload the setup page and try again.</p>"), status=403)
        config = self._pending.get(session)
        if not config:
            return Response.redirect("/install")

        name = request.form.get("admin_name", "").strip()
        email = request.form.get("admin_email", "").strip().lower()
        password = request.form.get("admin_password", "")
        confirmation = request.form.get("admin_password_confirm", "")
        if not name or "@" not in email:
            return self._admin_error(request, session, "Enter an administrator name and valid email address.")
        if len(password) < 12:
            return self._admin_error(request, session, "Use an administrator password with at least 12 characters.")
        if password != confirmation:
            return self._admin_error(request, session, "The password confirmation does not match.")

        try:
            from change_password.users.model import User
            from database.orm import QuerySet
            from modules.auth.passwords import hash_password

            if QuerySet(User).filter(email=email).exists():
                return self._admin_error(request, session, "That email address is already registered.")
            User.objects.create(
                name=name, email=email, password=hash_password(password),
                role="admin", active=1,
            )
            self._write_config(config)
        except Exception as exc:
            return self._admin_error(request, session, f"Could not finish installation: {exc}")

        self._pending.pop(session, None)
        self._tokens.pop(session, None)
        response = Response.redirect("/py-admin")
        response.set_cookie("pyinstall=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")
        return response

    def _admin_error(self, request: Request, session: str, message: str) -> Response:
        csrf = html.escape(self._tokens.get(session, ""), quote=True)
        fields = f"""<section class="panel"><p>Database created and migrations completed. Create the first administrator account.</p>
<form method="post" action="/install/admin"><input type="hidden" name="_csrf" value="{csrf}">
<label>Administrator name</label><input name="admin_name" value="{html.escape(request.form.get('admin_name',''), quote=True)}" required>
<label>Administrator email</label><input name="admin_email" type="email" value="{html.escape(request.form.get('admin_email',''), quote=True)}" required>
<label>Administrator password</label><input name="admin_password" type="password" minlength="12" required>
<label>Confirm password</label><input name="admin_password_confirm" type="password" minlength="12" required>
<button>Create administrator and finish</button></form></section>"""
        return self._response(request, _layout("Create administrator", fields, message), status=400, session=session)

    @staticmethod
    def _write_config(config: dict) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="pyserver-", suffix=".tmp", dir=CONFIG_PATH.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(config, stream, indent=2)
                stream.write("\n")
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, CONFIG_PATH)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)