"""Finished tasks accepted automatically (docs/PLAN-OWNER.md §15.3): the company's "When someone
finishes a task" rule, each mode for one-off tasks and routine runs, the timeout that accepts
work nobody reviewed, its audit row and notice, the settings API, and what people read."""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone, translation

from apps.audit.models import AuditLog
from apps.inbox.models import Notification
from apps.tasks import bot_messages, conf, generation, rules, services
from apps.tasks.audit_actions import TasksAction
from apps.tasks.models import OnFinish, Proof, Task, TasksSettings, TaskTemplate
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory, jpeg

pytestmark = pytest.mark.django_db

SETTINGS = "/api/v1/owner/companies/{}/tasks/settings/"


def photo() -> ContentFile:
    return jpeg("shelf.png")


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner")


def rule(company, on_finish=OnFinish.AUTO, hours=None) -> TasksSettings:
    row = conf.get_settings(company)
    row.on_finish, row.auto_accept_after_hours = on_finish, hours
    row.save()
    return row


def give(manager, worker, **fields) -> Task:
    return services.create_task(by=manager, assignee=worker, title="Count the fridge", **fields)


def waiting(manager, worker, *, hours_ago: float, **fields) -> Task:
    """Work finished `hours_ago` hours ago that waits for its check."""
    task = TaskFactory(
        assignee=worker,
        created_by=manager,
        needs_confirmation=True,
        status=Task.Status.REVIEW,
        completed_at=timezone.now() - timedelta(hours=hours_ago),
        **fields,
    )
    return task


# The setting ------------------------------------------------------------------------------


def test_a_new_company_accepts_finished_work_automatically_and_never_times_out(company):
    row = conf.get_settings(company)

    assert row.on_finish == OnFinish.AUTO
    assert row.auto_accept_after_hours is None


@pytest.mark.parametrize(
    ("on_finish", "expected"),
    [
        (OnFinish.AUTO, (False, False)),
        (OnFinish.PROOF, (True, True)),
        (OnFinish.ASK, (True, False)),
    ],
)
def test_the_rule_is_the_default_of_a_new_task(company, manager, worker, on_finish, expected):
    rule(company, on_finish)

    task = give(manager, worker)

    assert (task.needs_confirmation, task.accept_with_proof) == expected


@pytest.mark.parametrize("on_finish", list(OnFinish))
@pytest.mark.parametrize("choice", [True, False])
def test_a_tasks_own_choice_wins(company, manager, worker, on_finish, choice):
    rule(company, on_finish)

    task = give(manager, worker, needs_confirmation=choice)

    assert (task.needs_confirmation, task.accept_with_proof) == (choice, False)


def test_ones_own_task_never_waits_for_a_check(company, worker):
    rule(company, OnFinish.ASK)

    task = services.create_task(by=worker, title="Tidy the shelf")

    assert not task.needs_confirmation
    task = services.complete_task(task, by=worker)
    assert task.status == Task.Status.DONE
    assert not rules.accepted_automatically(task)  # just done: nobody gave it


# Finishing a one-off task -----------------------------------------------------------------


def test_accept_automatically_finishes_given_work_at_once(company, manager, worker):
    rule(company, OnFinish.AUTO)
    task = give(manager, worker)

    task = services.complete_task(task, by=worker)

    assert task.status == Task.Status.DONE
    assert rules.accepted_automatically(task)
    assert task.confirmed_by is None


@pytest.mark.parametrize(
    ("proof", "sent", "status"),
    [
        (Proof.NONE, {}, Task.Status.REVIEW),
        (Proof.NONE, {"proof_text": "Done, 4 °C"}, Task.Status.DONE),
        (Proof.ANY, {"proof_text": "All counted"}, Task.Status.DONE),
        (Proof.PHOTO, {"photo": True}, Task.Status.DONE),
    ],
)
def test_only_with_proof_accepts_work_that_brings_a_photo_or_text(
    company, manager, worker, proof, sent, status
):
    rule(company, OnFinish.PROOF)
    task = give(manager, worker, proof=proof)
    extra = {"proof_photo": photo()} if sent.pop("photo", False) else {}

    task = services.complete_task(task, by=worker, **sent, **extra)

    assert task.status == status
    assert rules.accepted_automatically(task) is (status == Task.Status.DONE)


def test_always_ask_sends_finished_work_for_a_check(company, manager, worker):
    rule(company, OnFinish.ASK)
    task = give(manager, worker, proof=Proof.TEXT)

    task = services.complete_task(task, by=worker, proof_text="Counted")

    assert task.status == Task.Status.REVIEW
    assert not rules.accepted_automatically(task)


