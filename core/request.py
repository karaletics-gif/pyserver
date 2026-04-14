import json
from urllib.parse import unquote_plus


class Request:
    """Represents an incoming HTTP request."""

    def __init__(self, method: str, path: str, headers: dict, body: bytes = b""):
        self.method       = method.upper()
        self.path         = self._strip_query(path)
        self.query_string = self._parse_query(path)
        self.headers      = headers
        self.body         = body

        # Auth middleware injects these
        self.user             = None
        self.is_authenticated = False
        self.is_admin         = False

        # Parsed lazily
        self._form:   dict | None = None
        self._json:   object      = _MISSING

    # ── Query string ─────────────────────────────────────────────────────────

    def _strip_query(self, path: str) -> str:
        return path.split("?")[0]

    def _parse_query(self, path: str) -> dict:
        if "?" not in path:
            return {}
        qs     = path.split("?", 1)[1]
        params = {}
        for pair in qs.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[unquote_plus(k)] = unquote_plus(v)
        return params

    # ── POST form data ────────────────────────────────────────────────────────

    @property
    def form(self) -> dict:
        """
        Parse application/x-www-form-urlencoded body.
        Returns an empty dict for other content types.
        """
        if self._form is None:
            ct = self.headers.get("Content-Type", "")
            if "application/x-www-form-urlencoded" in ct and self.body:
                self._form = {}
                for pair in self.body.decode("utf-8", errors="replace").split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        self._form[unquote_plus(k)] = unquote_plus(v)
            else:
                self._form = {}
        return self._form

    # ── JSON body ─────────────────────────────────────────────────────────────

    @property
    def json(self):
        """Parse application/json body. Returns None on failure."""
        if self._json is _MISSING:
            try:
                self._json = json.loads(self.body) if self.body else None
            except (ValueError, TypeError):
                self._json = None
        return self._json

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get(self, key: str, default: str = "") -> str:
        """Try form → query string → default."""
        return self.form.get(key) or self.query_string.get(key, default)

    def __repr__(self):
        return f"<Request {self.method} {self.path}>"


class _Missing:
    pass

_MISSING = _Missing()
