import io
import re
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core import uploads
from apps.core.exceptions import DomainError
from apps.core.uploads import InvalidUpload, accept_document, make_thumb, sanitize_image

SERVER_NAME = re.compile(r"^[0-9a-f]{32}\.(jpg|webp|pdf|xlsx|csv|zip)$")

SVG = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.cookie)">
  <script>fetch('/api/v1/me/')</script><rect width="10" height="10"/>
</svg>"""
HTML = b"<!doctype html><html><body><script>alert(1)</script></body></html>"


def picture(fmt="JPEG", size=(64, 48), mode="RGB", color=(200, 30, 30), **save) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, fmt, **save)
    return out.getvalue()


def jpeg_with_gps_and_rotation() -> bytes:
    image = Image.new("RGB", (80, 40), (10, 120, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    exif[0x010F] = "Phone maker"
    gps = {1: "N", 2: (41.0, 18.0, 0.0), 3: "E", 4: (69.0, 16.0, 0.0)}
    exif[0x8825] = gps
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif, comment=b"secret comment")
    return out.getvalue()


def upload(data: bytes, name="photo.jpg", content_type="image/jpeg") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type=content_type)


def reopen(file) -> Image.Image:
    image = Image.open(io.BytesIO(file.read()))
    file.seek(0)
    return image


def test_a_jpeg_is_reencoded_with_a_server_chosen_name():
    result = sanitize_image(upload(picture(), name="../../evil.php.jpg"))

    assert SERVER_NAME.match(result.name)
    assert result.name.endswith(".jpg")
    assert uploads.is_sanitized(result)
    image = reopen(result)
    assert image.format == "JPEG"
    assert image.size == (64, 48)


def test_metadata_is_dropped_and_rotation_applied():
    result = sanitize_image(upload(jpeg_with_gps_and_rotation()))

    image = reopen(result)
    assert image.size == (40, 80)  # turned upright
    assert not image.getexif()
    assert "exif" not in image.info
    assert "comment" not in image.info
    raw = result.read()
    assert b"Phone maker" not in raw
    assert b"secret comment" not in raw


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (SVG, "proof.svg"),
        (SVG, "proof.jpg"),
        (HTML, "proof.html"),
        (HTML, "proof.png"),
        (b"%PDF-1.7\n1 0 obj", "proof.jpg"),
        (b"GIF89a<script>alert(1)</script>", "proof.gif"),
    ],
)
def test_anything_that_is_not_a_decodable_picture_is_refused(data, name):
    with pytest.raises(InvalidUpload):
        sanitize_image(upload(data, name=name, content_type="image/jpeg"))


def test_refusals_are_domain_errors_with_a_safe_message():
    with pytest.raises(DomainError, match="isn't a picture"):
        sanitize_image(upload(SVG))


@pytest.mark.parametrize("weasyprint_loaded", [False, True])
def test_a_truncated_jpeg_is_refused(monkeypatch, weasyprint_loaded):
    from PIL import ImageFile

    # Importing WeasyPrint switches Pillow's LOAD_TRUNCATED_IMAGES on for the whole process.
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", weasyprint_loaded)
    data = picture(size=(400, 300))

    with pytest.raises(InvalidUpload):
        sanitize_image(upload(data[: len(data) // 2]))
    assert weasyprint_loaded == ImageFile.LOAD_TRUNCATED_IMAGES  # restored afterwards


def test_empty_and_oversized_uploads_are_refused():
    with pytest.raises(InvalidUpload, match="empty"):
        sanitize_image(upload(b""))
    with pytest.raises(InvalidUpload, match="too large"):
        sanitize_image(upload(picture()), max_bytes=100)


def test_decompression_bombs_are_refused_before_decoding(monkeypatch):
    monkeypatch.setattr(uploads, "MAX_PIXELS", 1000)
    with pytest.raises(InvalidUpload, match="too big"):
        sanitize_image(upload(picture(size=(100, 100))))


def test_large_pictures_are_scaled_down_to_max_side():
    result = sanitize_image(upload(picture(size=(3000, 1500))), max_side=1000)

    assert reopen(result).size == (1000, 500)


@pytest.mark.parametrize(
    ("fmt", "mode", "color"),
    [
        ("PNG", "RGBA", (0, 0, 0, 0)),
        ("PNG", "P", 3),
        ("GIF", "P", 1),
        ("WEBP", "RGB", (1, 2, 3)),
        ("BMP", "RGB", (1, 2, 3)),
        ("TIFF", "CMYK", (0, 0, 0, 0)),
        ("PNG", "L", 128),
        ("PNG", "I;16", 4000),
    ],
)
def test_other_formats_become_jpeg(fmt, mode, color):
    result = sanitize_image(upload(picture(fmt, mode=mode, color=color), name=f"x.{fmt.lower()}"))

    image = reopen(result)
    assert image.format == "JPEG"
    assert image.mode in ("RGB", "L")


def test_transparency_is_flattened_onto_white():
    result = sanitize_image(upload(picture("PNG", mode="RGBA", color=(0, 0, 0, 0))))

    assert reopen(result).convert("RGB").getpixel((0, 0)) == (255, 255, 255)


def test_heic_photos_from_iphones_are_accepted():
    import pillow_heif

    heif = pillow_heif.from_pillow(Image.new("RGB", (32, 32), (0, 128, 0)))
    out = io.BytesIO()
    heif.save(out, quality=80)

    result = sanitize_image(upload(out.getvalue(), name="IMG_0001.HEIC"))

    assert reopen(result).format == "JPEG"


def test_raw_bytes_are_accepted_too():
    assert sanitize_image(picture()).name.endswith(".jpg")


def test_thumbnails_are_small_webp_files():
    thumb = make_thumb(upload(picture(size=(1600, 1200))))

    assert SERVER_NAME.match(thumb.name)
    assert thumb.name.endswith(".webp")
    image = reopen(thumb)
    assert image.format == "WEBP"
    assert max(image.size) == 400


def test_thumbnails_refuse_non_images():
    with pytest.raises(InvalidUpload):
        make_thumb(upload(SVG))


def xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    out = io.BytesIO()
    Workbook().save(out)
    return out.getvalue()


def docx_like_bytes() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return out.getvalue()


def test_documents_get_their_type_from_the_content_not_the_name():
    pdf = accept_document(upload(b"%PDF-1.7\n%%EOF", name="report.exe"))
    sheet = accept_document(upload(xlsx_bytes(), name="data.pdf"))
    table = accept_document(upload(b"name;amount\nAli;100\n", name="x.html"))

    assert pdf.name.endswith(".pdf")
    assert sheet.name.endswith(".xlsx")
    assert table.name.endswith(".csv")
    assert all(SERVER_NAME.match(f.name) for f in (pdf, sheet, table))
    assert pdf.read() == b"%PDF-1.7\n%%EOF"


def macro_workbook_bytes() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes())) as source, zipfile.ZipFile(out, "w") as copy:
        for entry in source.infolist():
            copy.writestr(entry, source.read(entry))
        copy.writestr("xl/vbaProject.bin", b"\xd0\xcf\x11\xe0 macros")
    return out.getvalue()


@pytest.mark.parametrize(
    "data",
    [
        SVG,
        HTML,
        docx_like_bytes(),
        macro_workbook_bytes(),
        b"\x00\x01\x02binary",
        b'{"json": true}',
    ],
)
def test_documents_of_other_kinds_are_refused(data):
    with pytest.raises(InvalidUpload, match="isn't accepted"):
        accept_document(upload(data, name="file.pdf"))


def test_only_the_allowed_kinds_pass():
    with pytest.raises(InvalidUpload):
        accept_document(upload(xlsx_bytes()), allowed={"pdf"})


def test_csv_in_windows_1251_is_accepted():
    data = "Имя;Сумма\nАли;100\n".encode("cp1251")
    assert accept_document(upload(data), allowed={"csv"}).name.endswith(".csv")


def test_pictures_pass_as_documents_only_when_images_are_allowed():
    with pytest.raises(InvalidUpload):
        accept_document(upload(picture()), allowed={"pdf"})

    scan = accept_document(upload(jpeg_with_gps_and_rotation()), allowed={"pdf", "image"})

    assert scan.name.endswith(".jpg")
    assert b"Phone maker" not in scan.read()


def test_zip_bombs_are_refused(monkeypatch):
    monkeypatch.setattr(uploads, "MAX_UNPACKED_BYTES", 10)
    with pytest.raises(InvalidUpload):
        accept_document(upload(xlsx_bytes()), allowed={"xlsx"})


def test_every_listed_decoder_is_available():
    Image.init()
    assert set(uploads.IMAGE_FORMATS) <= set(Image.OPEN)


def test_unknown_document_kinds_are_a_programming_error():
    with pytest.raises(ValueError, match="Unknown document kinds"):
        accept_document(upload(b"%PDF-1.7"), allowed={"docx"})
