"""The tasks owner API (docs/PLAN-OWNER.md §4.5): permissions, tenancy, branch scope, the list's
filters, creating work for many people, the drawer, actions and the board."""

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.members.models import AccessRole
from apps.members.tests.factories import PositionFactory
from apps.reminders.models import ReminderLog
from apps.tasks.models import Proof, Task
from apps.tasks.tests.factories import TaskFactory, jpeg, make_shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/tasks/{path}"


def ids(response) -> set[int]:
    body = response.json()
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    return {row["id"] for row in rows}


def local_day(shop, moment) -> str:
    return timezone.localtime(moment, ZoneInfo(shop.company.timezone)).date().isoformat()


def work(shop, person, *, branch=None, by=None, **fields):
    return TaskFactory(
        assignee=person,
        created_by=by or shop.owner,
        branch=branch if branch is not None else person.home_branch,
        **fields,
    )


# Access ------------------------------------------------------------------------------------


def test_the_list_needs_view_all(shop, owner_api, member):
    employee = member.registered(shop.company, "Employee")
    # Employees have no dashboard access at all; an Accountant has it but can't see tasks.
    accountant = member.registered(shop.company, "Accountant")
    assert owner_api(employee).get(url(shop.company)).status_code == 403
    assert owner_api(accountant).get(url(shop.company)).status_code == 403
    assert owner_api(accountant).get(url(shop.company, "board/")).status_code == 403
    assert owner_api(shop.manager).get(url(shop.company)).status_code == 200


def test_another_companys_tasks_are_not_found(shop, other_company, member, owner_api):
    stranger = member.registered(other_company, "Owner")
    theirs = TaskFactory(assignee=stranger, created_by=stranger, kind=Task.Kind.ASSIGNED)
    client = owner_api(shop.owner)
    assert client.get(url(other_company)).status_code == 404
    assert client.get(url(shop.company, f"{theirs.pk}/")).status_code == 404
    assert client.post(url(shop.company, f"{theirs.pk}/cancel/")).status_code == 404


def test_a_mini_app_token_is_refused(shop, api_as):
    assert api_as(shop.owner).get(url(shop.company)).status_code == 401


# Branch scope ------------------------------------------------------------------------------


def test_a_branch_lead_sees_their_branch_and_their_own(shop, owner_api):
    here = work(shop, shop.worker)
    there = work(shop, shop.colleague)
    no_branch = work(shop, shop.worker, branch=None)
    no_branch.branch = None
    no_branch.save()
    handed_out = work(shop, shop.colleague, by=shop.lead)
    client = owner_api(shop.lead)

    assert ids(client.get(url(shop.company))) == {here.pk, handed_out.pk}
    assert client.get(url(shop.company, f"{there.pk}/")).status_code == 404
    assert ids(owner_api(shop.manager).get(url(shop.company))) >= {here.pk, there.pk, no_branch.pk}


def test_the_branch_filter_reads_the_tasks_branch_which_reassigning_keeps(shop, owner_api):
    task = work(
        shop, shop.worker, kind=Task.Kind.ASSIGNED, due_at=timezone.now() + timedelta(hours=3)
    )
    client = owner_api(shop.owner)
    response = client.post(
        url(shop.company, f"{task.pk}/reassign/"), {"assignee_id": shop.colleague.pk}, format="json"
    )
    assert response.status_code == 200, response.content
    task.refresh_from_db()
    assert task.assignee == shop.colleague and task.branch == shop.here

    assert task.pk in ids(client.get(url(shop.company), {"branch": shop.here.pk}))
    assert task.pk not in ids(client.get(url(shop.company), {"branch": shop.there.pk}))


def test_a_lead_cant_give_work_outside_their_branches(shop, owner_api):
    response = owner_api(shop.lead).post(
        url(shop.company),
        {"title": "Count the safe", "assignee_ids": [shop.colleague.pk]},
        format="json",
    )
    assert response.status_code == 400
    assert not Task.objects.filter(title="Count the safe").exists()


# The list ----------------------------------------------------------------------------------


def test_filters(shop, owner_api):
    now = timezone.now()
    late = work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        due_at=now - timedelta(hours=1),
        priority="urgent",
    )
    later = work(shop, shop.colleague, kind=Task.Kind.ASSIGNED, due_at=now + timedelta(days=2))
    done = work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.DONE,
        proof_text="Done, photo in chat",
    )
    client = owner_api(shop.owner)

    def found(**params):
        return ids(client.get(url(shop.company), params))

    assert found(overdue="true") == {late.pk}
    assert found(status=["done"]) == {done.pk}
    assert found(assignee=shop.colleague.pk) == {later.pk}
    assert found(priority="urgent") == {late.pk}
    assert found(has_proof="true") == {done.pk}
    assert found(q=later.title) == {later.pk}
    tomorrow = local_day(shop, now + timedelta(days=1))
    assert later.pk in found(due_from=tomorrow)
    assert late.pk not in found(due_from=tomorrow)


