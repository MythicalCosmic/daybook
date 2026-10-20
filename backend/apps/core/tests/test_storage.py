import re
from types import SimpleNamespace

import pytest
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.db import models
from django.db.migrations.writer import MigrationWriter

from apps.core.storage import (
    SANDBOX_HEADERS,
    PrivateStorage,
    PrivateUploadTo,
    private_storage,
    private_upload_to,
)
from config.urls import media


@pytest.fixture
def private_root(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"
    return settings.PRIVATE_MEDIA_ROOT


def test_private_files_live_under_the_private_root(private_root):
    name = private_storage.save("receipts/1/abc.pdf", ContentFile(b"%PDF-1.7"))

    assert (private_root / name).read_bytes() == b"%PDF-1.7"
    assert private_storage.path(name) == str(private_root.resolve() / name)


def test_the_root_follows_the_setting(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "one"
    assert private_storage.location == str((tmp_path / "one").resolve())
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "two"
    assert private_storage.location == str((tmp_path / "two").resolve())


def test_private_files_have_no_url(private_root):
    name = private_storage.save("receipts/1/abc.pdf", ContentFile(b"x"))

    with pytest.raises(ValueError, match="signed_url"):
        private_storage.url(name)


def test_private_storage_is_kept_apart_from_public_media(settings, private_root):
    assert private_storage.location != str(settings.MEDIA_ROOT)


def test_upload_names_are_chosen_by_the_server():
    upload_to = private_upload_to("receipts")
    row = SimpleNamespace(company_id=12)

    name = upload_to(row, "a1b2.jpg")

    assert re.fullmatch(r"receipts/12/[0-9a-f]{32}\.jpg", name)
    assert upload_to(row, "a1b2.jpg") != name  # a new name every time


@pytest.mark.parametrize(
    ("filename", "extension"),
    [
        ("x.JPEG", ".jpg"),
        ("x.jpg", ".jpg"),
        ("x.pdf", ".pdf"),
        ("x.xlsx", ".xlsx"),
        ("x.webp", ".webp"),
    ],
)
def test_extensions_come_from_the_upload_helpers(filename, extension):
    name = private_upload_to("hr/documents")(SimpleNamespace(company_id=3), filename)

    assert name.startswith("hr/documents/3/")
    assert name.endswith(extension)


@pytest.mark.parametrize("filename", ["evil.html", "photo.svg", "report", "x.pdf.exe", "x.php"])
def test_other_extensions_are_refused(filename):
    with pytest.raises(SuspiciousFileOperation):
        private_upload_to("receipts")(SimpleNamespace(company_id=3), filename)


def test_rows_without_their_own_company_name_the_path_to_it():
    upload_to = private_upload_to("projects/files", company_attr="project.company_id")
    row = SimpleNamespace(project=SimpleNamespace(company_id=8))

    assert upload_to(row, "x.pdf").startswith("projects/files/8/")


def test_a_row_must_know_its_company():
    with pytest.raises(ValueError):
        private_upload_to("receipts")(SimpleNamespace(company_id=None), "x.pdf")


def test_fields_using_them_serialize_into_migrations():
    field = models.FileField(storage=private_storage, upload_to=private_upload_to("receipts"))

    _, _, _, kwargs = field.deconstruct()
    written, imports = MigrationWriter.serialize(kwargs)

    assert "apps.core.storage.PrivateStorage()" in written
    assert "apps.core.storage.PrivateUploadTo('receipts', 'company_id')" in written
    assert "import apps.core.storage" in imports
    assert PrivateUploadTo("receipts") == private_upload_to("receipts")
    assert PrivateStorage() is not private_storage


def test_public_media_in_development_is_sandboxed(settings, rf):
    (settings.MEDIA_ROOT / "proofs").mkdir(parents=True)
    (settings.MEDIA_ROOT / "proofs" / "a.jpg").write_bytes(b"\xff\xd8\xff")

    response = media(rf.get("/media/proofs/a.jpg"), "proofs/a.jpg")

    assert response.status_code == 200
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "sandbox; default-src 'none'"
    assert SANDBOX_HEADERS == {
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
