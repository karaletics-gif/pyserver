"""Central configuration: values come from the process environment, then .env."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = Path(os.environ.get("PYSERVER_ENV_FILE", BASE_DIR / ".env"))


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_env(ENV_PATH)


def get(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


HOST = get("HOST", "127.0.0.1")
PORT = get_int("PORT", 8080)
CONFIG_PATH = Path(get("PYSERVER_CONFIG", str(BASE_DIR / "instance" / "pyserver.json")))
SQLITE_PATH = get("DB_PATH") or None


def db_defaults() -> dict:
    """Database settings from the environment (may be incomplete)."""
    return {
        "engine": "mysql",
        "host": get("DB_HOST", "127.0.0.1"),
        "port": get_int("DB_PORT", 3306),
        "database": get("DB_NAME", ""),
        "user": get("DB_USER", ""),
        "password": get("DB_PASSWORD", ""),
    }


def db_config() -> dict | None:
    """Return a complete MySQL config from the environment, else None."""
    config = db_defaults()
    if config["database"] and config["user"]:
        return config
    return None
