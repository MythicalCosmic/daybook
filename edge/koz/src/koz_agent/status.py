"""The local status page at ``http://127.0.0.1:8737`` (localhost only).

- ``/``: the page (uz/ru/en, no CDN); ``?tv=1`` is the full-screen TV view, ``?still=1`` refreshes
  pictures instead of streaming them.
- ``/api/status``: what the page shows, as JSON.
- ``/mjpeg/<key>``: a live MJPEG preview with boxes and zones; ``/frame/<key>.jpg``: one picture.

Requests whose ``Host`` is not this machine's loopback are refused, so a web page elsewhere cannot
read the cameras through the browser (DNS rebinding).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import unquote, urlsplit

log = logging.getLogger(__name__)

FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" '
    'rx="9" fill="#0D9488"/><path d="M5 16c3-5.5 7-8 11-8s8 2.5 11 8c-3 5.5-7 8-11 8s-8-2.5-11-8z" '
    'fill="#fff"/><circle cx="16" cy="16" r="4.6" fill="#0D9488"/><circle cx="17.6" cy="14.4" '
    'r="1.5" fill="#fff"/></svg>'
)


def page_html() -> str:
    return resources.files("koz_agent").joinpath("status_page.html").read_text(encoding="utf-8")


class StatusServer:
    def __init__(self, agent, *, host: str = "127.0.0.1", port: int = 8737,
                 mjpeg_fps: float = 6.0) -> None:
        self.agent = agent
        self.host = host
        self.port = port
        self.mjpeg_fps = mjpeg_fps
        self._server: ThreadingHTTPServer | None = None
        self._stop = threading.Event()

    def start(self) -> int:
        status = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args) -> None:
                return

            def _allowed(self) -> bool:
                host = (self.headers.get("Host") or "").lower()
                name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
                return name in ("127.0.0.1", "localhost", "[::1]")

            def _send(self, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                    "script-src 'self' 'unsafe-inline'; connect-src 'self'",
                )
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_HEAD(self) -> None:
                self.do_GET()

            def do_GET(self) -> None:
                if not self._allowed():
                    self._send(403, b"forbidden", "text/plain")
                    return
                path = unquote(urlsplit(self.path).path)
                try:
                    if path in ("/", "/index.html"):
                        self._send(200, page_html().encode("utf-8"), "text/html; charset=utf-8")
                    elif path == "/api/status":
                        body = json.dumps(status.agent.status(), ensure_ascii=False).encode()
                        self._send(200, body, "application/json; charset=utf-8")
                    elif path == "/favicon.svg":
                        self._send(200, FAVICON.encode(), "image/svg+xml")
                    elif path.startswith("/frame/") and path.endswith(".jpg"):
                        jpeg = status.agent.preview_jpeg(path[len("/frame/"):-4])
                        if jpeg is None:
                            self._send(404, b"no picture yet", "text/plain")
                        else:
                            self._send(200, jpeg, "image/jpeg")
                    elif path.startswith("/mjpeg/"):
                        self._mjpeg(path[len("/mjpeg/"):])
                    else:
                        self._send(404, b"not found", "text/plain")
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return

            def _mjpeg(self, key: str) -> None:
                if key not in status.agent.cams:
                    self._send(404, b"no such camera", "text/plain")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=kozframe")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                period = 1.0 / status.mjpeg_fps
                while not status._stop.is_set():
                    started = time.monotonic()
                    jpeg = status.agent.preview_jpeg(key)
                    if jpeg:
                        self.wfile.write(
                            b"--kozframe\r\nContent-Type: image/jpeg\r\nContent-Length: "
                            + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
                        )
                        self.wfile.flush()
                    status._stop.wait(max(0.02, period - (time.monotonic() - started)))

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, name="status-page", daemon=True).start()
        log.info("status page on http://%s:%d", self.host, self.port)
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
