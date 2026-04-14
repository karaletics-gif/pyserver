"""
core/logger.py – simple structured logger (stdlib only).

Writes JSON-Lines to stdout (and optionally a file).  Each line is a
self-contained JSON object so log aggregators can parse it easily.

Usage
-----
    from core.logger import get_logger

    log = get_logger("app")
    log.info("Server started", port=8080)
    log.warning("Slow query", ms=450, table="posts")
    log.error("Unhandled exception", exc=str(e), path=request.path)

    # In request handlers:
    log.request(request, response)

    # Control log level via LOG_LEVEL env var:
    LOG_LEVEL=DEBUG python app.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any


# ── Log levels ────────────────────────────────────────────────────────────────

DEBUG    = 10
INFO     = 20
WARNING  = 30
ERROR    = 40
CRITICAL = 50

_LEVEL_NAMES = {DEBUG: "DEBUG", INFO: "INFO", WARNING: "WARNING",
                ERROR: "ERROR", CRITICAL: "CRITICAL"}

_ENV_LEVELS  = {"DEBUG": DEBUG, "INFO": INFO, "WARNING": WARNING,
                "ERROR": ERROR, "CRITICAL": CRITICAL}

_MIN_LEVEL   = _ENV_LEVELS.get(os.environ.get("LOG_LEVEL", "INFO").upper(), INFO)


# ── ANSI colour helpers (stdout only) ─────────────────────────────────────────

_COLOURS = {
    DEBUG:    "\033[36m",   # cyan
    INFO:     "\033[32m",   # green
    WARNING:  "\033[33m",   # yellow
    ERROR:    "\033[31m",   # red
    CRITICAL: "\033[35m",   # magenta
}
_RESET = "\033[0m"
_USE_COLOUR = sys.stdout.isatty()


class Logger:
    """A named logger.  Create via get_logger()."""

    def __init__(self, name: str, log_file: str | None = None) -> None:
        self.name     = name
        self._file    = open(log_file, "a", encoding="utf-8") if log_file else None

    # ── Core emit ─────────────────────────────────────────────────────────────

    def _emit(self, level: int, message: str, **fields: Any) -> None:
        if level < _MIN_LEVEL:
            return

        now   = datetime.now(timezone.utc)
        entry = {
            "ts":      now.isoformat(timespec="milliseconds"),
            "level":   _LEVEL_NAMES[level],
            "logger":  self.name,
            "message": message,
            **fields,
        }

        line = json.dumps(entry, default=str)

        # Coloured human-readable stdout
        colour = _COLOURS.get(level, "") if _USE_COLOUR else ""
        reset  = _RESET if _USE_COLOUR else ""
        ts_fmt = now.strftime("%H:%M:%S")
        lvl    = _LEVEL_NAMES[level][:4]
        extra  = "  " + "  ".join(f"{k}={v!r}" for k, v in fields.items()) if fields else ""
        print(f"  {colour}{ts_fmt} {lvl:<4}{reset}  {self.name}: {message}{extra}")

        # JSON to file if configured
        if self._file:
            self._file.write(line + "\n")
            self._file.flush()

    # ── Convenience methods ───────────────────────────────────────────────────

    def debug(self, msg: str, **kw)    -> None: self._emit(DEBUG,    msg, **kw)
    def info(self, msg: str, **kw)     -> None: self._emit(INFO,     msg, **kw)
    def warning(self, msg: str, **kw)  -> None: self._emit(WARNING,  msg, **kw)
    def error(self, msg: str, **kw)    -> None: self._emit(ERROR,     msg, **kw)
    def critical(self, msg: str, **kw) -> None: self._emit(CRITICAL,  msg, **kw)

    def exception(self, msg: str, **kw) -> None:
        """Log an error with the current exception traceback."""
        self._emit(ERROR, msg, traceback=traceback.format_exc(), **kw)

    def request(self, request, response, duration_ms: float = 0) -> None:
        """Log an HTTP request/response pair."""
        level = WARNING if response.status >= 500 else (
                INFO    if response.status <  400 else WARNING)
        self._emit(level, f"{request.method} {request.path} → {response.status}",
                   status=response.status,
                   method=request.method,
                   path=request.path,
                   ms=round(duration_ms, 1))


# ── Registry ──────────────────────────────────────────────────────────────────

_loggers: dict[str, Logger] = {}
_log_file: str | None = os.environ.get("LOG_FILE")


def get_logger(name: str) -> Logger:
    """Return (or create) the named logger."""
    if name not in _loggers:
        _loggers[name] = Logger(name, log_file=_log_file)
    return _loggers[name]


# ── Module-level convenience ──────────────────────────────────────────────────

log = get_logger("pyserver")
