"""PDF documents (payslips, contracts, invoices, orders) rendered on the server with WeasyPrint.

Each module keeps its own templates (`templates/<app>/*.html`) extending
`core/base_print.html`, which brings the shared print stylesheet (`pdf_assets/print.css`: A4,
page numbers, tables, signatures) and the bundled Noto Sans, so Uzbek (with its modifier
letters) and Russian render the same on every server:

    data = render_pdf("payroll/payslip.html", {"company": company, "title": title, ...},
                      language=member.user.language)
    payslip.pdf.save(f"{uuid4().hex}.pdf", ContentFile(data), save=True)  # private storage

Rendering never reaches the network or the file system beyond the bundled assets: images go in
as `data:` URIs (`image_src()`), and any other URL in a template is refused, so text a person
typed into a contract template can't make the server fetch anything.
"""

import base64
import logging
from pathlib import Path, PurePosixPath

from django.template.loader import render_to_string
from django.utils import translation

ASSETS_DIR = Path(__file__).resolve().parent / "pdf_assets"
STYLESHEET = ASSETS_DIR / "print.css"

IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

logger = logging.getLogger(__name__)


class PdfResourceRefused(ValueError):
    pass


def render_pdf(template_name: str, context: dict, *, language: str) -> bytes:
    """Render `template_name` with `context` in `language` and return the PDF bytes."""
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration

    with translation.override(language):
        html = render_to_string(template_name, context)
    fetcher = _assets_only_fetcher()
    fonts = FontConfiguration()
    stylesheet = CSS(filename=str(STYLESHEET), font_config=fonts, url_fetcher=fetcher)
    document = HTML(string=html, base_url=str(ASSETS_DIR) + "/", url_fetcher=fetcher)
    return document.write_pdf(stylesheets=[stylesheet], font_config=fonts)


def image_src(file) -> str:
    """A `data:` URI for a picture (a `FieldFile` or a path in a storage), for `<img src>` in
    a print template. Only JPEG, PNG and WebP up to 5 MB; anything else gives ""."""
    name = getattr(file, "name", "") or ""
    content_type = IMAGE_TYPES.get(PurePosixPath(name).suffix.lower())
    if not content_type:
        return ""
    try:
        file.open("rb")
        try:
            data = file.read(MAX_IMAGE_BYTES + 1)
        finally:
            file.close()
    except OSError, ValueError:
        logger.warning("Picture %s for a PDF can't be read", name)
        return ""
    if len(data) > MAX_IMAGE_BYTES:
        return ""
    return f"data:{content_type};base64,{base64.b64encode(data).decode()}"


def _assets_only_fetcher():
    """WeasyPrint's URL fetcher, limited to `data:` URIs and the bundled assets."""
    from urllib.parse import unquote, urlsplit

    from weasyprint.urls import URLFetcher

    class AssetsOnlyFetcher(URLFetcher):
        def fetch(self, url, headers=None):
            if url.startswith("data:"):
                return super().fetch(url, headers)
            if url.startswith("file:"):
                path = Path(unquote(urlsplit(url).path)).resolve()
                if path.is_relative_to(ASSETS_DIR) and path.is_file():
                    return super().fetch(url, headers)
            raise PdfResourceRefused(f"PDF templates may not load {url[:80]!r}.")

    return AssetsOnlyFetcher(allowed_protocols={"data", "file"}, allow_redirects=False)
