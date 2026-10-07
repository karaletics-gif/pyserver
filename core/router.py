import re
from typing import Callable
from core.request import Request
from core.response import Response


class Router:
    """
    Maps URL paths to handler functions.

    Supports:
      - Exact paths          : "/about"
      - Parametric segments  : "/user/<name>"   → handler(request, name=...)
    """

    def __init__(self):
        # Each entry: (pattern, param_names, allowed_methods, handler)
        self._routes: list[tuple] = []

    # ── Registration ─────────────────────────────────────────────────────────

    def route(self, path: str, methods: list[str] | None = None):
        """Decorator to register a route handler."""
        allowed = [m.upper() for m in (methods or ["GET"])]

        def decorator(fn: Callable):
            pattern, names = self._compile(path)
            self._routes.append((pattern, names, allowed, fn))
            return fn

        return decorator
    
    def any(self, path: str):
        return self.route(path, methods=["GET", "POST"])

    def get(self, path: str):
        return self.route(path, methods=["GET"])

    def post(self, path: str):
        return self.route(path, methods=["POST"])

    # ── Dispatch ─────────────────────────────────────────────────────────────

    def dispatch(self, request: Request) -> Response:
        path_matched = False
        for pattern, param_names, allowed_methods, handler in self._routes:
            match = pattern.fullmatch(request.path)
            if match:
                path_matched = True
                if request.method not in allowed_methods:
                    continue
                kwargs = dict(zip(param_names, match.groups()))
                try:
                    return handler(request, **kwargs)
                except Exception as exc:
                    return Response.html(
                        f"<h1>500 – Internal Server Error</h1><pre>{exc}</pre>",
                        status=500,
                    )
        return Response.method_not_allowed() if path_matched else Response.not_found()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _compile(path: str) -> tuple[re.Pattern, list[str]]:
        """Convert '/user/<name>' → regex pattern + param name list."""
        param_names: list[str] = []
        # Replace <param> with a named capture group
        def replacer(m):
            param_names.append(m.group(1))
            return r"([^/]+)"

        regex = re.sub(r"<([^>]+)>", replacer, re.escape(path).replace(r"\<", "<").replace(r"\>", ">"))
        # re.escape escapes angle brackets in some versions – undo that
        regex = path  # simpler: build from scratch
        param_names.clear()
        parts = re.split(r"(<[^>]+>)", path)
        regex_parts = []
        for part in parts:
            if part.startswith("<") and part.endswith(">"):
                param_names.append(part[1:-1])
                regex_parts.append(r"([^/]+)")
            else:
                regex_parts.append(re.escape(part))
        return re.compile("".join(regex_parts)), param_names
