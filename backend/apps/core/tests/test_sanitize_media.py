import io
import re
from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from PIL import Image

from apps.core.storage import private_storage
from apps.core.uploads import sanitize_image
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'


@pytest.fixture(autouse=True)
def roots(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"


def jpeg_with_exif() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Phone maker"
    out = io.BytesIO()
    Image.new("RGB", (50, 40), (1, 2, 3)).save(out, "JPEG", exif=exif)
    return out.getvalue()


def with_proof(member, name: str, data: bytes) -> Task:
    task = TaskFactory(assignee=member)
    stored = default_storage.save(name, ContentFile(data))
    Task.objects.filter(pk=task.pk).update(proof_photo=stored)
    task.refresh_from_db()
    return task


def run(*args) -> str:
    out = StringIO()
    call_command("sanitize_media", *args, stdout=out, stderr=StringIO())
    return out.getvalue()


def test_pictures_are_reencoded_and_other_files_moved_aside(company, member):
    worker = member.registered(company)
    photo = with_proof(worker, f"proofs/{company.pk}/old.JPG", jpeg_with_exif())
    fake = with_proof(worker, f"proofs/{company.pk}/fake.jpg", SVG)
    clean_content = sanitize_image(jpeg_with_exif())
    clean = with_proof(worker, f"proofs/{company.pk}/{clean_content.name}", clean_content.read())
    clean_name = clean.proof_photo.name

    output = run()

    photo.refresh_from_db()
    fake.refresh_from_db()
    clean.refresh_from_db()
    assert re.fullmatch(rf"proofs/{company.pk}/[0-9a-f]{{32}}\.jpg", photo.proof_photo.name)
    assert not default_storage.exists(f"proofs/{company.pk}/old.JPG")
    assert b"Phone maker" not in default_storage.open(photo.proof_photo.name).read()
    assert fake.proof_photo.name == ""
    assert not default_storage.exists(f"proofs/{company.pk}/fake.jpg")
    assert private_storage.open(f"quarantine/proofs/{company.pk}/fake.jpg").read() == SVG
    assert clean.proof_photo.name == clean_name  # left alone
    assert "re-encoded 1, already clean 1, moved aside 1, missing 0" in output


def test_a_dry_run_changes_nothing(company, member):
    worker = member.registered(company)
    fake = with_proof(worker, f"proofs/{company.pk}/fake.jpg", SVG)

    output = run("--dry-run")

    fake.refresh_from_db()
    assert fake.proof_photo.name == f"proofs/{company.pk}/fake.jpg"
    assert default_storage.exists(fake.proof_photo.name)
    assert "Would have: re-encoded 0, already clean 0, moved aside 1" in output


def test_running_twice_is_safe(company, member):
    worker = member.registered(company)
    with_proof(worker, f"proofs/{company.pk}/old.png", jpeg_with_exif())

    run()
    output = run()

    assert "re-encoded 0, already clean 1" in output


def test_logos_and_missing_files(company, other_company):
    stored = default_storage.save("logos/logo.jpg", ContentFile(jpeg_with_exif()))
    type(company).objects.filter(pk=company.pk).update(logo=stored)
    type(company).objects.filter(pk=other_company.pk).update(logo="logos/gone.png")

    output = run()

    company.refresh_from_db()
    other_company.refresh_from_db()
    assert re.fullmatch(r"logos/[0-9a-f]{32}\.jpg", company.logo.name)
    assert other_company.logo.name == "logos/gone.png"
    assert "re-encoded 1, already clean 0, moved aside 0, missing 1" in output
