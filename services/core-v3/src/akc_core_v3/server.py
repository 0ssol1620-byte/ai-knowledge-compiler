"""A standard-library HTTP front for `RevisionService`.

Deliberately `http.server`. This is a reference endpoint whose job is to make the
contract executable -- a test starts it, drives the real Node client against it,
and stops it -- and a framework would add startup cost and configuration surface
to something whose whole value is having neither. A production deployment can put
the same `RevisionService` behind whatever it already runs; the service does not
know or care what is in front of it.

It binds to loopback by default and refuses anything that is not a POST to the
one route it serves.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .service import RevisionService

ROUTE = "/v3/revision-compile"

#: A revision request is metadata plus digests. Anything larger is not one, and
#: reading it before finding that out is the cheapest denial of service there is.
MAX_BODY_BYTES = 4 * 1024 * 1024


def make_handler(service: RevisionService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "tavonel-core-v3"
        sys_version = ""

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != ROUTE:
                self._send(404, {"code": "CORE_V3_ROUTE_UNKNOWN"})
                return
            try:
                length = int(self.headers.get("content-length", "0"))
            except ValueError:
                self._send(411, {"code": "CORE_V3_CONTENT_LENGTH_INVALID"})
                return
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send(413, {"code": "CORE_V3_BODY_SIZE_INVALID"})
                return
            body = self.rfile.read(length)
            status, payload = service.handle(dict(self.headers.items()), body)
            self._send(status, payload)

        def do_GET(self) -> None:
            self._send(405, {"code": "CORE_V3_METHOD_NOT_ALLOWED"})

        def log_message(self, fmt: str, *args: object) -> None:
            # Silence the default stderr access log. A request line carries the
            # tenant's world state id; it does not belong in an unstructured log.
            return

    return Handler


def serve(
    service: RevisionService,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[ThreadingHTTPServer, Callable[[], None]]:
    """Start the endpoint on a background thread and return it with a stopper."""
    httpd = ThreadingHTTPServer((host, port), make_handler(service))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def stop() -> None:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    return httpd, stop
