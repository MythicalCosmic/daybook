"""Every file a person uploads goes through here before it is stored (docs/PLAN-OWNER.md §2.8).

Images (proof photos, receipts, Z-reports, selfies, scans, logos, avatars) go through
`sanitize_image()`: Pillow decodes every pixel, EXIF rotation is applied, all metadata
(EXIF with GPS, comments, XMP) is dropped and the picture is re-encoded as a JPEG with a name
the server picks. Whatever Pillow can't decode is refused, so an SVG or HTML page can never be
stored as an "image". Other files go through `accept_document()`, which recognises the type
from the content (magic bytes), never from the client's name or content type, and also picks
the name.

    photo = uploads.sanitize_image(request.FILES["photo"])  # ContentFile "<uuid>.jpg"
    task.proof_photo.save(photo.name, photo, save=False)

Both raise `InvalidUpload` (a `DomainError`, so the API answers 400 with its message).
"""

import csv
import io
import threading
import uuid
import warnings
import zipfile
from collections.abc import Iterable
from contextlib import contextmanager

import pillow_heif
from django.core.files.base import ContentFile
from django.utils.translation import gettext as _
from PIL import Image, ImageCms, ImageFile, ImageOps, UnidentifiedImageError

from apps.core.exceptions import DomainError

pillow_heif.register_heif_opener()

# The largest upload we read at all.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# Decoded size limit: 64 megapixels (about 190 MB of RGB). Bigger pictures are refused before
# their pixels are decoded, so a tiny "decompression bomb" file can't exhaust memory.
MAX_PIXELS = 64_000_000
# The only decoders tried. Exotic formats (EPS through Ghostscript, PSD, ICO…) are never
# opened, which keeps the attack surface to well-tested decoders. (JPEG covers MPO, the
# multi-picture JPEG some cameras write.)
IMAGE_FORMATS = ("JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "HEIF", "AVIF")
# Document kinds `accept_document` knows, and the extension each one is stored with. "image"
# accepts any picture `sanitize_image` can decode (stored as a JPEG).
DOCUMENT_KINDS = {"pdf": "pdf", "xlsx": "xlsx", "csv": "csv", "zip": "zip", "image": "jpg"}
# A spreadsheet that would unpack to more than this is refused (zip bomb).
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
# Encodings a CSV file may use (Excel in Uzbekistan often saves Windows-1251).
CSV_ENCODINGS = ("utf-8-sig", "cp1251")

_SRGB = ImageCms.createProfile("sRGB")
_decoding_lock = threading.Lock()


class InvalidUpload(DomainError):
    """The file can't be accepted. The message is safe to show to the person who sent it."""


class SanitizedFile(ContentFile):
    """Content made by this module: decoded and re-encoded, or checked, with a server name."""


def is_sanitized(file) -> bool:
    return isinstance(file, SanitizedFile)


def sanitize_image(
    file, *, max_side: int = 2560, quality: int = 85, max_bytes: int = MAX_UPLOAD_BYTES
) -> SanitizedFile:
    """Decode `file` (an upload, a `File` or raw bytes) and re-encode it as `<uuid>.jpg`.

    The longest side is scaled down to `max_side`; colours are converted to sRGB; transparency
    is flattened onto white; only the first frame of an animation is kept.
    """
    image = _decode(_read(file, max_bytes))
    image = _flatten(image)
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    # No exif, icc_profile or comment arguments: nothing from the original is carried over.
    image.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return SanitizedFile(out.getvalue(), name=f"{uuid.uuid4().hex}.jpg")


def make_thumb(file, *, side: int = 400, quality: int = 80) -> SanitizedFile:
    """A small WebP preview (`<uuid>.webp`) of an image, for lists and cards."""
    image = _flatten(_decode(_read(file, MAX_UPLOAD_BYTES)))
    image.thumbnail((side, side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "WEBP", quality=quality, method=4)
    return SanitizedFile(out.getvalue(), name=f"{uuid.uuid4().hex}.webp")


def accept_document(
    file,
    *,
    allowed: Iterable[str] = ("pdf", "xlsx", "csv"),
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> SanitizedFile:
    """Check what `file` really is and return it as `<uuid>.<ext>`, the extension chosen here.

    `allowed` names kinds of `DOCUMENT_KINDS`. A picture, when "image" is allowed, is
    re-encoded by `sanitize_image`; every other kind is stored byte for byte.
    """
    allowed = set(allowed)
    if unknown := allowed - DOCUMENT_KINDS.keys():
        raise ValueError(f"Unknown document kinds: {sorted(unknown)}")
    data = _read(file, max_bytes)
    kind = _detect(data)
    if kind not in allowed:
        raise InvalidUpload(_unsupported_message(allowed))
    if kind == "image":
        return sanitize_image(data, max_bytes=max_bytes)
    return SanitizedFile(data, name=f"{uuid.uuid4().hex}.{DOCUMENT_KINDS[kind]}")


def _read(file, max_bytes: int) -> bytes:
    if isinstance(file, bytes | bytearray):
        data = bytes(file)
    else:
        size = getattr(file, "size", None)
        if size is not None and size > max_bytes:
            raise InvalidUpload(_too_large_message(max_bytes))
        if hasattr(file, "seek"):
            file.seek(0)
        data = file.read(max_bytes + 1)
        if hasattr(file, "seek"):
            file.seek(0)
    if len(data) > max_bytes:
        raise InvalidUpload(_too_large_message(max_bytes))
    if not data:
        raise InvalidUpload(_("The file is empty."))
    return data


@contextmanager
def _strict_decoding():
    """Truncated files must fail to decode. WeasyPrint switches Pillow's process-wide
    LOAD_TRUNCATED_IMAGES on when it is imported, so it is turned off around our decoding."""
    with _decoding_lock:
        previous = ImageFile.LOAD_TRUNCATED_IMAGES
        ImageFile.LOAD_TRUNCATED_IMAGES = False
        try:
            yield
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous


def _decode(data: bytes) -> Image.Image:
    """Open and fully decode the picture, or refuse it."""
    try:
        with _strict_decoding(), warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data), formats=IMAGE_FORMATS)
            if image.width * image.height > MAX_PIXELS:
                raise InvalidUpload(_("The picture is too big. Send a smaller one."))
            image.seek(0)  # the first frame of an animation
            image.load()  # decodes every pixel: a truncated or crafted file fails here
            image = ImageOps.exif_transpose(image)
    except InvalidUpload:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
        EOFError,
        TypeError,
        IndexError,
        KeyError,
        MemoryError,
    ) as exc:
        raise InvalidUpload(_("This file isn't a picture we can read. Send a photo.")) from exc
    return image