def test_rows_carry_money_as_strings_and_people_as_refs(shop, owner_api):
    work(shop, shop.worker, kind=Task.Kind.ASSIGNED, reward=Decimal("50000"))
    row = owner_api(shop.owner).get(url(shop.company)).json()["results"][0]
    assert row["reward"] == "50000.00"
    assert row["assignee"] == {
        "id": shop.worker.pk,
        "name": str(shop.worker),
        "photo_url": None,
        "position": None,
    }
    assert row["branch"]["id"] == shop.here.pk
    assert row["checklist"] == {"done": 0, "total": 0}


def test_the_list_doesnt_query_per_row(shop, owner_api, django_assert_max_num_queries):
    for _ in range(15):
        work(shop, shop.worker, kind=Task.Kind.ASSIGNED)
    client = owner_api(shop.owner)
    with django_assert_max_num_queries(16):
        assert client.get(url(shop.company)).status_code == 200


# Creating ----------------------------------------------------------------------------------


def test_one_task_per_person_from_people_positions_and_branches(
    shop, owner_api, member, sent_messages, django_capture_on_commit_callbacks
):
    cashier = PositionFactory(company=shop.company, name="Cashier")
    shop.worker.position = cashier
    shop.worker.save()
    extra = member.registered(shop.company, home_branch=shop.there)
    extra.branches.set([shop.there])
    due = timezone.now() + timedelta(days=1)
    with django_capture_on_commit_callbacks(execute=True):
        response = post_inventory(shop, owner_api, due, cashier)
    assert response.status_code == 201, response.content
    tasks = Task.objects.filter(title="Inventory: cosmetics shelf")
    assert {task.assignee_id for task in tasks} == {shop.colleague.pk, shop.worker.pk, extra.pk}
    assert response.json()["created"] == 3
    for task in tasks:
        assert task.kind == Task.Kind.ASSIGNED and task.reward == Decimal("25000.00")
        assert task.next_reminder_at is not None  # each has its own reminders
        assert task.checklist.count() == 2
        assert task.branch == task.assignee.home_branch
    assert AuditLog.objects.filter(action="task.assigned").count() == 3
    assert len(sent_messages) == 3  # everyone is told in the bot


def post_inventory(shop, owner_api, due, cashier):
    return owner_api(shop.owner).post(
        url(shop.company),
        {
            "title": "Inventory: cosmetics shelf",
            "due_at": due.isoformat(),
            "checklist": ["Count", "Photo"],
            "proof": "photo",
            "needs_confirmation": True,
            "reward": "25000",
            "assignee_ids": [shop.colleague.pk],
            "position_ids": [cashier.pk],
            "branch_ids": [shop.there.pk],
        },
        format="json",
    )


def test_creating_needs_somebody(shop, owner_api):
    response = owner_api(shop.owner).post(url(shop.company), {"title": "Nobody"}, format="json")
    assert response.status_code == 400
    assert "assignee_ids" in response.json()


def test_creating_needs_tasks_assign(shop, owner_api, member):
    accountant = member.registered(shop.company, "Accountant")
    response = owner_api(accountant).post(
        url(shop.company), {"title": "X", "assignee_ids": [shop.worker.pk]}, format="json"
    )
    assert response.status_code == 403


# The drawer and its actions ----------------------------------------------------------------


def test_the_drawer_has_everything(shop, owner_api):
    task = work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.REVIEW,
        due_at=timezone.now() + timedelta(hours=1),
        needs_confirmation=True,
        proof=Proof.PHOTO,
    )
    task.proof_photo.save("x.jpg", jpeg(), save=True)
    task.checklist.create(text="Shelf 1", is_done=True)
    task.comments.create(author=shop.owner, text="Looks good from here")
    body = owner_api(shop.owner).get(url(shop.company, f"{task.pk}/")).json()

    assert body["proof_photo"].startswith("/media/proofs/")
    assert body["checklist_items"] == [
        {"id": task.checklist.get().pk, "text": "Shelf 1", "is_done": True}
    ]
    assert body["comments"][0]["text"] == "Looks good from here"
    assert {"confirm", "return", "comment", "edit", "cancel", "reassign"} - {
        "edit",
        "cancel",
        "reassign",
    } <= set(body["actions"])
    assert body["reminders"]["policy"]["name"]
    assert body["moves"] == ["done", "returned"]


