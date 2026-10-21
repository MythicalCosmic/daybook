"""Projects services: creating and running a board (docs/PLAN-OWNER.md §13.3)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.projects import queries, services
from apps.projects.models import (
    Card,
    Health,
    Milestone,
    Project,
    ProjectMember,
    ProjectUpdate,
    TaskLabel,
)
from apps.projects.services import ProjectError
from apps.projects.tests.factories import card, lists, project, team
from apps.tasks import services as task_services
from apps.tasks.models import Proof, Task
from apps.tasks.tests.factories import jpeg

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(company, member):
    return team(company, member)


# Projects -------------------------------------------------------------------------------


def test_a_new_project_gets_the_default_lists_and_its_lead_as_member(company, people):
    reno = project(company, people["owner"], lead=people["manager"])

    assert [row.name for row in reno.lists.all()] == [
        "Backlog",
        "To do",
        "In progress",
        "Review",
        "Done",
    ]
    assert [row.is_done for row in reno.lists.all()] == [False, False, False, False, True]
    assert reno.key == "CBO"  # the initials of "Chilonzor branch opening"
    assert reno.color == "chart-1"
    lead = ProjectMember.objects.get(project=reno)
    assert (lead.membership, lead.role) == (people["manager"], ProjectMember.Role.LEAD)
    assert AuditLog.objects.filter(action="projects.project_created", target_id=reno.pk).exists()
    # The lead hears about it (the creator saw it themselves).
    assert Notification.objects.filter(recipient=people["manager"], kind="projects.added").exists()


def test_keys_are_suggested_free_and_checked(company, people):
    first = project(company, people["owner"], name="Website")
    second = project(company, people["owner"], name="Website")
    assert (first.key, second.key) == ("WEBS", "WEB")

    with pytest.raises(ProjectError) as error:
        project(company, people["owner"], name="Other", key="WEBS")
    assert error.value.code == "key"
    with pytest.raises(ProjectError):
        project(company, people["owner"], name="Other", key="w1")


def test_cyrillic_names_make_latin_keys(company, people):
    assert project(company, people["owner"], name="Склад инвентаризация").key == "SI"


def test_only_project_managers_create_projects(company, people):
    with pytest.raises(PermissionDenied):
        project(company, people["aziz"])


def test_company_settings_change_the_starting_lists(company, people):
    services.update_settings(
        company, by=people["owner"], default_lists=["Ideas", "Doing", "Shipped"]
    )

    reno = project(company, people["owner"])

    assert [(row.name, row.is_done) for row in reno.lists.all()] == [
        ("Ideas", False),
        ("Doing", False),
        ("Shipped", True),
    ]


def test_a_lead_manages_their_project_without_projects_manage(company, people):
    reno = project(company, people["owner"], lead=people["aziz"])

    services.update_project(reno, by=people["aziz"], name="Branch opening", status="active")

    reno.refresh_from_db()
    assert (reno.name, reno.status) == ("Branch opening", "active")
    with pytest.raises(PermissionDenied):
        services.update_project(reno, by=people["madina"], name="Mine")


def test_changing_the_lead_moves_the_role(company, people):
    reno = project(company, people["owner"], lead=people["manager"])

    services.update_project(reno, by=people["owner"], lead=people["aziz"])

    roles = dict(ProjectMember.objects.filter(project=reno).values_list("membership_id", "role"))
    assert roles == {people["manager"].pk: "member", people["aziz"].pk: "lead"}
    reno.refresh_from_db()
    assert reno.lead == people["aziz"]


def test_completing_stamps_the_time_and_reopening_clears_it(company, people):
    reno = project(company, people["owner"])

    services.update_project(reno, by=people["owner"], status=Project.Status.COMPLETED)
    reno.refresh_from_db()
    assert reno.completed_at is not None

    services.update_project(reno, by=people["owner"], status=Project.Status.ACTIVE)
    reno.refresh_from_db()
    assert reno.completed_at is None


def test_dates_and_budget_are_checked(company, people):
    today = timezone.localdate()
    with pytest.raises(ProjectError):
        project(company, people["owner"], start_on=today, due_on=today - timedelta(days=1))
    with pytest.raises(ProjectError):
        project(company, people["owner"], budget="-5")


def test_archive_and_restore(company, people):
    reno = project(company, people["owner"])

    services.archive_project(reno, by=people["owner"])
    assert not queries.visible_projects(people["owner"]).filter(pk=reno.pk).exists()
    assert queries.visible_projects(people["owner"], archived=True).filter(pk=reno.pk).exists()
    with pytest.raises(ProjectError):
        card(reno, people["owner"])

    services.restore_project(reno, by=people["owner"])
    assert queries.visible_projects(people["owner"]).filter(pk=reno.pk).exists()


# Members --------------------------------------------------------------------------------


def test_adding_a_member_tells_them_once(company, people):
    reno = project(company, people["owner"])

    services.add_member(reno, people["aziz"], by=people["owner"])
    services.add_member(reno, people["aziz"], by=people["owner"])

    note = Notification.objects.get(recipient=people["aziz"], kind="projects.added")
    assert reno.key in note.title
    assert note.app_screen == f"projects.board:{reno.pk}"


def test_the_lead_cant_be_removed_and_roles_change(company, people):
    reno = project(company, people["owner"], lead=people["manager"])
    row = services.add_member(reno, people["aziz"], by=people["owner"])

    services.set_member_role(row, by=people["owner"], role="viewer")
    row.refresh_from_db()
    assert row.role == "viewer"
    with pytest.raises(ProjectError):
        services.remove_member(reno, people["manager"], by=people["owner"])

    services.remove_member(reno, people["aziz"], by=people["owner"])
    assert not ProjectMember.objects.filter(project=reno, membership=people["aziz"]).exists()


def test_people_from_another_company_cant_join(company, other_company, people, member):
    stranger = member.registered(other_company)
    reno = project(company, people["owner"])

    with pytest.raises(ProjectError):
        services.add_member(reno, stranger, by=people["owner"])


# Lists ----------------------------------------------------------------------------------


def test_new_lists_go_before_done_and_deleting_moves_the_cards(company, people):
    reno = project(company, people["owner"])
    qa = services.create_list(reno, by=people["owner"], name="QA", wip_limit=3)
    names = [row.name for row in reno.lists.all()]
    assert names[-2:] == ["QA", "Done"]
    assert qa.wip_limit == 3

    work = card(reno, people["owner"], project_list=qa)
    services.delete_list(qa, by=people["owner"])

    work.refresh_from_db()
    assert work.project_list == lists(reno)["Backlog"]


def test_the_done_list_stays_and_a_board_keeps_one_other_list(company, people):
    reno = project(company, people["owner"])
    by_name = lists(reno)

    with pytest.raises(ProjectError):
        services.delete_list(by_name["Done"], by=people["owner"])
    with pytest.raises(ProjectError):
        services.create_list(reno, by=people["owner"], name="Shipped", is_done=True)
    for name in ("Backlog", "To do", "In progress"):
        services.delete_list(by_name[name], by=people["owner"])
    with pytest.raises(ProjectError):
        services.delete_list(by_name["Review"], by=people["owner"])


def test_reordering_needs_every_list_once(company, people):
    reno = project(company, people["owner"])
    ids = [row.pk for row in reno.lists.all()]

    services.reorder_lists(reno, list(reversed(ids)), by=people["owner"])
    assert [row.pk for row in reno.lists.all()] == list(reversed(ids))
    with pytest.raises(ProjectError):
        services.reorder_lists(reno, ids[:2], by=people["owner"])


def test_wip_limits_are_whole_numbers(company, people):
    reno = project(company, people["owner"])
    with pytest.raises(ProjectError):
        services.update_list(lists(reno)["To do"], by=people["owner"], wip_limit=1000)


# Cards ----------------------------------------------------------------------------------


def test_a_card_is_a_numbered_task_on_the_board(company, people):
    reno = project(company, people["owner"], key="RENO")
    label = services.create_label(reno, by=people["owner"], name="Electrics")
    launch = services.create_milestone(reno, by=people["owner"], name="Launch")

    first = card(
        reno, people["owner"], assignee=people["aziz"], label_ids=[label.pk], milestone=launch
    )
    second = card(reno, people["owner"], title="Order paint")

    assert first.card.number == 1 and second.card.number == 2
    assert queries.card_key(reno, first) == "RENO-1"
    assert first.project_list == lists(reno)["Backlog"]
    assert first.milestone == launch
    assert first.kind == Task.Kind.ASSIGNED
    assert first.branch == people["aziz"].home_branch
    assert list(TaskLabel.objects.filter(task=first).values_list("label_id", flat=True)) == [
        label.pk
    ]
    # Someone given a card joins the project.
    assert ProjectMember.objects.filter(project=reno, membership=people["aziz"]).exists()


def test_a_card_for_yourself_is_shared_work_not_a_private_task(company, people):
    reno = project(company, people["owner"])

    own = card(reno, people["owner"])

    assert own.kind == Task.Kind.ASSIGNED
    assert own.assignee == people["owner"]


def test_a_member_without_tasks_assign_adds_cards_only_for_themselves(company, people):
    reno = project(company, people["owner"])
    services.add_member(reno, people["aziz"], by=people["owner"])

    mine = card(reno, people["aziz"])
    assert mine.assignee == people["aziz"]
    with pytest.raises(PermissionDenied):
        card(reno, people["aziz"], assignee=people["madina"])
    with pytest.raises(PermissionDenied):
        card(reno, people["madina"])  # not on the project


def test_a_lead_without_tasks_assign_gives_cards_to_their_projects_people(company, people):
    lead = people["aziz"]  # an employee: no tasks.assign, no projects.manage
    reno = project(company, people["owner"], lead=lead)
    services.add_member(reno, people["madina"], by=lead)
    launch = services.create_milestone(reno, by=lead, name="Launch")

    given = card(reno, lead, assignee=people["madina"], milestone=launch)

    assert given.assignee == people["madina"] and given.created_by == lead
    assert given.kind == Task.Kind.ASSIGNED
    assert given.milestone == launch and given.card.number == 1
    assert queries.capabilities(reno, lead)["assign_others"] is True
    # Only the people on the project: someone else has to be added first.
    outsider = people["manager"]
    with pytest.raises(PermissionDenied):
        card(reno, lead, assignee=outsider)
    assert not ProjectMember.objects.filter(project=reno, membership=outsider).exists()


def test_who_may_give_cards_to_others_is_on_the_board_capabilities(company, people):
    reno = project(company, people["owner"])
    services.add_member(reno, people["aziz"], by=people["owner"])

    assert queries.capabilities(reno, people["owner"])["assign_others"] is True
    assert queries.capabilities(reno, people["aziz"])["assign_others"] is False
    # Seeing the board isn't editing it.
    services.add_member(reno, people["madina"], by=people["owner"], role="viewer")
    assert queries.capabilities(reno, people["madina"])["assign_others"] is False


def test_a_card_given_to_someone_new_tells_them_they_joined_but_not_its_maker(company, people):
    reno = project(company, people["owner"])
    manager = people["manager"]  # projects.manage, not on the project

    card(reno, manager, title="Mine")
    card(reno, manager, title="Theirs", assignee=people["madina"])

    assert ProjectMember.objects.filter(project=reno, membership=manager).exists()
    assert not Notification.objects.filter(recipient=manager, kind="projects.added").exists()
    joined = Notification.objects.filter(recipient=people["madina"], kind="projects.added")
    assert joined.count() == 1


def test_a_card_in_a_list_or_with_a_milestone_of_another_board_is_refused(company, people):
    reno = project(company, people["owner"])
    other = project(company, people["owner"], name="Other")
    elsewhere = services.create_milestone(other, by=people["owner"], name="Elsewhere")

    with pytest.raises(DomainError):
        card(reno, people["owner"], project_list=lists(other)["Backlog"])
    with pytest.raises(DomainError):
        card(reno, people["owner"], milestone=elsewhere)
    assert not Task.objects.filter(project=reno).exists()


def test_labels_from_another_board_are_refused(company, people):
    reno = project(company, people["owner"])
    other = project(company, people["owner"], name="Other")
    label = services.create_label(other, by=people["owner"], name="Elsewhere")

    with pytest.raises(ProjectError):
        card(reno, people["owner"], label_ids=[label.pk])


def test_moving_a_card_between_and_within_lists(company, people):
    reno = project(company, people["owner"])
    by_name = lists(reno)
    work = card(reno, people["owner"], assignee=people["aziz"])

    moved = services.move_card(work, by_name["In progress"], 1500.0, by=people["aziz"])

    assert (moved.project_list, moved.list_position) == (by_name["In progress"], 1500.0)
    assert AuditLog.objects.filter(action="projects.card_moved", target_id=work.pk).exists()


def test_only_the_assignee_or_board_editors_move_a_card(company, people):
    reno = project(company, people["owner"])
    services.add_member(reno, people["madina"], by=people["owner"], role="viewer")
    work = card(reno, people["owner"], assignee=people["aziz"])

    with pytest.raises(PermissionDenied):
        services.move_card(work, lists(reno)["To do"], 10, by=people["madina"])


def test_moving_into_done_completes_the_task(company, people):
    reno = project(company, people["owner"])
    work = card(reno, people["owner"], assignee=people["aziz"])

    moved = services.move_card(work, lists(reno)["Done"], 1.0, by=people["aziz"])

    assert moved.status == Task.Status.DONE
    assert moved.project_list == lists(reno)["Done"]
    assert moved.completed_at is not None


def test_a_card_needing_a_check_goes_to_review_and_the_checker_finishes_it(company, people):
    reno = project(company, people["owner"])
    work = card(reno, people["owner"], assignee=people["aziz"], needs_confirmation=True)

    moved = services.move_card(work, lists(reno)["Done"], 1.0, by=people["aziz"])
    assert moved.status == Task.Status.REVIEW
    assert moved.project_list == lists(reno)["Review"]

    confirmed = services.move_card(moved, lists(reno)["Done"], 1.0, by=people["owner"])
    assert confirmed.status == Task.Status.DONE
    assert confirmed.project_list == lists(reno)["Done"]


def test_a_card_needing_proof_or_someone_elses_opens_instead(company, people):
    reno = project(company, people["owner"])
    photo = card(reno, people["owner"], assignee=people["aziz"], proof=Proof.PHOTO)
    theirs = card(reno, people["owner"], assignee=people["aziz"], title="Mop the floor")

    for task, mover in ((photo, people["aziz"]), (theirs, people["owner"])):
        with pytest.raises(ProjectError) as error:
            services.move_card(task, lists(reno)["Done"], 1.0, by=mover)
        assert error.value.code == "needs_proof"
        task.refresh_from_db()
        assert task.status == Task.Status.TODO


def test_a_done_card_stays_in_done(company, people):
    reno = project(company, people["owner"])
    work = card(reno, people["owner"], assignee=people["aziz"])
    services.move_card(work, lists(reno)["Done"], 1.0, by=people["aziz"])

    with pytest.raises(ProjectError) as error:
        services.move_card(work, lists(reno)["To do"], 1.0, by=people["owner"])
    assert error.value.code == "done"


def test_a_task_finished_anywhere_moves_to_done(company, people):
    """The receiver: completion from the bot or the mini app moves the card too."""
    reno = project(company, people["owner"])
    work = card(reno, people["owner"], assignee=people["aziz"])

    task_services.complete_task(work, by=people["aziz"])

    work.refresh_from_db()
    assert work.project_list == lists(reno)["Done"]


def test_a_task_put_on_a_project_elsewhere_gets_a_card(company, people):
    reno = project(company, people["owner"])
    task = task_services.create_task(
        by=people["owner"], title="Count the till", assignee=people["madina"]
    )

    task.project = reno
    task.save()

    task.refresh_from_db()
    assert Card.objects.get(task=task).number == 1
    assert task.project_list == lists(reno)["Backlog"]
    assert ProjectMember.objects.filter(project=reno, membership=people["madina"]).exists()


def test_card_changes_go_through_the_task_app(company, people):
    reno = project(company, people["owner"])
    work = card(reno, people["owner"], assignee=people["aziz"])
    later = timezone.now() + timedelta(days=9)

    changed = services.update_card(work, by=people["owner"], title="Paint the hall", due_at=later)

    assert changed.title == "Paint the hall"
    assert abs((changed.due_at - later).total_seconds()) < 1
    # The assignee may plan their own card but not rename what they were given.
    with pytest.raises(PermissionDenied):
        services.update_card(work, by=people["aziz"], title="Mine now")
    services.update_card(work, by=people["aziz"], start_on=timezone.localdate())


def test_rescheduling_keeps_the_time_of_day(company, people):
    reno = project(company, people["owner"])
    work = card(reno, people["owner"], assignee=people["aziz"])
    day = timezone.localdate() + timedelta(days=12)

    moved = services.reschedule_card(
        work, by=people["owner"], start_on=day - timedelta(days=3), end_on=day
    )

    assert moved.card.start_on == day - timedelta(days=3)
    assert timezone.localtime(moved.due_at, company_tz(company)).date() == day


def company_tz(company):
    from zoneinfo import ZoneInfo

    return ZoneInfo(company.timezone)


# Milestones, labels ---------------------------------------------------------------------


def test_milestones_complete_and_reopen(company, people):
    reno = project(company, people["owner"])
    launch = services.create_milestone(reno, by=people["owner"], name="Launch")

    services.update_milestone(launch, by=people["owner"], status="done")
    launch.refresh_from_db()
    assert launch.completed_at is not None
    services.update_milestone(launch, by=people["owner"], status="open")
    launch.refresh_from_db()
    assert launch.completed_at is None

    work = card(reno, people["owner"], milestone=launch)
    services.delete_milestone(launch, by=people["owner"])
    work.refresh_from_db()
    assert work.milestone is None


def test_labels_are_unique_per_board(company, people):
    reno = project(company, people["owner"])
    services.create_label(reno, by=people["owner"], name="Urgent", color="chart-1")

    with pytest.raises(ProjectError):
        services.create_label(reno, by=people["owner"], name="urgent")
    with pytest.raises(ProjectError):
        services.create_label(reno, by=people["owner"], name="Blue", color="#0000ff")


# Time -----------------------------------------------------------------------------------


def test_logging_time_on_a_project(company, people):
    reno = project(company, people["owner"])
    services.add_member(reno, people["aziz"], by=people["owner"])
    today = timezone.localdate()

    entry = services.log_time(people["aziz"], day=today, minutes=90, project=reno, note="On site")

    assert (entry.minutes, entry.project, entry.source) == (90, reno, "manual")
    with pytest.raises(ProjectError):
        services.log_time(people["aziz"], day=today, minutes=1400, project=reno)  # > 24 h
    with pytest.raises(ProjectError):
        services.log_time(people["aziz"], day=today + timedelta(days=1), minutes=10, project=reno)
    with pytest.raises(PermissionDenied):
        services.log_time(people["madina"], day=today, minutes=10, project=reno)


def test_a_manager_logs_time_for_a_member(company, people):
    reno = project(company, people["owner"], lead=people["manager"])
    services.add_member(reno, people["aziz"], by=people["owner"])

    entry = services.log_time(
        people["manager"],
        day=timezone.localdate(),
        minutes=30,
        project=reno,
        membership=people["aziz"],
    )

    assert entry.membership == people["aziz"] and entry.created_by == people["manager"]
    with pytest.raises(PermissionDenied):
        services.log_time(
            people["aziz"],
            day=timezone.localdate(),
            minutes=5,
            project=reno,
            membership=people["madina"],
        )


def test_a_timer_logs_what_it_measured_and_switching_stops_the_old_one(company, people):
    reno = project(company, people["owner"])
    work = card(reno, people["owner"], assignee=people["aziz"])
    timer = services.start_timer(people["aziz"], task=work)
    timer.started_at = timezone.now() - timedelta(minutes=50)
    timer.save()

    services.start_timer(people["aziz"], project=reno)  # switches

    first = people["aziz"].time_entries.get()
    assert (first.minutes, first.task, first.project, first.source) == (50, work, reno, "timer")
    entry = services.stop_timer(people["aziz"])
    assert entry.minutes == 1  # at least a minute
    assert services.stop_timer(people["aziz"]) is None


def test_only_your_own_time_changes(company, people):
    reno = project(company, people["owner"])
    services.add_member(reno, people["aziz"], by=people["owner"])
    entry = services.log_time(people["aziz"], day=timezone.localdate(), minutes=30, project=reno)

    with pytest.raises(PermissionDenied):
        services.update_time_entry(entry, by=people["madina"], minutes=10)
    services.update_time_entry(entry, by=people["owner"], minutes=45)  # manages the project
    entry.refresh_from_db()
    assert entry.minutes == 45
    services.delete_time_entry(entry, by=people["aziz"])


# Updates, files, links ------------------------------------------------------------------


def test_posting_an_update(company, people):
    reno = project(company, people["owner"], lead=people["manager"])

    update = services.post_update(
        reno, by=people["manager"], health="at_risk", text="Tiles are late."
    )

    assert update.health == Health.AT_RISK
    with pytest.raises(PermissionDenied):
        services.post_update(reno, by=people["aziz"], health="on_track")
    with pytest.raises(ProjectError):
        services.post_update(reno, by=people["manager"], health="great")


def test_files_are_checked_and_private(company, people):
    from django.core.files.base import ContentFile

    from apps.core.uploads import InvalidUpload

    reno = project(company, people["owner"])
    row = services.add_file(reno, by=people["owner"], upload=jpeg("plan.jpg"))

    assert row.kind == "image" and row.name == "plan.jpg"
    assert row.file.name.startswith(f"projects/{company.pk}/") and row.file.name.endswith(".jpg")
    with pytest.raises(InvalidUpload):
        services.add_file(
            reno, by=people["owner"], upload=ContentFile(b"<svg onload=alert(1)>", name="x.svg")
        )


def test_links_must_be_web_addresses(company, people):
    reno = project(company, people["owner"])
    link = services.add_link(reno, by=people["owner"], title="", url="https://figma.com/file/x")
    assert link.title == "https://figma.com/file/x"
    with pytest.raises(ProjectError):
        services.add_link(reno, by=people["owner"], title="x", url="javascript:alert(1)")


# Money and health -----------------------------------------------------------------------


def fund(company, owner, amount="200000000"):
    from apps.finance import defaults as finance_defaults
    from apps.finance import services as finance

    finance_defaults.ensure(company)
    account = finance.create_account(company, by=owner, kind="bank", name="Bank")
    finance.record_transaction(
        company,
        by=owner,
        kind="owner",
        amount=Decimal(amount),
        account=account,
        occurred_on=timezone.localdate() - timedelta(days=5),
    )
    return account


def test_expenses_on_a_project_count_as_spent(company, people):
    from apps.finance.models import Category

    reno = project(company, people["owner"], budget="1000000")
    account = fund(company, people["owner"])
    repairs = Category.objects.get(company=company, system_code="repairs")

    txn = services.add_expense(
        reno,
        by=people["owner"],
        amount=Decimal("250000"),
        account=account,
        category=repairs,
        occurred_on=timezone.localdate(),
    )

    assert txn.project == reno and txn.base_amount == Decimal("-250000.00")
    money = queries.financials(reno, viewer=people["owner"])
    assert money["spent"] == Decimal("250000.00")
    assert money["burn"] == 25
    assert money["remaining"] == Decimal("750000.00")
    assert money["by_category"][0]["amount"] == Decimal("250000.00")
    with pytest.raises(PermissionDenied):
        services.add_expense(
            reno,
            by=people["manager"],
            amount=Decimal("1"),
            account=account,
            category=repairs,
            occurred_on=timezone.localdate(),
        )


def test_health(company, people):
    from apps.finance.models import Category

    today = timezone.localdate()
    reno = project(
        company,
        people["owner"],
        status="active",
        due_on=today + timedelta(days=30),
        budget="100000",
    )
    assert queries.health_of(reno) == Health.ON_TRACK

    reno.due_on = today + timedelta(days=5)  # close, nothing done
    reno.save()
    assert queries.health_of(reno) == Health.AT_RISK

    launch = services.create_milestone(
        reno, by=people["owner"], name="Launch", due_on=today - timedelta(days=1)
    )
    assert queries.health_of(reno) == Health.OFF_TRACK
    services.update_milestone(launch, by=people["owner"], status=Milestone.Status.DONE)

    reno.due_on = today + timedelta(days=30)
    reno.save()
    account = fund(company, people["owner"])
    services.add_expense(
        reno,
        by=people["owner"],
        amount=Decimal("150000"),
        account=account,
        category=Category.objects.get(company=company, system_code="repairs"),
        occurred_on=today,
    )
    assert queries.health_of(reno) == Health.OFF_TRACK  # over budget

    reno.status = Project.Status.COMPLETED
    reno.save()
    assert queries.health_of(reno) is None


def test_progress_overall_and_per_milestone(company, people):
    reno = project(company, people["owner"])
    launch = services.create_milestone(reno, by=people["owner"], name="Launch")
    done = card(reno, people["owner"], milestone=launch)
    card(reno, people["owner"], milestone=launch, title="Two")
    card(reno, people["owner"], title="Three")
    services.move_card(done, lists(reno)["Done"], 1, by=people["owner"])

    progress = queries.progress(reno)

    assert (progress["done"], progress["total"], progress["percent"]) == (1, 3, 33)
    assert progress["milestones"] == [{"id": launch.pk, "done": 1, "total": 2, "percent": 50}]


def test_labour_cost_uses_payroll_rates_and_skips_unknown(company, people, monkeypatch):
    reno = project(company, people["owner"])
    services.add_member(reno, people["aziz"], by=people["owner"])
    services.log_time(people["aziz"], day=timezone.localdate(), minutes=90, project=reno)
    services.log_time(people["owner"], day=timezone.localdate(), minutes=60, project=reno)
    assert queries.labour_cost(reno) is None  # payroll not set up

    rates = {people["aziz"].pk: Decimal("40000")}
    monkeypatch.setattr(
        "apps.payroll.contracts.cost_rate", lambda membership, day: rates.get(membership.pk)
    )
    assert queries.labour_cost(reno) == Decimal("60000.00")


# Visibility -----------------------------------------------------------------------------


def test_members_only_projects_and_their_tasks_are_hidden_from_others(company, people):
    from apps.tasks.queries import visible_tasks

    reno = project(company, people["owner"])
    work = card(reno, people["owner"], assignee=people["owner"])
    outsider = people["madina"]

    assert not queries.visible_projects(outsider).filter(pk=reno.pk).exists()
    assert queries.visible_projects(people["manager"]).filter(pk=reno.pk).exists()  # view_all
    assert not visible_tasks(outsider).filter(pk=work.pk).exists()

    services.update_project(reno, by=people["owner"], visibility="company")
    assert queries.visible_projects(outsider).filter(pk=reno.pk).exists()


def test_branch_scope_limits_view_all(company, people, member):
    from apps.companies.models import Branch

    other_branch = Branch.objects.create(company=company, name="Yunusobod")
    scoped = member.registered(company, "Employee", first_name="Scoped")
    scoped.role.permissions = [*scoped.role.permissions, "projects.view_all", "dashboard.access"]
    scoped.role.save()
    first_branch = company.branches.order_by("order", "pk").first()
    scoped.branches.set([first_branch])
    here = project(company, people["owner"], name="Here", branch=first_branch)
    there = project(company, people["owner"], name="There", branch=other_branch)
    nowhere = project(company, people["owner"], name="Nowhere")

    seen = set(queries.visible_projects(scoped).values_list("pk", flat=True))

    assert here.pk in seen and there.pk not in seen and nowhere.pk not in seen


def test_project_rows_are_audited_with_the_actor(company, people):
    reno = project(company, people["owner"])
    services.post_update(reno, by=people["owner"], health="on_track")
    row = AuditLog.objects.filter(action="projects.update_posted").get()
    assert row.actor == people["owner"].user
    assert ProjectUpdate.objects.filter(project=reno).count() == 1
