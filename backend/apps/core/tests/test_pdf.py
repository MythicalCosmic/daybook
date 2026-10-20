import io
import logging
import re
import zlib
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import translation
from PIL import Image

from apps.core import pdf

TEMPLATE = """{% extends "core/base_print.html" %}{% load i18n %}
{% block content %}
<h1>{% translate "Name" %}: Oʻzbekiston, gʻalaba</h1>
<p><b>Привет, мир!</b> <i>Ўзбекистон, қўшиқ, ғалаба, ҳамма.</i> № 12 — «5 200 000 soʻm»</p>
<table><tr><td>Oylik</td><td class="num">5 200 000 soʻm</td></tr></table>
{% if logo_src %}<img src="{{ logo_src }}">{% endif %}
<img src="http://127.0.0.1:1/steal.png">
<img src="file:///etc/passwd">
<link rel="stylesheet" href="https://example.com/x.css">
{% endblock %}"""


@pytest.fixture
def print_templates(settings, tmp_path):
    (tmp_path / "test_print").mkdir()
    (tmp_path / "test_print" / "doc.html").write_text(TEMPLATE)
    settings.TEMPLATES = [{**settings.TEMPLATES[0], "DIRS": [tmp_path]}]


@pytest.fixture
def opened(monkeypatch):
    """URLs WeasyPrint actually opened (after our fetcher let them through)."""
    from weasyprint.urls import URLFetcher

    urls = []
    original = URLFetcher.fetch

    def recording(self, url, headers=None):
        urls.append(url)
        return original(self, url, headers)

    monkeypatch.setattr(URLFetcher, "fetch", recording)
    return urls


def company():
    return SimpleNamespace(name="Demo Shop")


def font_names(data: bytes) -> set[bytes]:
    """Embedded font names; WeasyPrint keeps PDF objects in compressed object streams."""
    streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S)
    objects = b"".join(_inflate(stream) for stream in streams) + data
    return {name.split(b"+")[-1] for name in re.findall(rb"/BaseFont\s*/([\w+-]+)", objects)}


def test_renders_a_pdf_with_the_bundled_fonts(print_templates, opened):
    data = pdf.render_pdf(
        "test_print/doc.html", {"company": company(), "title": "Oylik"}, language="uz"
    )

    assert data.startswith(b"%PDF-")
    for style in ("Regular", "Bold", "Italic"):
        assert any(url.endswith(f"/fonts/NotoSans-{style}.ttf") for url in opened), style
    names = font_names(data)
    assert names and all(name.startswith(b"Noto") for name in names), names


@pytest.mark.parametrize("style", ["Regular", "Bold", "Italic", "BoldItalic"])
def test_the_bundled_fonts_cover_uzbek_and_russian(style):
    from fontTools.ttLib import TTFont

    cmap = TTFont(pdf.ASSETS_DIR / "fonts" / f"NotoSans-{style}.ttf").getBestCmap()
    text = (
        "Oʻzbekiston gʻalaba O‘g‘il ABCabc 0123456789 Ўзбекистон қўшиқ ғалаба ҳамма ЁёЭэЪъ "
        "Привет № — – « » „ “ ” ‘ ’ • … $ € ₽ % +−×÷ ©"
    )
    assert not {char for char in text if not char.isspace() and ord(char) not in cmap}


def test_nothing_outside_the_bundled_assets_is_opened(print_templates, opened, caplog):
    with caplog.at_level(logging.WARNING):
        data = pdf.render_pdf("test_print/doc.html", {"company": company()}, language="uz")

    assert data.startswith(b"%PDF-")
    assets = pdf.ASSETS_DIR.as_uri()
    assert opened
    assert all(url.startswith(("data:", assets)) for url in opened), opened
    assert "127.0.0.1" in caplog.text  # the template asked for it, and was refused


def test_refused_urls_raise_in_the_fetcher():
    fetcher = pdf._assets_only_fetcher()
    outside = pdf.ASSETS_DIR / ".." / "pdf.py"
    for url in ("http://example.com/a.png", "file:///etc/passwd", "ftp://x/y", outside.as_uri()):
        with pytest.raises(ValueError):
            fetcher.fetch(url)
    assert fetcher.fetch((pdf.ASSETS_DIR / "print.css").as_uri())


def test_logos_go_in_as_data_uris(print_templates, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    out = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 0, 0)).save(out, "PNG")
    name = default_storage.save("logos/logo.png", ContentFile(out.getvalue()))
    logo = default_storage.open(name)
    logo.name = name

    src = pdf.image_src(logo)
    data = pdf.render_pdf(
        "test_print/doc.html", {"company": company(), "logo_src": src}, language="uz"
    )

    assert src.startswith("data:image/png;base64,")
    assert data.startswith(b"%PDF-")


def test_image_src_refuses_other_files(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    name = default_storage.save("logos/logo.svg", ContentFile(b"<svg/>"))
    svg = default_storage.open(name)
    svg.name = name

    assert pdf.image_src(svg) == ""
    assert pdf.image_src(SimpleNamespace(name="")) == ""


def test_the_documents_language_does_not_leak(print_templates):
    with translation.override("en"):
        pdf.render_pdf("test_print/doc.html", {"company": company()}, language="ru")
        assert translation.get_language() == "en"


def _inflate(stream: bytes) -> bytes:
    try:
        return zlib.decompress(stream)
    except zlib.error:
        return b""
