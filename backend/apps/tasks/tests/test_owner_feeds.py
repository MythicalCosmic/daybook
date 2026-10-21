"""What tasks register with the console (docs/PLAN-OWNER.md §2.5, §13): queue, pulse, stream,
branch and company facts, the brief section, the calendar source, the exporter, History and
the employee endpoints for search and the week calendar; plus the bot touchpoints."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.console import contracts, registry
from apps.exports.registry import get_exporter
from apps.tasks import bot_messages, feeds
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, jpeg, make_shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


def owner_path(company, path):
    return f"/api/v1/owner/companies/{company.pk}/{path}"


def shared(shop, person, **fields):
    return TaskFactory(assignee=person, created_by=shop.owner, branch=person.home_branch, **fields)


def test_reviews_wait_in_needs_you_and_can_be_decided_there(shop, owner_api):
    task = shared(
        shop,
        shop.worker,
        status=Task.Status.REVIEW,
        needs_confirmation=True,
        completed_at=timezone.now(),
    )
    client = owner_api(shop.owner)
    items = client.get(owner_path(shop.company, "queue/")).json()["items"]
    item = next(item for item in items if item["kind"] == "tasks.review")
    assert item["id"] == task.pk
    accept, send_back = item["actions"]
    assert send_back["needs_reason"] is True
    assert client.post(owner_path(shop.company, accept["endpoint"])).status_code == 200
    task.refresh_from_db()
    assert task.status == Task.Status.DONE


def test_pulse_counts_late_work_and_checks(shop, owner_api):
    shared(shop, shop.worker, due_at=timezone.now() - timedelta(hours=1))
    shared(shop, shop.worker, status=Task.Status.REVIEW, needs_confirmation=True)
    counters = owner_api(shop.owner).get(owner_path(shop.company, "pulse/")).json()["counters"]
    assert counters["tasks.late_now"] == 1 and counters["tasks.review"] == 1
    lead = owner_api(shop.lead).get(owner_path(shop.company, "pulse/")).json()["counters"]
    assert lead["tasks.late_now"] == 1


def test_a_saved_task_moves_its_pulse_version(shop, owner_api):
    def version() -> int:
        body = owner_api(shop.owner).get(owner_path(shop.company, "pulse/")).json()
        return int(body["versions"]["tasks.tasks"])

    before = version()
    task = shared(shop, shop.worker)
    assert version() > before

    # The reminder engine's bookkeeping alone moves nothing (it runs every minute).
    moved = version()
    task.reminders_sent = 1
    task.save(update_fields=["reminders_sent", "next_reminder_at", "updated_at"])
    assert version() == moved
    task.title = "Recount the till"
    task.save(update_fields=["title", "updated_at"])
    assert version() > moved


def test_the_stream_shows_finished_work_with_its_photo(shop, owner_api):
    task = shared(shop, shop.worker, status=Task.Status.DONE, completed_at=timezone.now())
    task.proof_photo.save("x.jpg", jpeg(), save=True)
    TaskFactory(
        assignee=shop.worker, status=Task.Status.DONE, completed_at=timezone.now()
    )  # personal
    items = owner_api(shop.owner).get(owner_path(shop.company, "stream/")).json()["items"]
    done = [item for item in items if item["kind"] == "tasks.done"]
    assert len(done) == 1 and done[0]["photo_url"].startswith("/media/proofs/")
    assert done[0]["actor"]["id"] == shop.worker.pk


def test_branch_facts_fit_their_shape_and_scope(shop):
    now = timezone.now()
    shared(shop, shop.worker, due_at=now + timedelta(minutes=30))
    shared(shop, shop.worker, due_at=now - timedelta(minutes=30))
    shared(shop, shop.colleague, due_at=now + timedelta(minutes=10), status=Task.Status.DONE)
    today = timezone.localtime(now).date()
    facts = feeds.branch_facts(shop.company, today, now, None)
    for value in facts.values():
        assert contracts.problems(contracts.TasksFacts, value) == []
    scoped = feeds.branch_facts(shop.company, today, now, [shop.here.pk])
    assert set(scoped) <= {shop.here.pk}


def test_company_facts_and_the_brief_section(shop):
    now = timezone.now()
    shared(shop, shop.worker, due_at=now - timedelta(minutes=30))
    facts = feeds.company_facts(shop.company, None, shop.owner)
    assert contracts.problems(contracts.TasksCompanyFacts, facts) == []
    brief = feeds.brief(shop.company, timezone.localtime(now).date(), now, None)
    assert brief["late"] == 1 and brief["late_tasks"][0]["assignee"]["id"] == shop.worker.pk
    quiet = feeds.brief(shop.company, timezone.localtime(now).date(), now, [shop.there.pk])
    assert quiet is None


def test_the_calendar_source_counts_tasks_per_day(shop):
    now = timezone.now()
    shared(shop, shop.worker, due_at=now + timedelta(days=1))
    shared(shop, shop.worker, due_at=now + timedelta(days=1, minutes=5))
    start, end = timezone.localtime(now).date(), timezone.localtime(now).date() + timedelta(days=7)
    items = registry.collect_calendar(shop.owner, start, end, sources=["tasks.due"])
    assert len(items) == 1 and items[0].kind == "tasks.due" and "2" in items[0].title


def test_the_exporter_uses_the_tables_filters(shop):
    shared(shop, shop.worker, title="Inventory", reward=Decimal("1000"))
    shared(shop, shop.colleague, title="Elsewhere")
    exporter = get_exporter("tasks.list")
    rows = list(exporter.rows(shop.lead, {"q": "Inventory"}))
    assert [row["title"] for row in rows] == ["Inventory"] and rows[0]["reward"] == Decimal(
        "1000.00"
    )
    assert [row["title"] for row in exporter.rows(shop.lead, {})] == ["Inventory"]


def test_history_of_a_task_follows_its_visibility(shop, owner_api):
    here = shared(shop, shop.worker, due_at=timezone.now() + timedelta(hours=2))
    there = shared(shop, shop.colleague)
    owner_api(shop.owner).patch(
        owner_path(shop.company, f"tasks/{here.pk}/"), {"priority": "high"}, format="json"
    )
    history = owner_api(shop.lead).get(
        owner_path(shop.company, "audit/records/"), {"target_type": "task", "target_id": here.pk}
    )
    assert history.status_code == 200 and history.json()["results"][0]["action"] == "task.changed"
    hidden = owner_api(shop.lead).get(
        owner_path(shop.company, "audit/records/"), {"target_type": "task", "target_id": there.pk}
    )
    assert hidden.status_code == 404


def test_employees_search_their_tasks_and_see_a_week(shop, api_as):
    now = timezone.now()
    mine = shared(shop, shop.worker, title="Order receipt rolls", due_at=now + timedelta(days=1))
    shared(shop, shop.worker, title="Water the plants", due_at=now + timedelta(days=2))
    shared(shop, shop.colleague, title="Order more boxes", due_at=now + timedelta(days=1))
    client = api_as(shop.worker)
    found = client.get(f"/api/v1/companies/{shop.company.pk}/tasks/", {"q": "order"}).json()[
        "results"
    ]
    assert [row["id"] for row in found] == [mine.pk]
    start = timezone.localtime(now).date()
    week = client.get(
        f"/api/v1/companies/{shop.company.pk}/tasks/calendar/",
        {"from": start.isoformat(), "to": (start + timedelta(days=6)).isoformat()},
    ).json()
    assert {row["title"] for row in week["tasks"]} == {"Order receipt rolls", "Water the plants"}
    assert sum(day["total"] for day in week["days"]) == 2
    too_long = client.get(
        f"/api/v1/companies/{shop.company.pk}/tasks/calendar/",
        {"from": "2026-01-01", "to": "2026-03-01"},
    )
    assert too_long.status_code == 400


def test_bot_messages_show_the_reward_and_the_project_key(shop):
    from apps.projects.models import Project

    project = Project.objects.create(company=shop.company, name="Chilonzor opening", key="CHL")
    task = shared(
        shop, shop.worker, title="Paint the wall", reward=Decimal("50000"), project=project
    )
    text, _markup = bot_messages.task_card(task, shop.worker, timezone.now())
    assert "CHL-1 · Paint the wall" in text
    assert "50 000" in text
    text, _ = bot_messages.nudge(task, shop.owner, timezone.now())
    assert str(shop.owner) in text


def test_task_messages_carry_the_card_key(shop, django_assert_num_queries):
    from apps.projects.models import Card, Project
    from apps.reminders import bot_messages as reminder_messages
    from apps.tasks.models import Proof
    from apps.tasks.queries import TASK_RELATIONS

    project = Project.objects.create(company=shop.company, name="Renovation", key="RENO")
    shared(shop, shop.worker, title="Order tiles", project=project)
    task = shared(
        shop,
        shop.worker,
        title="Paint the wall",
        project=project,
        proof=Proof.PHOTO,
        due_at=timezone.now() + timedelta(hours=2),
    )
    plain = shared(shop, shop.worker, title="Water the plants")
    now = timezone.now()

    task = Task.objects.select_related(*TASK_RELATIONS).get(pk=task.pk)
    with django_assert_num_queries(0):
        assert bot_messages.display_title(task) == "RENO-2 · Paint the wall"
    plain = Task.objects.select_related(*TASK_RELATIONS).get(pk=plain.pk)
    assert bot_messages.display_title(plain) == "Water the plants"
    _text, markup = bot_messages.task_list([task, plain], now)
    labels = [row[0].text for row in markup.inline_keyboard]
    assert "RENO-2 · Paint the wall" in labels[0] and "RENO" not in labels[1]
    assert "RENO-2 · Paint the wall" in bot_messages.proof_request(task)[0]
    assert "RENO-2 · Paint the wall" in reminder_messages.heads_up(task)[0]
    assert "RENO-2 · Paint the wall" in reminder_messages.escalation(task, now)[0]
    # Until the board gives it a card, the project's key alone.
    Card.objects.filter(task=task).delete()
    task = Task.objects.select_related(*TASK_RELATIONS).get(pk=task.pk)
    assert bot_messages.display_title(task) == "RENO · Paint the wall"