def test_a_rule_change_leaves_tasks_already_given_alone(company, manager, worker):
    rule(company, OnFinish.ASK)
    task = give(manager, worker)
    rule(company, OnFinish.AUTO)

    assert services.complete_task(task, by=worker).status == Task.Status.REVIEW


def test_work_accepted_at_once_can_still_be_undone(company, manager, worker):
    task = services.complete_task(give(manager, worker), by=worker)

    task = services.reopen_task(task, by=worker)

    assert task.is_open
    assert not rules.accepted_automatically(task)


def test_a_confirmed_task_is_not_accepted_automatically(company, manager, worker):
    rule(company, OnFinish.ASK)
    task = services.complete_task(give(manager, worker), by=worker)

    task = services.confirm_task(task, by=manager)

    assert task.status == Task.Status.DONE
    assert not rules.accepted_automatically(task)


# Routine runs -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("on_finish", "expected"),
    [
        (OnFinish.AUTO, (False, False)),
        (OnFinish.PROOF, (True, True)),
        (OnFinish.ASK, (True, False)),
    ],
)
def test_a_new_routine_follows_the_rule(company, manager, worker, on_finish, expected):
    rule(company, on_finish)

    template = services.create_template(
        by=manager, title="Fridge temperature", due_time="09:00", assignees=[worker]
    )

    assert (template.needs_confirmation, template.accept_with_proof) == expected


def test_a_routines_own_choice_wins_and_null_goes_back_to_the_rule(company, manager, worker):
    rule(company, OnFinish.PROOF)
    template = services.create_template(
        by=manager, title="Shelves", due_time="09:00", needs_confirmation=False, assignees=[worker]
    )
    assert (template.needs_confirmation, template.accept_with_proof) == (False, False)

    template = services.update_template(template, by=manager, needs_confirmation=None)

    assert (template.needs_confirmation, template.accept_with_proof) == (True, True)
    template = services.update_template(template, by=manager, title="Shelves, all of them")
    assert (template.needs_confirmation, template.accept_with_proof) == (True, True)


@pytest.mark.parametrize(
    ("on_finish", "with_photo", "status"),
    [
        (OnFinish.AUTO, False, Task.Status.DONE),
        (OnFinish.PROOF, True, Task.Status.DONE),
        (OnFinish.PROOF, False, Task.Status.REVIEW),
        (OnFinish.ASK, True, Task.Status.REVIEW),
    ],
)
def test_a_routine_run_follows_its_routines_rule(
    company, manager, worker, on_finish, with_photo, status
):
    rule(company, on_finish)
    template = services.create_template(
        by=manager, title="Fridge photo", due_time="09:00", assignees=[worker]
    )
    now = timezone.now()
    [run] = Task.objects.bulk_create(
        generation.build_tasks(
            template,
            timezone.localdate(),
            now + timedelta(hours=1),
            people=[worker],
            created_by=manager,
            now=now,
        )
    )
    assert (run.needs_confirmation, run.accept_with_proof) == (
        template.needs_confirmation,
        template.accept_with_proof,
    )

    extra = {"proof_photo": photo()} if with_photo else {}
    run = services.complete_task(run, by=worker, **extra)

    assert run.status == status
    assert rules.accepted_automatically(run) is (status == Task.Status.DONE)


# The timeout ------------------------------------------------------------------------------


def test_nobody_reviewing_within_the_wait_accepts_the_work(
    company, manager, worker, django_capture_on_commit_callbacks
):
    rule(company, OnFinish.ASK, hours=4)
    late = waiting(manager, worker, hours_ago=5)
    recent = waiting(manager, worker, hours_ago=3)

    with django_capture_on_commit_callbacks():
        assert services.accept_overdue_reviews() == 1

    late.refresh_from_db()
    recent.refresh_from_db()
    assert late.status == Task.Status.DONE
    assert late.confirmed_at is not None and late.confirmed_by is None
    assert rules.accepted_automatically(late)
    assert recent.status == Task.Status.REVIEW
    row = AuditLog.objects.get(action=TasksAction.AUTO_ACCEPTED)
    assert (row.target_type, row.target_id, row.actor) == ("task", late.pk, None)
    assert row.details == {"hours": 4}


def test_the_checker_hears_in_plain_words(company, manager, worker):
    rule(company, OnFinish.ASK, hours=8)
    late = waiting(manager, worker, hours_ago=9, title="Count the cash")

    services.accept_overdue_reviews()

    notice = Notification.objects.get(kind="tasks.auto_accepted")
    assert notice.recipient == manager
    assert notice.target_id == late.pk
    assert "Count the cash" in notice.title
    assert "8 hours" in notice.body
    assert str(worker) in notice.body
    assert not any(ord(char) > 0x2FFF for char in notice.title + notice.body)  # no emoji


