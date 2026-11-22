"""Serves a built web bundle with single-page-app fallback (any unknown path -> index.html).

usage (inside the build container): python3 crm/tools/spa_serve.py <public dir> <port>
"""
import functools
import http.server
import os
import sys

root, port = sys.argv[1], int(sys.argv[2])


class Handler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.exists(path) or (os.path.isdir(path) and not os.path.exists(os.path.join(path, "index.html"))):
            self.path = "/index.html"
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


Handler.extensions_map[".wasm"] = "application/wasm"
http.server.ThreadingHTTPServer(("0.0.0.0", port), functools.partial(Handler, directory=root)).serve_forever()
