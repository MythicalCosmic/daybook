"""The Wave 0 project models that tasks link to (Package T builds the rest)."""

import pytest
from django.db import DataError, IntegrityError, transaction
from django.db.models import ProtectedError

from apps.projects.models import Milestone, Project, ProjectList
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


def project(company, key="RENO", **fields) -> Project:
    return Project.objects.create(company=company, name="Branch opening", key=key, **fields)


def test_a_new_project_is_private_to_its_members_and_planned(company):
    reno = project(company)

    assert reno.status == Project.Status.PLANNING
    assert reno.visibility == Project.Visibility.MEMBERS
    assert reno.budget is None
    assert reno.budget_currency == "UZS"
    assert str(reno) == "RENO Branch opening"


@pytest.mark.parametrize("key", ["R", "RENOVATE", "reno", "RE-1", "R3NO"])
def test_keys_are_two_to_six_capital_letters(company, key):
    with pytest.raises((IntegrityError, DataError)), transaction.atomic():
        project(company, key=key)


def test_keys_are_unique_per_company(company, other_company):
    project(company)
    project(other_company)  # another company may use it

    with pytest.raises(IntegrityError), transaction.atomic():
        project(company)


def test_a_project_has_at_most_one_done_list(company):
    reno = project(company)
    ProjectList.objects.create(project=reno, name="To do")
    ProjectList.objects.create(project=reno, name="Done", is_done=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectList.objects.create(project=reno, name="Shipped", is_done=True)


def test_tasks_sit_on_a_project_board(company, member):
    reno = project(company)
    doing = ProjectList.objects.create(project=reno, name="In progress", position=2)
    launch = Milestone.objects.create(project=reno, name="Launch")
    worker = member(company)
    card = TaskFactory(
        assignee=worker, project=reno, project_list=doing, milestone=launch, list_position=1.5
    )

    assert list(reno.tasks.all()) == [card]
    assert list(doing.tasks.all()) == [card]
    assert list(launch.tasks.all()) == [card]

    doing.delete()
    launch.delete()
    card.refresh_from_db()
    assert card.project_list is None  # the card stays on the project
    assert card.milestone is None
    with pytest.raises(ProtectedError):
        reno.delete()  # a project with tasks is archived, not deleted
