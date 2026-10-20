"""Other people's personal tasks (docs/PLAN-OWNER.md §0, §3.2): only owners see them, only while
the company setting is on, on the owner API; the AI tools never send any personal task."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.tools.testing import call_tool
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, make_shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


@pytest.fixture
def personal(shop):
    return TaskFactory(
        assignee=shop.worker,
        title="Pick up my sister",
        branch=shop.here,
        due_at=timezone.now() + timedelta(hours=2),
    )


def listed(owner_api, member, company) -> set[int]:
    response = owner_api(member).get(
        f"/api/v1/owner/companies/{company.pk}/tasks/", {"page_size": 200}
    )
    return {row["id"] for row in response.json()["results"]}


def detail(owner_api, member, task):
    return owner_api(member).get(f"/api/v1/owner/companies/{task.company_id}/tasks/{task.pk}/")


def test_owners_see_personal_tasks_while_the_setting_is_on(shop, personal, owner_api):
    assert personal.kind == Task.Kind.PERSONAL
    assert personal.pk in listed(owner_api, shop.owner, shop.company)
    assert detail(owner_api, shop.owner, personal).status_code == 200

    shop.company.owner_sees_personal_tasks = False
    shop.company.save()
    assert personal.pk not in listed(owner_api, shop.owner, shop.company)
    assert detail(owner_api, shop.owner, personal).status_code == 404


def test_managers_never_see_other_peoples_personal_tasks(shop, personal, owner_api):
    # A manager holds tasks.view_all and branches.all, and still doesn't see it.
    assert personal.pk not in listed(owner_api, shop.manager, shop.company)
    assert detail(owner_api, shop.manager, personal).status_code == 404
    board = (
        owner_api(shop.manager)
        .get(f"/api/v1/owner/companies/{shop.company.pk}/tasks/board/")
        .json()
    )
    assert all(card["id"] != personal.pk for column in board["columns"] for card in column["items"])
    search = owner_api(shop.manager).get(
        f"/api/v1/owner/companies/{shop.company.pk}/search/", {"q": "sister"}
    )
    assert search.json()["results"] == []


def test_owners_find_personal_tasks_in_search_too(shop, personal, owner_api):
    search = owner_api(shop.owner).get(
        f"/api/v1/owner/companies/{shop.company.pk}/search/", {"q": "sister"}
    )
    assert [hit["id"] for hit in search.json()["results"]] == [personal.pk]


def test_ai_tools_never_send_personal_tasks(shop, personal):
    shared = TaskFactory(
        assignee=shop.worker, created_by=shop.owner, title="Count the till", branch=shop.here
    )
    found = call_tool("tasks_search", shop.owner)
    assert [row["id"] for row in found["rows"]] == [shared.pk]
    assert call_tool("tasks_get", shop.owner, task_id=personal.pk) == {"error": "not_found"}
    assert (
        call_tool("tasks_get", shop.owner, task_id=shared.pk)["data"]["title"] == "Count the till"
    )


def test_ai_tools_follow_branch_scope_and_permissions(shop, member):
    there = TaskFactory(assignee=shop.colleague, created_by=shop.owner, branch=shop.there)
    here = TaskFactory(assignee=shop.worker, created_by=shop.owner, branch=shop.here)
    assert [row["id"] for row in call_tool("tasks_search", shop.lead)["rows"]] == [here.pk]
    assert call_tool("tasks_get", shop.lead, task_id=there.pk) == {"error": "not_found"}
    employee = member.registered(shop.company)
    assert call_tool("tasks_search", employee) == {"error": "not_allowed"}


def test_ai_tools_share_free_text_only_with_the_switch(shop):
    task = TaskFactory(
        assignee=shop.worker,
        created_by=shop.owner,
        branch=shop.here,
        description="Call +998 90 123 45 67",
    )
    task.comments.create(author=shop.owner, text="Ask Akmal")
    with_text = call_tool("tasks_get", shop.owner, task_id=task.pk)["data"]
    assert with_text["comments"][0]["text"] == "Ask Akmal"
    assert "998" not in with_text["description"]  # phone numbers are scrubbed
    without = call_tool("tasks_get", shop.owner, task_id=task.pk, _switches=frozenset())["data"]
    assert "description" not in without and "comments" not in without
