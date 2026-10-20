"""Helpers that make projects the way the app does (through the services), for tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.members.models import Membership
from apps.projects import services
from apps.projects.models import Project
from apps.tasks.models import Task


def team(company, member) -> dict[str, Membership]:
    """An owner, a manager and two employees, all registered, in the company's first branch."""
    branch = company.branches.order_by("order", "pk").first()
    people = {
        "owner": member.registered(company, "Owner", first_name="Dilnoza", home_branch=branch),
        "manager": member.registered(company, "Manager", first_name="Bekzod", home_branch=branch),
        "aziz": member.registered(company, first_name="Aziz", home_branch=branch),
        "madina": member.registered(company, first_name="Madina", home_branch=branch),
    }
    for person in people.values():
        person.branches.add(branch)
    return people


def project(company, by: Membership, *, name="Chilonzor branch opening", **fields) -> Project:
    return services.create_project(company, by=by, name=name, **fields)


def card(project: Project, by: Membership, title="Paint the walls", **fields) -> Task:
    fields.setdefault("due_at", timezone.now() + timedelta(days=3))
    return services.create_card(project, by=by, title=title, **fields)


def lists(project: Project) -> dict[str, object]:
    return {row.name: row for row in project.lists.all()}


MONEY = Decimal("120000000")
