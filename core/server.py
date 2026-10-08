import http.server
import socket
from core.request import Request
from core.router import Router
from core import config


class _Handler(http.server.BaseHTTPRequestHandler):
    """Internal request handler wired to the Router."""

    router: Router  # injected by Server

    # ── Handled verbs ─────────────────────────────────────────────────────────

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    # ── Core ──────────────────────────────────────────────────────────────────

    def _handle(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        request = Request(
            method=self.command,
            path=self.path,
            headers=dict(self.headers),
            body=body,
        )

        response = self.router.dispatch(request)
        status, reason, headers, body_bytes = response.encode()

        self.send_response(status, reason)
        for k, v in headers.items():
            self.send_header(k, v)
        for cookie in response._cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body_bytes)

    def log_message(self, fmt, *args):
        # Custom compact log line
        print(f"  {self.address_string()} → {fmt % args}")


class Server:
    """
    Minimal HTTP server.

    Usage:
        server = Server(router, host="0.0.0.0", port=8080)
        server.serve()
    """

    def __init__(self, router: Router, host: str | None = None, port: int | None = None):
        self.router = router
        self.host = host if host is not None else config.HOST
        self.port = port if port is not None else config.PORT

    def serve(self):
        # Inject router into the handler class
        handler = type("Handler", (_Handler,), {"router": self.router})

        httpd = http.server.HTTPServer((self.host, self.port), handler)
        httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        local_ip = self._local_ip()
        print(f"\n  🚀  Server running")
        print(f"      http://localhost:{self.port}")
        print(f"      http://{local_ip}:{self.port}")
        print(f"\n  Ctrl+C to stop\n")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")
        finally:
            httpd.server_close()

    @staticmethod
    def _local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()