def test_the_timeout_is_idempotent(company, manager, worker):
    rule(company, OnFinish.ASK, hours=4)
    waiting(manager, worker, hours_ago=6)

    assert services.accept_overdue_reviews() == 1
    assert services.accept_overdue_reviews() == 0
    assert AuditLog.objects.filter(action=TasksAction.AUTO_ACCEPTED).count() == 1
    assert Notification.objects.filter(kind="tasks.auto_accepted").count() == 1


@pytest.mark.parametrize("status", [Task.Status.RETURNED, Task.Status.CANCELLED])
def test_the_timeout_never_accepts_returned_or_cancelled_work(company, manager, worker, status):
    rule(company, OnFinish.ASK, hours=4)
    task = waiting(manager, worker, hours_ago=10)
    Task.objects.filter(pk=task.pk).update(status=status)

    assert services.accept_overdue_reviews() == 0

    task.refresh_from_db()
    assert task.status == status


def test_without_a_wait_nothing_is_accepted(company, manager, worker):
    rule(company, OnFinish.ASK, hours=None)
    task = waiting(manager, worker, hours_ago=100)

    assert services.accept_overdue_reviews() == 0
    task.refresh_from_db()
    assert task.status == Task.Status.REVIEW


def test_the_beat_job_runs_the_timeout(company, manager, worker):
    from apps.tasks import tasks as jobs

    rule(company, OnFinish.ASK, hours=4)
    waiting(manager, worker, hours_ago=5)

    assert jobs.accept_overdue_reviews() == 1


# What people read ---------------------------------------------------------------------------


def test_the_card_says_accepted_not_sent_for_checking(company, manager, worker):
    task = services.complete_task(give(manager, worker), by=worker)
    now = timezone.now()

    with translation.override("uz"):
        text = bot_messages.card_text(task, worker, now)
        note = bot_messages.accepted_note(task)

    assert "Holati: Qabul qilindi" in text
    assert note == "Qabul qilindi"


def test_the_checkers_copy_says_nobody_checked_it_in_time(company, manager, worker):
    rule(company, OnFinish.ASK, hours=4)
    late = waiting(manager, worker, hours_ago=5)
    services.accept_overdue_reviews()
    late.refresh_from_db()

    with translation.override("en"):
        text, _ = bot_messages.copy_of(late, manager, "review", timezone.now())

    assert text.startswith("<b>Accepted automatically</b> · nobody checked it in time")


def test_work_waiting_for_a_check_has_no_accepted_note(company, manager, worker):
    rule(company, OnFinish.ASK)
    task = services.complete_task(give(manager, worker), by=worker)

    assert bot_messages.accepted_note(task) is None


# The API ----------------------------------------------------------------------------------


def test_anyone_in_the_dashboard_reads_the_rule(company, manager, owner_api):
    response = owner_api(manager).get(SETTINGS.format(company.pk))

    assert response.status_code == 200
    assert response.json() == {"on_finish": "auto", "auto_accept_after_hours": None}


def test_only_company_settings_changes_it(company, manager, owner_api):
    response = owner_api(manager).patch(
        SETTINGS.format(company.pk), {"on_finish": "ask"}, format="json"
    )

    assert response.status_code == 403
    assert conf.get_settings(company).on_finish == OnFinish.AUTO