def _flatten(image: Image.Image) -> Image.Image:
    """An RGB (or greyscale) picture in sRGB, without transparency or a colour profile."""
    profile = image.info.get("icc_profile")
    if profile and image.mode in ("RGB", "RGBA", "CMYK", "L", "LA"):
        try:
            source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
            mode = "RGBA" if image.mode in ("RGBA", "LA") else "RGB"
            image = ImageCms.profileToProfile(image, source, _SRGB, outputMode=mode)
        except ImageCms.PyCMSError, OSError, ValueError:
            pass  # a broken profile: keep the pixels as they are
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    elif image.mode != "L":
        image = image.convert("RGB")
    image.info = {}
    return image


def _detect(data: bytes) -> str | None:
    """The document kind of `data`, judged from its content only."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return _zip_kind(data)
    if _is_image(data):
        return "image"
    if _is_csv(data):
        return "csv"
    return None


def _zip_kind(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if sum(entry.file_size for entry in entries) > MAX_UNPACKED_BYTES:
                return None
            names = {entry.filename for entry in entries}
    except zipfile.BadZipFile, OSError, ValueError:
        return None
    if "[Content_Types].xml" in names and "xl/workbook.xml" in names:
        return "xlsx"
    if "[Content_Types].xml" in names:
        return None  # another Office file (docx, pptx), which we don't take
    return "zip"


def _is_image(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data), formats=IMAGE_FORMATS) as image:
            image.verify()
    except Exception:  # anything Pillow can't identify is simply not an image
        return False
    return True


def _is_csv(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    for encoding in CSV_ENCODINGS:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        head = text.lstrip()[:512].lower()
        if head.startswith(("<", "{", "[")) or "<script" in head or "<html" in head:
            return False  # markup or JSON wearing a .csv name
        try:
            rows = list(csv.reader(io.StringIO(text[:65536])))
        except csv.Error:
            return False
        return bool(rows)
    return False


def _too_large_message(max_bytes: int) -> str:
    return _("The file is too large (%(megabytes)d MB at most).") % {
        "megabytes": max_bytes // (1024 * 1024)
    }


def _unsupported_message(allowed: set[str]) -> str:
    names = {"pdf": "PDF", "xlsx": "Excel (xlsx)", "csv": "CSV", "zip": "ZIP", "image": _("photo")}
    kinds = ", ".join(names[kind] for kind in sorted(allowed))
    return _("This type of file isn't accepted. Send one of: %(kinds)s.") % {"kinds": kinds}