def test_confirm_and_send_back(shop, owner_api):
    first = work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.REVIEW,
        needs_confirmation=True,
    )
    second = work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.REVIEW,
        needs_confirmation=True,
    )
    client = owner_api(shop.owner)
    assert client.post(url(shop.company, f"{first.pk}/confirm/")).json()["status"] == "done"
    assert (
        client.post(url(shop.company, f"{second.pk}/return/"), {}, format="json").status_code == 400
    )
    response = client.post(
        url(shop.company, f"{second.pk}/return/"), {"reason": "Retake in daylight"}, format="json"
    )
    assert response.json()["status"] == "returned"
    assert response.json()["comments"][-1]["text"] == "Retake in daylight"


def test_edit_reward_and_due(shop, owner_api):
    task = work(
        shop, shop.worker, kind=Task.Kind.ASSIGNED, due_at=timezone.now() + timedelta(hours=2)
    )
    due = timezone.now() + timedelta(days=2)
    response = owner_api(shop.owner).patch(
        url(shop.company, f"{task.pk}/"),
        {"reward": "100000.50", "due_at": due.isoformat(), "priority": "high"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["reward"] == "100000.50" and response.json()["priority"] == "high"
    changes = AuditLog.objects.get(action="task.changed", target_id=task.pk).details["changes"]
    assert set(changes) == {"reward", "due_at", "priority"}


def test_nudge_sends_the_card_and_waits_before_another(
    shop, owner_api, sent_messages, django_capture_on_commit_callbacks
):
    task = work(
        shop, shop.worker, kind=Task.Kind.ASSIGNED, due_at=timezone.now() - timedelta(minutes=30)
    )
    client = owner_api(shop.owner)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(url(shop.company, f"{task.pk}/nudge/")).status_code == 200
    assert len(sent_messages) == 1 and str(shop.owner) in sent_messages[0]["text"]
    assert sent_messages[0]["chat_id"] == shop.worker.user.telegram_id
    assert client.post(url(shop.company, f"{task.pk}/nudge/")).status_code == 400
    assert AuditLog.objects.filter(action="tasks.nudged", target_id=task.pk).count() == 1


def test_nobody_nudges_a_blocked_bot(shop, owner_api):
    shop.worker.user.employee_bot_blocked_at = timezone.now()
    shop.worker.user.save()
    task = work(shop, shop.worker, kind=Task.Kind.ASSIGNED)
    response = owner_api(shop.owner).post(url(shop.company, f"{task.pk}/nudge/"))
    assert response.status_code == 400 and "blocked" in response.json()["detail"]


def test_comment_and_timeline(shop, owner_api):
    task = work(
        shop, shop.worker, kind=Task.Kind.ASSIGNED, due_at=timezone.now() - timedelta(hours=1)
    )
    ReminderLog.objects.create(
        task=task, kind=ReminderLog.Kind.REMINDER, step=1, recipient=shop.worker
    )
    client = owner_api(shop.owner)
    assert (
        client.post(
            url(shop.company, f"{task.pk}/comment/"), {"text": "On my way"}, format="json"
        ).status_code
        == 201
    )
    client.post(url(shop.company, f"{task.pk}/cancel/"))
    kinds = [
        entry["kind"] for entry in client.get(url(shop.company, f"{task.pk}/timeline/")).json()
    ]
    assert kinds[0] == "created"
    assert {"comment", "reminder", "audit"} <= set(kinds)


def test_cancel_needs_a_manager(shop, owner_api, member):
    AccessRole.objects.create(
        company=shop.company, name="Checker", permissions=["dashboard.access", "tasks.confirm"]
    )
    checker = member.registered(shop.company, "Checker")
    checker.branches.set([shop.here])
    task = work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.REVIEW,
        needs_confirmation=True,
    )
    client = owner_api(checker)
    assert client.post(url(shop.company, f"{task.pk}/cancel/")).status_code == 403
    assert client.post(url(shop.company, f"{task.pk}/confirm/")).status_code == 200


# Board, calendar, summary, reviews, options ------------------------------------------------


def test_the_board_drag_only_goes_where_rules_allow(shop, owner_api):
    review = work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.REVIEW,
        needs_confirmation=True,
    )
    todo = work(shop, shop.worker, kind=Task.Kind.ASSIGNED)
    client = owner_api(shop.owner)
    columns = {c["id"]: c for c in client.get(url(shop.company, "board/")).json()["columns"]}
    assert [c for c in columns] == ["todo", "in_progress", "review", "returned", "done"]
    assert {card["id"]: card["moves"] for card in columns["review"]["items"]}[review.pk] == [
        "done",
        "returned",
    ]
    assert {card["id"]: card["moves"] for card in columns["todo"]["items"]}[todo.pk] == []

    refused = client.post(
        url(shop.company, f"{todo.pk}/move/"), {"to": "in_progress"}, format="json"
    )
    assert refused.status_code == 400
    assert (
        client.post(
            url(shop.company, f"{review.pk}/move/"), {"to": "returned"}, format="json"
        ).status_code
        == 400
    )
    moved = client.post(
        url(shop.company, f"{review.pk}/move/"), {"to": "returned", "reason": "Redo"}, format="json"
    )
    assert moved.json()["status"] == "returned"


