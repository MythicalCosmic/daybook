"""No N+1 on the tasks owner lists (docs/PLAN-OWNER.md §11.2): the number of queries a list
endpoint makes doesn't grow with its rows."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.tasks.models import ChecklistItem, Proof, Task, TaskComment
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory, jpeg, make_shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


def owner_path(company, path):
    return f"/api/v1/owner/companies/{company.pk}/{path}"


def add_work(shop, routine, n: int, start: int = 0) -> None:
    """`n` tasks of every kind the lists show: open, late, waiting with a photo, finished."""
    now = timezone.now()
    for index in range(start, start + n):
        for person in (shop.worker, shop.colleague):
            open_task = TaskFactory(
                assignee=person,
                created_by=shop.owner,
                branch=person.home_branch,
                due_at=now + timedelta(hours=index + 1),
                reward="25000.00",
            )
            ChecklistItem.objects.create(task=open_task, text="Step", order=0)
            TaskComment.objects.create(task=open_task, author=shop.owner, text="Note")
            TaskFactory(
                assignee=person,
                created_by=shop.owner,
                branch=person.home_branch,
                due_at=now - timedelta(hours=index + 1),
                template=routine,
                kind=Task.Kind.DAILY,
                for_date=(now - timedelta(days=index)).date(),
            )
            review = TaskFactory(
                assignee=person,
                created_by=shop.owner,
                branch=person.home_branch,
                due_at=now + timedelta(hours=2),
                status=Task.Status.REVIEW,
                needs_confirmation=True,
                proof=Proof.PHOTO,
                completed_at=now - timedelta(minutes=index + 1),
            )
            review.proof_photo.save("p.jpg", jpeg(), save=True)


def queries_for(client, url, params=None) -> int:
    with CaptureQueriesContext(connection) as context:
        response = client.get(url, params or {})
    assert response.status_code == 200, response.content
    return len(context.captured_queries)


@pytest.mark.parametrize(
    "path,params",
    [
        ("tasks/", {}),
        ("tasks/", {"status": "review", "ordering": "-priority"}),
        ("tasks/board/", {}),
        ("tasks/calendar/", "calendar"),
        ("tasks/reviews/", {}),
        ("tasks/summary/", {}),
        ("proofs/", {}),
        ("routines/", {}),
        ("reminder-log/", {}),
        ("blocked-bot/", {}),
        ("reports/team/", {"preset": "last_30", "compare": "prev"}),
        ("reports/team/", {"preset": "last_30", "group_by": "routine"}),
        ("reports/routines/", {"preset": "last_30"}),
    ],
)
def test_lists_dont_query_per_row(shop, owner_api, path, params):
    routine = TaskTemplateFactory(
        company=shop.company, title="Shelves", assignees=[shop.worker, shop.colleague]
    )
    if params == "calendar":
        today = timezone.localdate(timezone=ZoneInfo(shop.company.timezone))
        params = {
            "from": (today - timedelta(days=10)).isoformat(),
            "to": (today + timedelta(days=10)).isoformat(),
        }
    client = owner_api(shop.owner)
    add_work(shop, routine, 2)
    client.get(owner_path(shop.company, path), params)  # warm caches (permissions, pulse)
    few = queries_for(client, owner_path(shop.company, path), params)
    add_work(shop, routine, 6, start=2)
    many = queries_for(client, owner_path(shop.company, path), params)
    assert many == few, f"{path}: {few} queries for a few rows, {many} for more"
