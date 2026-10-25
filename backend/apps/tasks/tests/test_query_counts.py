"""The mini app's hot endpoints cost the same number of queries whatever the rows, and the task
queries stay small enough for Postgres to plan quickly (the 17-table join of every relation
took longer to plan than to run: 250 ms for a dashboard page)."""

from datetime import timedelta
from string import ascii_uppercase

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.projects.tests.factories import card, project, team
from apps.tasks import queries
from apps.tasks.models import ChecklistItem, Task, TaskComment
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory

pytestmark = pytest.mark.django_db

# A fresh project key for every project give_work opens.
KEYS = (f"R{first}{second}" for first in ascii_uppercase for second in ascii_uppercase)


def app_for(membership) -> APIClient:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(membership.user)}")
    return api


def queries_of(api: APIClient, url: str) -> list[str]:
    api.get(url)  # warm what's cached per process
    with CaptureQueriesContext(connection) as captured:
        response = api.get(url)
    assert response.status_code == 200, response.content
    return [query["sql"] for query in captured.captured_queries]


@pytest.fixture
def people(company, member):
    return team(company, member)


def give_work(people, n: int) -> None:
    """`n` rounds of every kind of task a person's lists show, with every relation filled."""
    now = timezone.now()
    worker, boss = people["aziz"], people["manager"]
    routine = TaskTemplateFactory(company=worker.company, created_by=boss)
    key = next(KEYS)
    reno = project(worker.company, people["owner"], name=f"Opening {key}", key=key)
    for index in range(n):
        given = TaskFactory(
            assignee=worker,
            created_by=boss,
            branch=worker.home_branch,
            due_at=now + timedelta(hours=index + 1),
        )
        ChecklistItem.objects.create(task=given, text="Step", order=0)
        TaskComment.objects.create(task=given, author=boss, text="Note")
        TaskFactory(
            assignee=worker,
            created_by=boss,
            template=routine,
            kind=Task.Kind.DAILY,
            for_date=(now - timedelta(days=index)).date(),
            due_at=now - timedelta(hours=1),
            escalate_to=boss,
        )
        TaskFactory(
            assignee=worker,
            created_by=boss,
            status=Task.Status.DONE,
            completed_at=now,
            confirmed_by=boss,
            confirmed_at=now,
        )
        card(reno, people["owner"], assignee=worker, title=f"Card {index}")


@pytest.mark.parametrize("scope", ["board", "today", "mine"])
def test_the_lists_cost_the_same_whatever_the_rows(people, scope):
    give_work(people, 1)
    api = app_for(people["aziz"])
    url = f"/api/v1/companies/{people['aziz'].company_id}/tasks/?scope={scope}&page_size=200"
    few = len(queries_of(api, url))

    give_work(people, 4)
    many = queries_of(api, url)

    assert len(many) <= few
    assert len(api.get(url).data["results"]) > 4


def test_one_task_and_its_comments_cost_the_same_whatever_the_rows(people):
    give_work(people, 1)
    worker = people["aziz"]
    task = Task.objects.filter(assignee=worker, kind=Task.Kind.ASSIGNED).first()
    api = app_for(worker)
    base = f"/api/v1/companies/{worker.company_id}/tasks/{task.pk}"
    one = (len(queries_of(api, f"{base}/")), len(queries_of(api, f"{base}/comments/")))

    for n in range(5):
        TaskComment.objects.create(task=task, author=people["manager"], text=f"More {n}")
    more = (len(queries_of(api, f"{base}/")), len(queries_of(api, f"{base}/comments/")))

    assert more == one


def test_the_review_queue_costs_the_same_whatever_the_rows(people):
    boss = people["manager"]
    now = timezone.now()

    def waiting(n):
        for _ in range(n):
            TaskFactory(
                assignee=people["aziz"],
                created_by=boss,
                status=Task.Status.REVIEW,
                needs_confirmation=True,
                completed_at=now,
            )

    waiting(1)
    api = app_for(boss)
    url = f"/api/v1/companies/{boss.company_id}/tasks/?scope=review&page_size=200"
    few = len(queries_of(api, url))
    waiting(6)

    assert len(queries_of(api, url)) <= few


def test_task_queries_join_only_the_assignee(people):
    """Every other relation comes with a small query of its own (`queries.with_relations`)."""
    give_work(people, 1)
    worker = people["aziz"]
    sql = str(queries.visible_tasks(worker).query)
    main = sql.split(" WHERE ")[0]

    assert main.count(" JOIN ") <= 3
    with CaptureQueriesContext(connection) as captured:
        tasks = list(queries.board_tasks(worker, timezone.now()))
        for task in tasks:  # what cards and serializers read
            _ = (task.company.name, task.assignee.user.pk, task.branch)
            _ = (task.created_by and task.created_by.user.pk, task.confirmed_by)
            _ = (task.template and task.template.reminder_policy, task.escalate_to)
            _ = (getattr(task, "card", None), task.project, task.reminder_policy)
    count = len(captured.captured_queries)

    give_work(people, 3)
    with CaptureQueriesContext(connection) as captured:
        tasks = list(queries.board_tasks(worker, timezone.now()))
        for task in tasks:
            _ = (task.company.name, task.assignee.user.pk, task.branch)
            _ = (task.created_by and task.created_by.user.pk, task.confirmed_by)
            _ = (task.template and task.template.reminder_policy, task.escalate_to)
            _ = (getattr(task, "card", None), task.project, task.reminder_policy)

    assert len(captured.captured_queries) == count
