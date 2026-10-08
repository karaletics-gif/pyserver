# PyServer CMS User Manual

This guide takes you from a fresh machine to a running site, then explains every feature in the application.

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Virtual environment](#2-virtual-environment)
3. [Configuration (.env)](#3-configuration-env)
4. [First run and installation](#4-first-run-and-installation)
5. [Starting and stopping the app](#5-starting-and-stopping-the-app)
6. [Roles and permissions](#6-roles-and-permissions)
7. [Visitor features](#7-visitor-features)
8. [Account features](#8-account-features)
9. [Editor features](#9-editor-features)
10. [Administrator features](#10-administrator-features)
11. [Themes](#11-themes)
12. [JSON API](#12-json-api)
13. [Database tables](#13-database-tables)
14. [Troubleshooting](#14-troubleshooting)
15. [Security notes](#15-security-notes)

---

## 1. Prerequisites

- Python 3.10 or newer (`python --version`).
- A MySQL or MariaDB server that is running, with an account that may create and use a database.
- The project folder (this repository).

## 2. Virtual environment

A virtual environment keeps this project's packages separate from other Python projects. Create one per project and never install packages globally.

### Create (once)

From the repository root:

| Shell | Command |
| --- | --- |
| Windows PowerShell / CMD | `python -m venv .venv` |
| Git Bash / Linux / macOS | `python -m venv .venv` |

### Activate (every new terminal)

| Shell | Command |
| --- | --- |
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows CMD | `.venv\Scripts\activate.bat` |
| Git Bash | `source .venv/Scripts/activate` |
| Linux / macOS | `source .venv/bin/activate` |

The prompt shows `(.venv)` when it is active. If PowerShell blocks the script, run once:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.

### Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Deactivate

```bash
deactivate
```

This works in every shell and returns you to the system Python. The `.venv` folder stays; activate it again whenever you return.

### Best practices

- Name the folder `.venv` and keep it inside the project; it is already ignored by Git (`venv/` is listed, add `.venv/` if your Git status shows it).
- Never commit `.venv`; recreate it from `requirements.txt` instead.
- Use `python -m pip` so packages go to the active environment.
- Re-run `pip install -r requirements.txt` after pulling changes that touch `requirements.txt`.
- To start clean, deactivate, delete `.venv`, and repeat the create/activate/install steps.
- Check you are using the right interpreter: `python -c "import sys; print(sys.prefix)"` should point to `.venv`.

## 3. Configuration (.env)

Settings live in a `.env` file in the repository root. Copy the template and edit it:

```bash
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Address the web server binds to. Keep loopback unless behind a proxy. |
| `PORT` | `8080` | Port the web server listens on. |
| `DB_HOST` | `127.0.0.1` | MySQL/MariaDB host. |
| `DB_PORT` | `3306` | MySQL/MariaDB port. |
| `DB_NAME` | `pyserver` | Database name (letters, digits, underscore; must not start with a digit). |
| `DB_USER` | none | Database username. |
| `DB_PASSWORD` | empty | Database password. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `LOG_FILE` | unset | Optional path to also write logs to a file. |
| `DB_PATH` | unset | SQLite file for local development/tests; skips MySQL and the installer. |
| `PYSERVER_CONFIG` | `instance/pyserver.json` | Where the installer stores its marker/config file. |
| `PYSERVER_ADMIN_PASSWORD` | unset | SQLite seed mode only: sets the seeded admin password. |

Real environment variables override `.env`. `.env` holds secrets and is ignored by Git; never commit it.

## 4. First run and installation

1. Activate the virtual environment and make sure `.env` is filled in.
2. Run `python app.py`.
3. Open `http://localhost:8080` (or the `HOST`/`PORT` you chose).
4. **Step 1, Database connection:** the form is prefilled from `.env`. Confirm host, port, database name and username. Leave the password blank to use `DB_PASSWORD`. Submit.
   - The installer creates the database if it does not exist and creates every required table (users, posts, revisions, options, user/post meta, terms, taxonomy, relationships, comments, comment meta, links, term meta).
   - It then verifies that all tables exist; if any is missing it stops with an error naming the table.
5. **Step 2, Administrator:** enter a name, email, and password (and confirm). Passwords need 12+ characters with at least three of lowercase, uppercase, digits, symbols. The unchecked "weaker password" box allows 8+ characters if you accept the risk.
6. On success you are redirected to `/py-admin`. Setup details are saved to `instance/pyserver.json`, which marks the app as installed.

Existing legacy tables (`users`, `posts`, `settings`) or WordPress `wp_` tables are renamed to `py_` and kept, and missing columns are added.

To re-run the installer, stop the app and delete `instance/pyserver.json` (the database itself is untouched).

## 5. Starting and stopping the app

| Action | How |
| --- | --- |
| Start | Activate `.venv`, then `python app.py` |
| Stop | Press `Ctrl+C` in the terminal |
| Debug logging | Set `LOG_LEVEL=DEBUG` in `.env` |
| Local SQLite mode | Set `DB_PATH=dev.db` in `.env` (seeds sample users and posts) |
| Leave the environment | `deactivate` |

Sessions are kept in memory, so everyone is signed out when the server restarts.

## 6. Roles and permissions

| Role | Can do |
| --- | --- |
| Admin | Everything: users, roles, settings, themes, content |
| Editor | Create, edit, publish, delete posts |
| Member | Sign in, view dashboard, change own password; cannot edit posts |

New registrations are Members. Admins promote users from `/py-admin`.

## 7. Visitor features

| Page | What it does |
| --- | --- |
| `/` | Homepage with the latest six published posts. |
| `/posts` | All published posts, paginated; page size comes from the "Posts per page" setting. Use `?page=2`. |
| `/posts/<slug>` | A single post. Published posts are public; drafts are visible only to signed-in users. Each view increments the post's view counter. |
| `/pages/<slug>` | A published CMS page (content type "page"). |
| `/search?q=term` | Searches published post titles and bodies. Needs at least two characters. |
| `/register` | Creates a Member account (name, email, password). |
| `/login` | Signs in with email and password. |

## 8. Account features

| Page | What it does |
| --- | --- |
| `/dashboard` | Your account summary and recent posts. |
| `/account/password` | Change your password: enter the current one, then a new one twice. Changing it signs out your other sessions. |
| `/logout` | Sign out (a POST button in the navigation). |

Imported WordPress password hashes work at first login and are upgraded automatically.

## 9. Editor features

Editors and admins see these actions:

| Page | What it does |
| --- | --- |
| `/posts/new` | Create a post: title, body, excerpt, slug (auto-generated from the title if blank, made unique), and status (`draft` or `published`). |
| `/posts/<slug>/edit` | Edit a post. Each save stores a revision. |
| Revision list (on the edit page) | Shows previous versions; "Restore" returns the post to that version. |
| `/posts/<slug>/delete` | Deletes a post (POST button with confirmation). |

Drafts stay hidden from visitors until published.

## 10. Administrator features

Open `/py-admin` (the old `/admin` redirects here). Sections:

- **Dashboard:** counts of posts, published, drafts, pages, users, and comments, plus recent posts and recent comments.
- **Users:**
  - Change a user's role (Admin, Editor, Member).
  - Activate or deactivate an account. Deactivating signs the user out immediately.
  - Edit profile (`/py-admin/users/<id>/edit`): first/last name, nickname, display name, email (must be unique), website, bio, admin color scheme, visual editor on/off, comment shortcuts, and admin bar on the site.
- **Settings:** site name, tagline, and posts per page.
- **Themes:** switch between installed themes; the choice is saved and applies to the public site.

### Admin login (`/py-login`)

Visiting a protected admin or editor page while signed out redirects to `/py-login?next=<page>`. After signing in you return to that page; admins default to `/py-admin`, others to `/dashboard`. Only same-site paths are accepted as `next`.

Developers can customise the login from a theme's `theme.py` (or any plugin code) using the shared hook registry (`hooks`). Full details are in `modules/auth/login_page.py`.

| Hook | Type | Purpose |
| --- | --- | --- |
| `auth.login.fields` | filter | Add, remove or reorder form fields |
| `auth.login.form_before` / `auth.login.form_after` | filter | Inject raw HTML around the fields |
| `auth.login.page_context` | filter | Change title, intro, button text |
| `auth.login.validate` | filter | Extra validation before authentication; append error strings |
| `auth.login.credentials` | filter | Modify email/password before checking |
| `auth.login.allowed` | filter | Block after credentials pass (return `False` or an error string) |
| `auth.login.error_message` | filter | Rewrite the error shown |
| `auth.login.redirect` | filter | Choose where to go after login |
| `auth.login.url` | filter | Change where anonymous users are sent |
| `auth.login.response` | filter | Adjust the final response (cookies, headers) |
| `auth.login.before` / `auth.login.after` / `auth.login.failed` | action | React to login attempts |

```python
@hooks.filter("auth.login.fields")
def add_pin(fields, request):
    return fields + [{"name": "pin", "label": "PIN", "type": "password"}]

@hooks.filter("auth.login.validate")
def check_pin(errors, form, request):
    return errors + ([] if form.get("pin") == "1234" else ["Wrong PIN."])
```

### Appearance

| Screen | URL | What it does |
| --- | --- | --- |
| Themes | `/py-admin/themes.py` | Grid of installed themes with screenshot, Activate, Delete and Customize. Only one theme is active; activating one deactivates the rest. The active theme and its parent cannot be deleted. |
| Add Theme | `/py-admin/theme-install.py` | Upload a `.zip` (extracted into `themes/`, optionally activated) or create a child theme. |
| Patterns | `/py-admin/edit.py?post_type=pattern` | Reusable content snippets. |
| Customize | `/py-admin/customize.py` | Site title, tagline, accent colour, additional CSS. |
| Widgets | `/py-admin/widgets.py` | Text or HTML widgets for the theme's widget areas (the Footer area is shown automatically). |
| Fonts, Header, Background | `/py-admin/fonts.py`, `header.py`, `background.py` | Font choices, header text and logo, background colour and image. |
| Menus | `/py-admin/nav-menus.py` | Primary and footer menus that replace the theme's default links. |
| Theme File Editor | `/py-admin/theme-editor.py` | Edit theme files; Python files are syntax-checked and the active theme reloads on save. Disable with `DISALLOW_FILE_EDIT=true`. |

**Theme zip format:** one folder (or the files directly) containing `theme.py` and `index.html`; an optional `screenshot.png` is shown in the grid. Unsafe paths, symlinks, oversized archives and existing theme names are rejected.

**Child themes:** a child theme sets `THEME_PARENT = "<parent-slug>"` in its `theme.py`. It inherits the parent's templates, partials and assets; a template with the same name in the child overrides the parent's. The child's `theme.py` runs before the parent's, so its hooks and `setdefault` context values take precedence. Only one level of parent is supported. Themes can also declare `THEME_SUPPORTS` (a set such as `{"menus", "widgets", "customize"}`) to hide unsupported screens and `THEME_WIDGET_AREAS` for their widget areas.

### Custom post types, admin menu and admin bar (developers)

From a theme's `theme.py` or any plugin code, using the shared `hooks` registry:

```python
from cms.content.post_types import register_post_type
from modules.admin.menu import menu_item, submenu_item, bar_item

register_post_type("event", label="Events", singular="Event", icon="*", menu_position=22)
# or: @hooks.filter("post_types.register") and add/modify entries in the dict

@hooks.filter("admin.menu")            # add a top-level sidebar item
def reports(items, request):
    items.append(menu_item("reports", "Reports", "/py-admin/tools.py", position=65,
                           children=[submenu_item("Overview", "/py-admin/tools.py", "all")]))
    return items

@hooks.filter("admin.submenu")         # add a sub menu to an existing item
def user_links(children, parent_key, request):
    if parent_key == "users":
        children.append(submenu_item("Invitations", "/py-admin/users.py", "invites"))
    return children

@hooks.filter("admin.bar")             # add to the top admin bar
def bar(items, request):
    items.append(bar_item("help", "Help", "/docs", align="right"))
    return items
```

A registered type gets its own menu entry, list screen (`/py-admin/edit.py?post_type=event`), editor, dashboard count, and public URL (`/content/event/<slug>`, configurable with `view_url`). The full list of type options is documented in `cms/content/post_types.py`.

## 11. Themes

Themes live in `themes/<name>/` with `index.html`, `editor.html`, `theme.py`, and an `assets/` folder served at `/themes/<name>/assets/<file>`. Bundled themes are **Default** and **Minimal**. To add one, copy a bundled theme folder, rename it, edit `theme.py` and the templates, then select it under Themes.

## 12. JSON API

| Method and path | Auth | Description |
| --- | --- | --- |
| `GET /api/health` | none | Application and database health |
| `GET /api/settings` | none | Public site settings |
| `GET /api/posts?page=1&per_page=10` | none | Paginated published posts |
| `GET /api/posts/<slug>` | none (drafts need login) | One post |
| `GET /api/search?q=term` | none | Search (2+ characters) |
| `POST /api/posts` | session + capability | Create a post |
| `PUT` / `PATCH /api/posts/<slug>` | session + capability | Update a post |
| `DELETE /api/posts/<slug>` | session + capability | Delete a post |

Write requests use the `pysess` cookie and must include a CSRF token in `_csrf` or the `X-CSRF-Token` header.

```bash
curl "http://localhost:8080/api/posts?page=1&per_page=10"
```

## 13. Database tables

All tables use the `py_` prefix and are created automatically at install and on every start (`CREATE TABLE IF NOT EXISTS`).

| Table | Purpose |
| --- | --- |
| `py_users`, `py_usermeta` | Accounts and user metadata |
| `py_posts`, `py_postmeta`, `py_post_revisions` | Posts, pages, metadata, revisions |
| `py_terms`, `py_term_taxonomy`, `py_term_relationships`, `py_termmeta` | Categories, tags, relationships |
| `py_comments`, `py_commentmeta` | Comments |
| `py_options` | Site settings |
| `py_links` | Links |

## 14. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `python` or `pip` not found | Install Python 3.10+ and reopen the terminal. |
| `ModuleNotFoundError: mysql` | Activate `.venv`, then `python -m pip install -r requirements.txt`. |
| PowerShell refuses to activate | Run the `Set-ExecutionPolicy` command from section 2. |
| "Could not connect or prepare the database" | Check the MySQL service is running and `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD` are correct. |
| "Missing database tables after setup" | The DB user lacks `CREATE` rights, or the wrong database was used. Grant privileges and rerun. |
| Port already in use | Change `PORT` in `.env` or stop the other program. |
| Signed out after restart | Expected; sessions are in memory. |
| Installer appears again | `instance/pyserver.json` is missing; complete setup again. |
| Garbled characters on Windows console | Set `PYTHONUTF8=1` before running. |

## 15. Security notes

- Keep `.env` and `instance/pyserver.json` private and out of Git.
- Use a dedicated database user with only the privileges this app needs.
- Run behind Apache (see the README) with TLS before exposing it publicly; the built-in server has no TLS.
- Use strong, unique passwords for administrators.
