import io

import factory
from django.core.files.base import ContentFile
from factory.django import DjangoModelFactory
from PIL import Image

from apps.tasks.models import Task, TaskTemplate


class TaskFactory(DjangoModelFactory):
    """A personal task unless `created_by` names someone other than the assignee."""

    class Meta:
        model = Task

    company = factory.SelfAttribute("assignee.company")
    kind = factory.LazyAttribute(
        lambda task: (
            Task.Kind.PERSONAL
            if task.created_by is None or task.created_by == task.assignee
            else Task.Kind.ASSIGNED
        )
    )
    title = factory.Sequence(lambda n: f"Task {n}")
    created_by = factory.SelfAttribute("assignee")


class TaskTemplateFactory(DjangoModelFactory):
    class Meta:
        model = TaskTemplate
        skip_postgeneration_save = True

    title = factory.Sequence(lambda n: f"Daily {n}")
    due_time = "18:00"

    @factory.post_generation
    def assignees(self, create, members, **kwargs):
        if create and members:
            self.assignees.set(members)

    @factory.post_generation
    def positions(self, create, positions, **kwargs):
        if create and positions:
            self.positions.set(positions)


def jpeg_bytes(size=(40, 30), *, exif_maker: str | None = None) -> bytes:
    """A real little JPEG (proof photos are decoded, so fake bytes are refused)."""
    out = io.BytesIO()
    exif = Image.Exif()
    if exif_maker:
        exif[0x010F] = exif_maker
    Image.new("RGB", size, (90, 140, 60)).save(out, "JPEG", exif=exif)
    return out.getvalue()


def jpeg(name: str = "shelf.jpg") -> ContentFile:
    return ContentFile(jpeg_bytes(), name=name)
