"""Private files: receipts, Z-reports, documents, selfies, exports, PDFs.

They live under `settings.PRIVATE_MEDIA_ROOT`, which the web server never serves, and have no
URL of their own: downloads go through a signed, permission-checked link (`apps.core.files`).
Content reaches this storage only through `apps.core.uploads` (re-encoded images, documents
checked by magic bytes), which also picks the file's extension.

    receipt = models.FileField(storage=private_storage, upload_to=private_upload_to("receipts"))
"""

import uuid
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible

# Extensions the upload helpers produce. Anything else means a file skipped them.
SAFE_EXTENSIONS = {
    ".jpg": ".jpg",
    ".jpeg": ".jpg",
    ".png": ".png",
    ".webp": ".webp",
    ".pdf": ".pdf",
    ".xlsx": ".xlsx",
    ".csv": ".csv",
    ".zip": ".zip",
}


@deconstructible
class PrivateStorage(FileSystemStorage):
    """`FileSystemStorage` at `PRIVATE_MEDIA_ROOT`, read on every use (tests move it), and
    without a base URL, so `url()` raises instead of leaking a public path."""

    @property
    def base_location(self):
        return str(settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return str(Path(self.base_location).resolve())

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError("Private files have no URL; use apps.core.files.signed_url().")


private_storage = PrivateStorage()


@deconstructible
class PrivateUploadTo:
    """`upload_to` for private files: `"{prefix}/{company_id}/{uuid4hex}{ext}"`.

    The extension comes from the name `apps.core.uploads` gave the content and must be one it
    produces; the client's file name is never used. `company_attr` is a dotted path on the
    instance (`"company_id"`, or `"project.company_id"` for rows without their own company).
    """

    def __init__(self, prefix: str, company_attr: str = "company_id"):
        self.prefix = prefix.strip("/")
        self.company_attr = company_attr

    def __call__(self, instance, filename: str) -> str:
        company_id = instance
        for attr in self.company_attr.split("."):
            company_id = getattr(company_id, attr)
        if company_id is None:
            raise ValueError(f"{type(instance).__name__} has no company yet; save it first.")
        extension = SAFE_EXTENSIONS.get(PurePosixPath(filename).suffix.lower())
        if extension is None:
            raise SuspiciousFileOperation(
                "Private uploads must go through apps.core.uploads, which picks the extension."
            )
        return f"{self.prefix}/{company_id}/{uuid.uuid4().hex}{extension}"

    def __eq__(self, other):
        return isinstance(other, PrivateUploadTo) and (self.prefix, self.company_attr) == (
            other.prefix,
            other.company_attr,
        )

    def __hash__(self):
        return hash((self.prefix, self.company_attr))


def private_upload_to(prefix: str, *, company_attr: str = "company_id") -> PrivateUploadTo:
    return PrivateUploadTo(prefix, company_attr)