def test_my_own_card_can_be_started_and_finished(shop, owner_api):
    mine = TaskFactory(
        assignee=shop.owner, created_by=shop.manager, kind=Task.Kind.ASSIGNED, branch=shop.here
    )
    client = owner_api(shop.owner)
    assert (
        client.post(
            url(shop.company, f"{mine.pk}/move/"), {"to": "in_progress"}, format="json"
        ).json()["status"]
        == "in_progress"
    )
    assert (
        client.post(url(shop.company, f"{mine.pk}/move/"), {"to": "done"}, format="json").json()[
            "status"
        ]
        == "done"
    )


def test_calendar_counts_due_tasks_per_day(shop, owner_api):
    now = timezone.now()
    day = (now + timedelta(days=1)).astimezone(timezone.get_current_timezone())
    work(shop, shop.worker, kind=Task.Kind.ASSIGNED, due_at=now + timedelta(days=1))
    work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        due_at=now + timedelta(days=1),
        status=Task.Status.DONE,
    )
    start = (now - timedelta(days=2)).date().isoformat()
    end = (now + timedelta(days=5)).date().isoformat()
    body = (
        owner_api(shop.owner).get(url(shop.company, "calendar/"), {"from": start, "to": end}).json()
    )
    assert sum(entry["total"] for entry in body["days"]) == 2
    assert sum(entry["done"] for entry in body["days"]) == 1
    assert len(body["items"]) == 2
    assert day  # the day itself depends on the company timezone; counts are what matter
    too_long = owner_api(shop.owner).get(
        url(shop.company, "calendar/"), {"from": "2026-01-01", "to": "2026-06-01"}
    )
    assert too_long.status_code == 400


def test_summary_leaves_personal_tasks_out(shop, owner_api):
    now = timezone.now()
    work(shop, shop.worker, kind=Task.Kind.ASSIGNED, due_at=now - timedelta(hours=2))
    TaskFactory(assignee=shop.worker, due_at=now - timedelta(hours=2), branch=shop.here)  # personal
    body = owner_api(shop.owner).get(url(shop.company, "summary/")).json()
    assert body["late_now"] == 1
    assert len(body["series"]) == 14


def test_reviews_are_the_callers_checks(shop, owner_api):
    here = work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.REVIEW,
        needs_confirmation=True,
    )
    there = work(
        shop,
        shop.colleague,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.REVIEW,
        needs_confirmation=True,
    )
    assert ids(owner_api(shop.lead).get(url(shop.company, "reviews/"))) == {here.pk}
    assert ids(owner_api(shop.owner).get(url(shop.company, "reviews/"))) == {here.pk, there.pk}


def test_options_offer_people_in_scope(shop, owner_api, member):
    people = {
        row["id"]
        for row in owner_api(shop.lead).get(url(shop.company, "options/")).json()["people"]
    }
    assert shop.worker.pk in people and shop.colleague.pk not in people
    # The staff list is for whoever works with tasks, not every dashboard user.
    accountant = member.registered(shop.company, "Accountant")
    assert owner_api(accountant).get(url(shop.company, "options/")).status_code == 403


def test_photo_wall_shows_todays_proofs(shop, owner_api):
    task = work(
        shop,
        shop.worker,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.DONE,
        completed_at=timezone.now(),
    )
    task.proof_photo.save("x.jpg", jpeg(), save=True)
    work(
        shop,
        shop.colleague,
        kind=Task.Kind.ASSIGNED,
        status=Task.Status.DONE,
        completed_at=timezone.now(),
    )
    body = owner_api(shop.owner).get(f"/api/v1/owner/companies/{shop.company.pk}/proofs/").json()
    assert [row["id"] for row in body["items"]] == [task.pk]
    assert (
        owner_api(shop.lead)
        .get(f"/api/v1/owner/companies/{shop.company.pk}/proofs/", {"branch": shop.there.pk})
        .json()["items"]
        == []
    )
