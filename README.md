# PyServer CMS

PyServer is a learning-oriented content management system implemented in Python without Django or Flask. It includes a small HTTP server and router, MySQL/MariaDB persistence, authentication and permissions, a template engine, themed public pages, post revisions, an admin panel, and a JSON API.

> **User documentation:** [Open the PyServer CMS User Manual](docs/USER_MANUAL.md) (the older [.docx manual](docs/PyServer_User_Manual_2026-10-08.docx) is kept for reference)

## What It Does

- Public homepage, post listing, post detail, search, and CMS page routes.
- Registration, login, password changes, server-side sessions, and role-based permissions.
- Draft and published posts, slugs, excerpts, metadata, and revision restore.
- Admin tools for site settings, theme selection, user roles, and account activation.
- Default and Minimal themes; theme templates are under `themes/`.
- JSON endpoints for health, settings, posts, and search.
- Browser-based first-run setup for database connection and administrator creation.
- WordPress-style content, user, metadata, taxonomy, comment, option, and link tables, all using the `py_` prefix.
- Additive migrations from the app's old tables and existing `wp_` tables, with source data retained.
- Apache `.htaccess` reverse proxy rules for a domain pointing at the local server.

## Requirements

- Python 3.10 or newer.
- MySQL or MariaDB server with an account allowed to create a database and use it.
- Python connector dependency installed from `requirements.txt`.

## Quick Start

### 1. Create and activate a virtual environment

Use one virtual environment per project so dependencies stay isolated. Create it once, inside the repository root:

```bash
python -m venv .venv
```

Activate it in every new terminal:

| Shell | Command |
| --- | --- |
| PowerShell | `.venv\Scripts\Activate.ps1` |
| CMD | `.venv\Scripts\activate.bat` |
| Git Bash | `source .venv/Scripts/activate` |
| Linux / macOS | `source .venv/bin/activate` |

The prompt shows `(.venv)` when active. If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once.

When you are finished, leave the environment with:

```bash
deactivate
```

Best practices: never commit `.venv` (recreate it from `requirements.txt`), install with `python -m pip` so packages go to the active environment, and delete and recreate `.venv` if it becomes inconsistent.

### 2. Install dependencies and configure

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env     # PowerShell: Copy-Item .env.example .env
```

Edit `.env` to set `HOST`, `PORT`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`. `.env` is ignored by Git; keep it private. Real environment variables override `.env`.

### 3. Start the application

```bash
python app.py
```

Open <http://localhost:8080> directly for local setup, or open your domain when Apache is proxying to the app. The first-run installer asks for the MySQL/MariaDB host, port, database name, database username, and password; the form is prefilled from `.env`, and a blank password uses `DB_PASSWORD`. The installer creates the database and every required table, then verifies that none is missing. The supplied database account must be permitted to create and use the selected database.

After the database is created and migrations complete, the installer asks for the first administrator's name, email, and password. The installer stores a PBKDF2 password hash compatible with the login service. When installation finishes, sign in at `/py-admin` (for example, `https://your-domain.example/py-admin`). The existing `/admin` URL redirects to `/py-admin`.

Strong passwords are required by default: at least 12 characters and at least three of lowercase, uppercase, numbers, and symbols. Registration, first-admin setup, and password-change forms include an unchecked confirmation checkbox that allows a password of at least 8 characters when the user explicitly accepts the risk. Imported WordPress portable phpass passwords are accepted on first login and transparently upgraded to PBKDF2.

The setup stores database connection details in `instance/pyserver.json`. This file is ignored by Git, has restrictive permissions where supported, and is denied by the supplied Apache rules. Keep it private and back it up securely.

## Apache Domain Setup

The included `.htaccess` forwards requests to `127.0.0.1:8080`. Point the Apache document root at the repository root, enable `.htaccess` overrides, and enable `mod_rewrite`, `mod_proxy`, and `mod_proxy_http`. The app binds to loopback by default so the Python server is not directly exposed. Configure TLS in Apache before using a public domain.

Start the app from the repository root:

```bash
python app.py
```

For local SQLite-only development and the test suite, set `DB_PATH` explicitly (for example, `DB_PATH=:memory:`); production first-run setup uses MySQL/MariaDB.

## Main Browser Routes

