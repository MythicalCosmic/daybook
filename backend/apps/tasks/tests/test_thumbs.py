"""Proof thumbnails (docs/PLAN-OWNER.md §1.3, §10.1): a 400 px WebP next to each proof photo."""

import pytest
from django.core.files.base import ContentFile
from PIL import Image

from apps.tasks import services, thumbs
from apps.tasks.models import Proof, Task
from apps.tasks.tests.factories import TaskFactory, jpeg_bytes

pytestmark = pytest.mark.django_db


def big_photo() -> ContentFile:
    return ContentFile(jpeg_bytes(size=(1600, 1200)), name="shelf.jpg")


def test_completing_with_a_photo_makes_its_preview(
    member, company, django_capture_on_commit_callbacks
):
    worker = member.registered(company)
    task = TaskFactory(assignee=worker, proof=Proof.PHOTO)
    with django_capture_on_commit_callbacks(execute=True):
        services.complete_task(task, by=worker, proof_photo=big_photo())
    task.refresh_from_db()
    assert task.proof_thumb.name.startswith(f"proofs/thumbs/{company.pk}/")
    assert task.proof_thumb.name.endswith(".webp")
    with task.proof_thumb.open("rb") as file:
        image = Image.open(file)
        assert image.format == "WEBP" and max(image.size) == 400


def test_a_task_without_a_photo_gets_none(member, company):
    task = TaskFactory(assignee=member.registered(company))
    assert thumbs.make_proof_thumb(task.pk) is False
    assert thumbs.make_proof_thumb(999999) is False


def test_older_proofs_are_backfilled(member, company):
    worker = member.registered(company)
    task = TaskFactory(assignee=worker, status=Task.Status.DONE)
    task.proof_photo.save("old.jpg", big_photo(), save=True)
    assert not task.proof_thumb
    assert thumbs.missing_thumbs() == 1
    task.refresh_from_db()
    assert task.proof_thumb
    assert thumbs.missing_thumbs() == 0


def test_the_employee_api_lists_the_preview(member, company, api_as):
    worker = member.registered(company)
    task = TaskFactory(assignee=worker, status=Task.Status.DONE)
    task.proof_photo.save("old.jpg", big_photo(), save=True)
    thumbs.make_proof_thumb(task.pk)
    row = api_as(worker).get(f"/api/v1/companies/{company.pk}/tasks/").json()["results"][0]
    assert row["proof_thumb"].endswith(".webp")


def test_a_repeated_job_writes_no_second_file(member, company):
    worker = member.registered(company)
    task = TaskFactory(assignee=worker, status=Task.Status.DONE)
    task.proof_photo.save("old.jpg", big_photo(), save=True)
    assert thumbs.make_proof_thumb(task.pk) is True
    task.refresh_from_db()
    first = task.proof_thumb.name
    # A retried (or duplicated) job finds the preview there and leaves it alone.
    assert thumbs.make_proof_thumb(task.pk) is False
    task.refresh_from_db()
    assert task.proof_thumb.name == first


def test_a_new_photo_gets_a_new_preview(member, company, django_capture_on_commit_callbacks):
    worker = member.registered(company)
    task = TaskFactory(assignee=worker, proof=Proof.PHOTO, created_by=member.registered(company))
    task.proof_photo.save("old.jpg", big_photo(), save=True)
    thumbs.make_proof_thumb(task.pk)
    task.refresh_from_db()
    old = task.proof_thumb.name
    with django_capture_on_commit_callbacks(execute=True):
        services.complete_task(task, by=worker, proof_photo=big_photo())
    task.refresh_from_db()
    assert task.proof_thumb and task.proof_thumb.name != old
