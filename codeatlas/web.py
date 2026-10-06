"""Loopback-only demo HTTP server. Not a multi-user production gateway."""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

LOG = logging.getLogger(__name__)
MAX_BODY = 22 * 1024 * 1024


def make_server(service, port=8081, bind="127.0.0.1"):
    if bind not in {"127.0.0.1", "0.0.0.0"}:
        raise ValueError("bind must be 127.0.0.1 or 0.0.0.0")
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(100)

        def log_message(self, *args):
            # Queries and document text are deliberately excluded from access logs.
            pass

        def send(self, status, payload, content_type="application/json"):
            body = json.dumps(payload).encode() if content_type == "application/json" else payload
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            allowed = {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed:
                self.send(403, {"error": "Only localhost requests are accepted"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + host for host in allowed}:
                self.send(403, {"error": "Cross-origin requests are rejected"})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send(200, Path(__file__).with_name("static").joinpath("index.html").read_bytes(), "text/html; charset=utf-8")
            elif parsed.path == "/app.js":
                self.send(200, Path(__file__).with_name("static").joinpath("app.js").read_bytes(), "text/javascript; charset=utf-8")
            elif parsed.path == "/api/health":
                self.send(200, {"status": "ok"})
            elif parsed.path == "/api/status":
                meta = service.index.metadata()
                self.send(200, {k: v for k, v in meta.items() if k not in {"root", "digests", "unresolved_calls"}})
            else:
                self.send(404, {"error": "Not found"})

        def do_POST(self):
            if not self.allowed():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    self.send(413, {"error": "Request body is empty or exceeds 22 MiB"})
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.send(415, {"error": "Send application/json"})
                    return
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Body must be a JSON object")
                path = urlparse(self.path).path
                if path == "/api/search":
                    self.send(200, service.search(payload.get("question"), payload.get("k", 5)))
                elif path == "/api/impact":
                    self.send(200, service.impact(payload.get("symbol"), payload.get("depth", 3)))
                else:
                    self.send(404, {"error": "Not found"})
            except (ValueError, TypeError) as exc:
                self.send(400, {"error": str(exc)})
            except Exception:
                LOG.exception("Request failed")
                self.send(500, {"error": "Internal error; see server logs"})

    return ThreadingHTTPServer((bind, port), Handler)