| Route | Purpose | Access |
| --- | --- | --- |
| `/` | Homepage | Public |
| `/posts` | Published post list and pagination | Public |
| `/posts/<slug>` | View a post | Public when published; signed-in users can view drafts |
| `/pages/<slug>` | View a published CMS page | Public |
| `/search?q=<term>` | Search published post titles and bodies | Public |
| `/register` | Create a member account | Public |
| `/login` | Sign in | Public |
| `/logout` | Sign out | POST form action |
| `/dashboard` | Account dashboard and recent posts | Signed-in |
| `/posts/new` | Create a post | Editor or Admin |
| `/posts/<slug>/edit` | Edit a post and review/restore revisions | Editor or Admin |
| `/py-admin` | WordPress-style admin dashboard, users, settings, and themes | Admin |
| `/py-admin/users/<id>/edit` | Edit a user's profile and admin personal options | Admin |
| `/admin` | Compatibility redirect to `/py-admin` | Any visitor |
| `/account/password` | Change the signed-in account password | Signed-in |

## Roles

| Role | Capabilities |
| --- | --- |
| Admin | Manage users, roles, settings, themes, and content |
| Editor | Create, edit, publish, and delete posts |
| Member | Sign in and use member pages; cannot edit posts |

New registrations receive the Member role. An Admin can promote a user from `/py-admin`.

## Database Tables

Application tables use the `py_` prefix. The main tables correspond to the supplied WordPress-style schema:

| Table | Purpose |
| --- | --- |
| `py_users`, `py_usermeta` | User accounts and extensible user metadata |
| `py_posts`, `py_postmeta`, `py_post_revisions` | Posts, pages, content metadata, and revision history |
| `py_terms`, `py_term_taxonomy`, `py_term_relationships`, `py_termmeta` | Categories/tags and object relationships |
| `py_comments`, `py_commentmeta` | Comments and comment metadata |
| `py_options` | Site options/settings |
| `py_links` | Link records |

The migration renames this project's legacy `users`, `posts`, `post_revisions`, and `settings` tables to their `py_` names. Existing `wp_` tables are renamed to `py_` where a target table does not already exist, then compatibility columns are added and WordPress user/post/option fields are copied into the fields used by this CMS. WordPress capability metadata maps administrator/editor users to the corresponding PyServer roles.

## JSON API

All API responses use JSON. Public read endpoints include:

| Method and path | Description |
| --- | --- |
| `GET /api/health` | Application/database health |
| `GET /api/settings` | Public site settings |
| `GET /api/posts?page=1&per_page=10` | Paginated published posts |
| `GET /api/posts/<slug>` | A post; signed-in users can view drafts |
| `GET /api/search?q=<term>` | Search published posts; query must be at least two characters |

`POST /api/posts`, `PUT` or `PATCH /api/posts/<slug>`, and `DELETE /api/posts/<slug>` require a signed-in session and the corresponding capability. The app uses its `pysess` cookie for API authentication. Unsafe requests with a session must also send a valid CSRF token in `_csrf` or `X-CSRF-Token`.

Example public request:

```bash
curl "http://localhost:8080/api/posts?page=1&per_page=10"
```

## Tests

Run from the repository root:

```bash
python -m modules.auth.test_auth
python -m modules.test_orm
python -m database.test_installer
python -m database.test_py_schema
python -m change_password.content.test_content
python -m templates.test_template
python -m templates.test_integration
python test_post_editor.py
python test_final.py
```

## Project Layout

```text
app.py                         Application entry point and route registration
core/                          HTTP request, response, router, and server
database/                      ORM, installer, WordPress schema, and migrations
modules/auth/                  Passwords, sessions, roles, and auth services
modules/api/                   JSON API routes
change_password/content/       Post models, revisions, slugs, and content service
templates/                     Internal account/admin templates and partials
themes/                        Public-facing Default and Minimal themes
blocks/                        CSRF, flash, logging, and theme loading
cookie/                        Template engine and hooks
docs/PyServer_User_Manual_2026-10-08.docx Updated end-user guide
.htaccess                      Apache reverse proxy and private-file rules
requirements.txt               MySQL/MariaDB connector dependency
```

## Current Limitations

This is a prototype and learning project, not a hardened production CMS. Sessions are held in memory and are lost when the process restarts. The built-in HTTP server does not provide TLS or production-grade concurrency. Use the Apache proxy only behind TLS, and add persistent session storage, backups, and a reviewed deployment configuration before exposing it to the public internet.
