import json as _json


class Response:
    """Represents an outgoing HTTP response."""

    STATUS_MESSAGES = {
        200: "OK",
        201: "Created",
        204: "No Content",
        301: "Moved Permanently",
        302: "Found",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        409: "Conflict",
        422: "Unprocessable Entity",
        500: "Internal Server Error",
    }

    def __init__(self, body: str = "", status: int = 200,
                 content_type: str = "text/html; charset=utf-8"):
        self.status       = status
        self.content_type = content_type
        self.body         = body
        self.headers: dict[str, str] = {}
        # Multiple Set-Cookie headers need a list
        self._cookies: list[str] = []

    def set_header(self, key: str, value: str) -> "Response":
        self.headers[key] = value
        return self

    def set_cookie(self, cookie_str: str) -> "Response":
        """Append a Set-Cookie header value."""
        self._cookies.append(cookie_str)
        return self

    def encode(self) -> tuple[int, str, dict, bytes]:
        reason     = self.STATUS_MESSAGES.get(self.status, "Unknown")
        body_bytes = self.body.encode("utf-8")
        headers    = {
            "Content-Type":   self.content_type,
            "Content-Length": str(len(body_bytes)),
            **self.headers,
        }
        # Note: multiple Set-Cookie are joined; the server layer must split them.
        # We store them separately so the server can send each as its own header.
        return self.status, reason, headers, body_bytes

    # ── Convenience constructors ─────────────────────────────────────────────

    @classmethod
    def html(cls, body: str, status: int = 200) -> "Response":
        return cls(body=body, status=status,
                   content_type="text/html; charset=utf-8")

    @classmethod
    def text(cls, body: str, status: int = 200) -> "Response":
        return cls(body=body, status=status,
                   content_type="text/plain; charset=utf-8")

    @classmethod
    def json(cls, data, status: int = 200) -> "Response":
        return cls(body=_json.dumps(data, default=str), status=status,
                   content_type="application/json; charset=utf-8")

    @classmethod
    def redirect(cls, location: str, permanent: bool = False) -> "Response":
        r = cls(status=301 if permanent else 302)
        r.set_header("Location", location)
        return r

    @classmethod
    def not_found(cls, message: str = "404 – Page not found") -> "Response":
        return cls.html(f"<h1>{message}</h1>", status=404)

    @classmethod
    def method_not_allowed(cls) -> "Response":
        return cls.html("<h1>405 – Method Not Allowed</h1>", status=405)

    def __repr__(self):
        return f"<Response {self.status}>"