def test_the_owner_changes_the_rule_and_it_is_audited(company, owner, owner_api):
    response = owner_api(owner).patch(
        SETTINGS.format(company.pk),
        {"on_finish": "proof", "auto_accept_after_hours": 24},
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == {"on_finish": "proof", "auto_accept_after_hours": 24}
    row = AuditLog.objects.get(action=TasksAction.SETTINGS_CHANGED)
    assert row.details["changes"]["on_finish"] == ["auto", "proof"]

    off = owner_api(owner).patch(
        SETTINGS.format(company.pk), {"auto_accept_after_hours": None}, format="json"
    )
    assert off.json()["auto_accept_after_hours"] is None


@pytest.mark.parametrize("hours", [3, 73, 0])
def test_the_wait_is_between_4_and_72_hours(company, owner, owner_api, hours):
    response = owner_api(owner).patch(
        SETTINGS.format(company.pk), {"auto_accept_after_hours": hours}, format="json"
    )

    assert response.status_code == 400


def test_the_dashboards_new_task_follows_the_rule_unless_told(company, manager, worker, owner_api):
    rule(company, OnFinish.ASK)
    client = owner_api(manager)
    url = f"/api/v1/owner/companies/{company.pk}/tasks/"

    default = client.post(url, {"title": "A", "assignee_ids": [worker.pk]}, format="json")
    explicit = client.post(
        url,
        {"title": "B", "assignee_ids": [worker.pk], "needs_confirmation": False},
        format="json",
    )
    null = client.post(
        url,
        {"title": "C", "assignee_ids": [worker.pk], "needs_confirmation": None},
        format="json",
    )

    assert {default.status_code, explicit.status_code, null.status_code} == {201}
    flags = dict(Task.objects.filter(assignee=worker).values_list("title", "needs_confirmation"))
    assert flags == {"A": True, "B": False, "C": True}


def test_the_mini_apps_give_a_task_follows_the_rule(company, manager, worker, api_as):
    rule(company, OnFinish.PROOF)

    response = api_as(manager).post(
        f"/api/v1/companies/{company.pk}/tasks/",
        {"title": "Check the expiry dates", "assignee_id": worker.pk},
        format="json",
    )

    assert response.status_code == 201
    data = response.json()
    assert (data["needs_confirmation"], data["accept_with_proof"]) == (True, True)
    assert data["accepted_automatically"] is False


def test_the_assignee_reads_accepted_in_the_app_and_the_dashboard(
    company, manager, worker, api_as, owner_api
):
    task = give(manager, worker)

    done = api_as(worker).post(f"/api/v1/companies/{company.pk}/tasks/{task.pk}/complete/", {})
    row = owner_api(manager).get(f"/api/v1/owner/companies/{company.pk}/tasks/{task.pk}/")

    assert done.status_code == 200
    assert (done.json()["status"], done.json()["accepted_automatically"]) == ("done", True)
    assert row.json()["accepted_automatically"] is True


def test_the_review_lists_never_show_work_accepted_automatically(
    company, manager, worker, owner_api
):
    services.complete_task(give(manager, worker), by=worker)

    reviews = owner_api(manager).get(f"/api/v1/owner/companies/{company.pk}/tasks/reviews/")

    assert reviews.status_code == 200
    assert reviews.json()["results"] == []


def test_the_routines_api_takes_null_for_the_rule(company, manager, worker, owner_api):
    rule(company, OnFinish.ASK)

    response = owner_api(manager).post(
        f"/api/v1/owner/companies/{company.pk}/routines/",
        {
            "title": "Open the shutters",
            "due_time": "08:00",
            "assignee_ids": [worker.pk],
            "needs_confirmation": None,
        },
        format="json",
    )

    assert response.status_code == 201, response.json()
    assert (response.json()["needs_confirmation"], response.json()["accept_with_proof"]) == (
        True,
        False,
    )


def test_the_mini_app_reads_the_rule_for_i_will_check_it(company, manager, api_as):
    rule(company, OnFinish.ASK)

    response = api_as(manager).get(f"/api/v1/companies/{company.pk}/tasks/finish-rule/")

    assert response.status_code == 200
    assert response.json() == {"on_finish": "ask"}


def test_a_template_made_by_hand_keeps_its_choice(company, manager, worker):
    template = TaskTemplateFactory(
        company=company, needs_confirmation=True, assignees=[worker], weekdays=list(range(7))
    )

    assert (template.needs_confirmation, template.accept_with_proof) == (True, False)


def test_the_mini_apps_routine_api_follows_the_rule_too(company, manager, worker, api_as):
    rule(company, OnFinish.PROOF)
    url = f"/api/v1/companies/{company.pk}/task-templates/"
    client = api_as(manager)

    default = client.post(url, {"title": "Shelves", "due_time": "09:00"}, format="json")
    null = client.post(
        url, {"title": "Till", "due_time": "10:00", "needs_confirmation": None}, format="json"
    )
    own = client.post(
        url, {"title": "Fridge", "due_time": "11:00", "needs_confirmation": False}, format="json"
    )

    assert {default.status_code, null.status_code, own.status_code} == {201}
    rules_of = {
        t.title: (t.needs_confirmation, t.accept_with_proof)
        for t in TaskTemplate.objects.filter(company=company)
    }
    assert rules_of == {"Shelves": (True, True), "Till": (True, True), "Fridge": (False, False)}
    edited = client.patch(f"{url}{default.json()['id']}/", {"title": "Shelves, all"}, format="json")
    assert edited.status_code == 200
    assert TaskTemplate.objects.get(title="Shelves, all").accept_with_proof is True
