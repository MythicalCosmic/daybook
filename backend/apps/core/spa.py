"""The two single-page apps Django serves next to the API, on the same origin.

- The employee mini app (`miniapp/dist`) at `/app/`, as before.
- The owner dashboard: WhiteNoise serves **only** its fingerprinted `dashboard/dist/assets/` at
  `/dashboard/assets/` (immutable). `/dashboard/` and every deep link go to `dashboard_index`,
  so the page always carries the security headers below, whatever the path.
"""

import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings as django_settings
from django.http import HttpResponse, HttpResponseNotAllowed, HttpResponseNotFound
from django.utils.cache import get_conditional_response
from django.utils.http import quote_etag
from django.views.decorators.clickjacking import xframe_options_exempt
from whitenoise.middleware import WhiteNoiseMiddleware

# Vite fingerprints everything it emits under assets/, e.g. assets/index-BJyE8SXe.js.
VITE_ASSET = re.compile(r"^/(app|dashboard)/assets/.+-[A-Za-z0-9_-]{8}\.\w+$")

# Telegram Web runs the dashboard in an iframe on web.telegram.org: frame-ancestors allows
# exactly that, instead of X-Frame-Options (which can't name an origin).
DASHBOARD_CSP = "; ".join(
    (
        "default-src 'self'",
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org",
        "connect-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self' https://telegram.org",
        "frame-ancestors https://web.telegram.org",
        "base-uri 'none'",
        "form-action 'self'",
    )
)
DASHBOARD_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": DASHBOARD_CSP,
}


class SpaWhiteNoiseMiddleware(WhiteNoiseMiddleware):
    """WhiteNoise (collected static files) plus the built mini app and dashboard assets."""

    def __init__(self, get_response=None, settings=django_settings):
        super().__init__(get_response, settings)
        configured = self.add_headers_function

        def add_headers(headers, path, url):
            if configured:
                configured(headers, path, url)
            # The mini app's page is checked again on every open (a quick 304 when nothing
            # changed): a phone holding an old page after a deploy would ask for assets that
            # are gone. Its fingerprinted assets stay cached for good (immutable_file_test).
            if url.startswith("/app/") and url.endswith(("/", ".html")):
                headers["Cache-Control"] = "no-cache"

        self.add_headers_function = add_headers
        if settings.MINIAPP_DIST.is_dir():
            self.add_files(str(settings.MINIAPP_DIST), prefix="app/")
        assets = settings.DASHBOARD_DIST / "assets"
        if assets.is_dir():
            # Never the dashboard's index.html: that one needs dashboard_index's headers.
            self.add_files(str(assets), prefix="dashboard/assets/")

    def immutable_file_test(self, path, url):
        return bool(VITE_ASSET.match(url)) or super().immutable_file_test(path, url)


# The old name, from before the dashboard existed.
MiniAppWhiteNoiseMiddleware = SpaWhiteNoiseMiddleware


@lru_cache(maxsize=8)
def _read_index(path: Path, mtime_ns: int) -> tuple[bytes, str]:
    content = path.read_bytes()
    return content, quote_etag(f"{mtime_ns:x}-{len(content):x}")


@xframe_options_exempt
def dashboard_index(request, *args, **kwargs):
    """`dashboard/dist/index.html` for `/dashboard/` and every client-side route under it."""
    if request.method not in ("GET", "HEAD"):
        response = HttpResponseNotAllowed(["GET", "HEAD"])
    else:
        index = Path(django_settings.DASHBOARD_DIST) / "index.html"
        try:
            content, etag = _read_index(index, index.stat().st_mtime_ns)
        except FileNotFoundError:
            response = HttpResponseNotFound(
                b"The dashboard isn't built. Run `make dashboard` (dev server) or build it.",
                content_type="text/plain; charset=utf-8",
            )
        else:
            response = get_conditional_response(request, etag=etag) or HttpResponse(
                content, content_type="text/html; charset=utf-8"
            )
            response["ETag"] = etag
    for header, value in DASHBOARD_HEADERS.items():
        response[header] = value
    return response
