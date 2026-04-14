"""
core/middleware.py – request/response middleware classes.

LoggingMiddleware
    Wraps any dispatcher and logs every request with method, path,
    status code, and elapsed time (ms).

Usage
-----
    from core.middleware import LoggingMiddleware
    from modules.auth.middleware import AuthMiddleware

    router = Router()
    stack  = LoggingMiddleware(AuthMiddleware(router))
    server = Server(stack, port=8080)
"""

from __future__ import annotations

import time
from blocks.logger import get_logger

_log = get_logger("request")


class LoggingMiddleware:
    """
    Wraps any object with a .dispatch(request) method.

    Logs every request as:
      HH:MM:SS INFO  request: GET /path → 200  [12.3ms]
    """

    def __init__(self, inner) -> None:
        self._inner = inner

    def dispatch(self, request):
        t0   = time.monotonic()
        resp = self._inner.dispatch(request)
        ms   = (time.monotonic() - t0) * 1000
        _log.request(request, resp, duration_ms=ms)
        return resp
