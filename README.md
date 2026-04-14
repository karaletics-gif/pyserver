# 🚀 PyServer CMS (WordPress-like CMS in Pure Python)

A fully custom-built Content Management System (CMS) developed using **pure Python (no Django, no Flask)**.

This project replicates core concepts of platforms like **WordPress / Laravel / Django**, including:
- Custom web server
- Routing system
- ORM
- Authentication
- Template engine
- Theme system
- Middleware architecture

---

# 📌 Features

## 🔐 Authentication System
- User registration & login
- Session management
- Password hashing
- Role & permission support

## 🧠 Custom Core Framework
- HTTP server (built from scratch)
- Router (GET/POST handling)
- Request & Response abstraction

## 🗄️ Database Layer
- SQLite-based storage
- Custom ORM (no external libraries)
- Query abstraction

## 🎨 Template Engine
- PHP-like syntax using Python
- Dynamic rendering
- Layout support

## 🧱 Middleware System
- CSRF protection
- Logging
- Flash messages
- Theme loader

## 🎭 Theme System
- WordPress-like themes
- Default + Minimal themes
- Layout fallback (`index.html`)

## 📝 Content System
- Post model
- Revision support (optional)
- Extendable module structure

---

# 📁 Project Structure

```
pyserver/
│
├── app.py                 # Entry point
│
├── core/                  # Framework core
│   ├── server.py
│   ├── router.py
│   ├── request.py
│   └── response.py
│
├── database/              # Database layer
│   ├── orm.py
│   ├── init_db.py
│   └── pyserver.db
│
├── modules/               # Feature modules
│   ├── auth/
│   ├── posts/
│   └── api/
│
├── templates/             # HTML templates
│
├── themes/                # Theme system
│   ├── default/
│   │   ├── index.html
│   │   └── theme.py
│   └── minimal/
│
├── blocks/                # Middleware
│
├── cookie/                # Sessions & templating
│
└── change_password/       # Feature module
```

---

# ⚙️ Installation & Setup

## 1️⃣ Clone the Repository

```bash
git clone <your-repo-url>
cd pyserver
```

## 2️⃣ Ensure Python Version

```bash
python --version
```

👉 Recommended: **Python 3.10+**

## 3️⃣ Initialize Database

```bash
python -m database.init_db
```

✔ This will create:
```
pyserver.db
```

## 4️⃣ Run the Application

```bash
python app.py
```

## 5️⃣ Open in Browser

```
http://localhost:8000
```

---

# 🔗 Available Routes

| Route        | Description        |
|-------------|--------------------|
| `/`         | Homepage           |
| `/login`    | Login page         |
| `/register` | Register page      |
| `/dashboard`| User dashboard     |
| `/logout`   | Logout             |

---

# 🧠 How It Works

### 🔄 Request Flow

```
Client → Server → Router → Controller → Template → Theme → Response
```

---

### 🧩 Architecture Mapping

| PyServer        | Equivalent         |
|----------------|-------------------|
| core/server.py | Express/Django     |
| router.py      | Laravel Routes     |
| ORM            | Eloquent/Django ORM|
| templates      | Blade/Jinja        |
| modules        | Plugins/Apps       |

---

# 🎨 Theme System

Each theme must include:

```
themes/<theme-name>/
 ├── index.html   ✅ REQUIRED
 └── theme.py
```

👉 `index.html` acts as the base layout.

---

# ⚠️ Common Issues & Fixes

## ❌ ModuleNotFoundError

👉 Run modules like:

```bash
python -m database.init_db
```

---

## ❌ Theme Error

```
Theme 'default' has no index.html
```

✔ Fix:
```
themes/default/index.html must exist
```

---

## ❌ Import Issues

Ensure folders contain:

```
__init__.py
```

---

# 🧪 Testing

Run test files:

```bash
python test_auth.py
python test_orm.py
python test_template.py
```

---

# 🔥 Future Improvements

- Admin panel
- Media upload system
- Plugin system
- REST API expansion
- Caching (Redis)
- Docker support
- Deployment pipeline

---

# 💡 Learning Purpose

This project is ideal for understanding:

- How frameworks like Django/Laravel work internally
- How routing, ORM, templating, and middleware are built
- Backend architecture design

---

# 👨‍💻 Author

**Ajeet Kumar**  
Senior PHP Developer → Transitioning to Python & DevOps 🚀

---

# 📜 License

This project is open-source and available under the MIT License.

---

# ⭐ Support

If you found this useful:
- Star the repo ⭐
- Share with others
- Build on top of it 🚀
