"""The two single-page apps Django serves next to the API, on the same origin.

- The employee mini app (`miniapp/dist`) at `/app/`, as before.
- The owner dashboard: WhiteNoise serves **only** its fingerprinted `dashboard/dist/assets/` at
  `/dashboard/assets/` (immutable). `/dashboard/` and every deep link go to `dashboard_index`,
  so the page always carries the security headers below, whatever the path.
"""

import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from django.conf import settings as django_settings
from django.http import HttpResponse, HttpResponseNotAllowed, HttpResponseNotFound
from django.utils.cache import get_conditional_response
from django.utils.http import quote_etag
from django.views.decorators.clickjacking import xframe_options_exempt
from whitenoise.middleware import WhiteNoiseMiddleware

# Vite fingerprints everything it emits under assets/, e.g. assets/index-BJyE8SXe.js.
VITE_ASSET = re.compile(r"^/(app|dashboard)/assets/.+-[A-Za-z0-9_-]{8}\.\w+$")

# Telegram Web runs the dashboard in an iframe on web.telegram.org: frame-ancestors allows
# exactly that, instead of X-Frame-Options (which can't name an origin). A lesson's preview plays
# its video (signed same-origin links) or a YouTube link through the privacy-enhanced player
# (docs/PLAN-LEARNING.md §5); PdfPreview frames signed PDFs of the same origin.
DASHBOARD_CSP = "; ".join(
    (
        "default-src 'self'",
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://i.ytimg.com",
        "media-src 'self' blob:",
        "connect-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self' https://telegram.org https://www.youtube.com",
        "frame-src 'self' https://www.youtube-nocookie.com",
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


# Davomat's first paint (docs/DAVOMAT.md): until the app has asked which edition this is, the page
# is the built index.html, Daybook's. A Davomat install answers with its own title, mark and canvas,
# so it never flashes Daybook's splash. The mark is core/brand.ts's davomatMark() (a test keeps the
# two in step): a white D with a check cut into it, on an indigo tile.
DAVOMAT_MARK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><defs><linearGradient id="dg" '
    'gradientUnits="userSpaceOnUse" x1="7.2" y1="0" x2="40.8" y2="48"><stop offset="0" '
    'stop-color="#6c69f7"/><stop offset="1" stop-color="#4136d6"/></linearGradient>'
    '<linearGradient id="dh" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" '
    'stop-opacity=".2"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/></linearGradient>'
    '</defs><rect width="48" height="48" rx="13.5" fill="url(#dg)"/><path d="M14 15.5A3.5 3.5 0 0 '
    '1 17.5 12H22a12 12 0 0 1 0 24h-4.5A3.5 3.5 0 0 1 14 32.5Z" fill="#fff"/><path d="M18.6 '
    '24.3l3.4 3.4 6.8-7.1" fill="none" stroke="url(#dg)" stroke-width="3.4" stroke-linecap="round" '
    'stroke-linejoin="round"/><rect width="48" height="48" rx="13.5" fill="url(#dh)"/><rect '
    'x=".5" y=".5" width="47" height="47" rx="13" fill="none" stroke="#fff" stroke-opacity=".1"/>'
    "</svg>"
)
BOOT_MARK = re.compile(rb'(<div class="boot"[^>]*>\s*)<svg\b.*?</svg>', re.S)


def _davomat_index(content: bytes) -> bytes:
    mark = DAVOMAT_MARK.encode()
    content = content.replace(b"<title>Daybook Console</title>", b"<title>Davomat</title>")
    content = content.replace(
        b'href="/dashboard/favicon.svg"',
        b'href="data:image/svg+xml,' + quote(DAVOMAT_MARK).encode() + b'"',
    )
    # Daybook's warm paper (light, dark) becomes Davomat's cool canvas.
    content = content.replace(b"#f7f3ec", b"#f4f6fa").replace(b"#141210", b"#0b0e14")
    return BOOT_MARK.sub(lambda found: found.group(1) + mark, content, count=1)


@lru_cache(maxsize=8)
def _read_index(path: Path, mtime_ns: int, edition: str = "daybook") -> tuple[bytes, str]:
    content = path.read_bytes()
    if edition == "davomat":
        content = _davomat_index(content)
    return content, quote_etag(f"{mtime_ns:x}-{len(content):x}-{edition}")


@xframe_options_exempt
def dashboard_index(request, *args, **kwargs):
    """`dashboard/dist/index.html` for `/dashboard/` and every client-side route under it."""
    if request.method not in ("GET", "HEAD"):
        response = HttpResponseNotAllowed(["GET", "HEAD"])
    else:
        index = Path(django_settings.DASHBOARD_DIST) / "index.html"
        try:
            content, etag = _read_index(
                index, index.stat().st_mtime_ns, getattr(django_settings, "EDITION", "daybook")
            )
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
