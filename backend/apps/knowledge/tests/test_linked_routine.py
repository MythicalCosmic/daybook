"""The mini app's "How to do this" on a task: pages linked to the task, and to the routine that
made it (the mini app's task has no routine id, and the link search leaves such tasks out)."""

import pytest
from django.utils import timezone

from apps.knowledge import demo
from apps.knowledge.models import PageLink
from apps.knowledge.tests.factories import PageFactory, SpaceFactory
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory

pytestmark = pytest.mark.django_db


def linked(api, company, task) -> list[str]:
    response = api.get(
        f"/api/v1/companies/{company.pk}/knowledge/linked/",
        {"target_type": "task", "target_id": task.pk},
    )
    assert response.status_code == 200
    return [row["page"]["title"] for row in response.data]


@pytest.fixture
def handbook(company):
    return SpaceFactory(company=company, name="Handbook")


@pytest.fixture
def opening(company, cashier, handbook):
    """The "Open the till" routine, today's task it made for the cashier, and its page."""
    routine = TaskTemplateFactory(company=company, title="Open the till", assignees=[cashier])
    task = TaskFactory(
        assignee=cashier,
        created_by=None,
        kind=Task.Kind.DAILY,
        template=routine,
        title="Open the till",
    )
    page = PageFactory(space=handbook, title="How we open the till")
    PageLink.objects.create(company=company, page=page, target_type="routine", target_id=routine.pk)
    return routine, task


def test_a_routine_task_shows_its_routines_pages_with_its_own(
    company, api_as, cashier, handbook, opening
):
    _routine, task = opening
    own = PageFactory(space=handbook, title="Today: the new float")
    PageLink.objects.create(company=company, page=own, target_type="task", target_id=task.pk)

    assert linked(api_as(cashier), company, task) == [
        "How we open the till",
        "Today: the new float",
    ]


def test_the_routine_link_is_listed_as_the_routines(company, api_as, cashier, opening):
    routine, task = opening

    rows = (
        api_as(cashier)
        .get(
            f"/api/v1/companies/{company.pk}/knowledge/linked/",
            {"target_type": "task", "target_id": task.pk},
        )
        .data
    )

    assert [(row["target_type"], row["target_id"]) for row in rows] == [("routine", routine.pk)]


def test_someone_who_cant_see_the_task_gets_nothing(company, api_as, cook, opening):
    _routine, task = opening

    assert linked(api_as(cook), company, task) == []


def test_a_task_without_a_routine_shows_only_its_own(company, api_as, cashier, handbook, opening):
    plain = TaskFactory(assignee=cashier, title="Call the landlord")

    assert linked(api_as(cashier), company, plain) == []


def test_asking_for_the_routine_itself_still_works(company, api_as, cashier, opening):
    routine, _task = opening

    response = api_as(cashier).get(
        f"/api/v1/companies/{company.pk}/knowledge/linked/",
        {"target_type": "routine", "target_id": routine.pk},
    )

    assert [row["page"]["title"] for row in response.data] == ["How we open the till"]


def test_the_demo_shows_how_to_on_a_pharmacists_routine(company, demo_people, api_as):
    """The demo links a page its routine's people can read, so the mini app shows it."""
    from apps.core import demo_plan

    people = demo_people(company)
    worker = people["worker"]
    routine = TaskTemplateFactory(
        company=company, title=demo_plan.TELEGRAM_ORDERS, assignees=[worker]
    )
    task = TaskFactory(
        assignee=worker,
        created_by=None,
        kind=Task.Kind.DAILY,
        template=routine,
        title=routine.title,
    )

    demo.seed(company, people, timezone.now())

    assert linked(api_as(worker), company, task) == ["Xaridor bilan muloqot"]
