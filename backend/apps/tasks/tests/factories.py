import importlib
import io
from dataclasses import dataclass

import factory
from django.core.files.base import ContentFile
from factory.django import DjangoModelFactory
from PIL import Image

from apps.ai.tools import registry as ai_registry
from apps.companies.tests.factories import BranchFactory
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.tasks.models import Task, TaskTemplate


def ensure_ai_tools(*modules: str) -> None:
    """Make sure the tools of `modules` are in the AI tool registry.

    apps.ai's `test_every_installed_tool_follows_the_rules` imports every app's ai_tools module
    into a throwaway registry, so a test running after it can find the real one without them
    (the modules are imported, so discovery never runs them again). Load them again if so.
    """
    present = {tool.fn.__module__ for tool in ai_registry.all_tools()}
    for name in modules:
        if name not in present:
            importlib.reload(importlib.import_module(name))


@dataclass
class Shop:
    """A company with two branches and the people the owner console tests need."""

    company: object
    here: object  # the company's first branch
    there: object  # a second branch, "Yunusobod"
    owner: Membership
    manager: Membership  # every branch (branches.all)
    lead: Membership  # a branch lead: tasks, reminders and reports, only `here`
    worker: Membership  # works `here`
    colleague: Membership  # works `there`


LEAD_PERMS = [
    Perm.DASHBOARD_ACCESS,
    Perm.TASKS_VIEW_ALL,
    Perm.TASKS_ASSIGN,
    Perm.TASKS_CONFIRM,
    Perm.TASKS_TEMPLATES,
    Perm.REPORTS_VIEW,
    Perm.REMINDERS_CONFIGURE,
    Perm.MEMBERS_VIEW,
]


def make_shop(company, member) -> Shop:
    """`member` is the root `member` fixture (a MemberMaker)."""
    here = company.branches.get()
    there = BranchFactory(company=company, name="Yunusobod", code="YNS")
    AccessRole.objects.get_or_create(
        company=company, name="Branch lead", defaults={"permissions": LEAD_PERMS}
    )

    def person(role, branches=(here,)):
        made = member.registered(company, role, home_branch=branches[0] if branches else None)
        made.branches.set(branches)
        return made

    return Shop(
        company=company,
        here=here,
        there=there,
        owner=person("Owner", (here, there)),
        manager=person("Manager", (here, there)),
        lead=person("Branch lead"),
        worker=person("Employee"),
        colleague=person("Employee", (there,)),
    )


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
