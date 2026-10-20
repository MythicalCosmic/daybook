"""The roster by hand: drafts, moves, removals, bulk actions, publishing, and the receivers that
keep shifts in step with time off and people leaving."""

from datetime import time, timedelta

import pytest

from apps.attendance import queries, services
from apps.attendance.models import AttendanceRecord, MemberSchedule, ShiftSwap, WorkShift
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import assign, shift_at, weekly_schedule
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.members import services as member_services
from apps.timeoff import services as timeoff_services
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

MONDAY = DAY + timedelta(days=5)  # next week's Monday (26 October)


@pytest.fixture(autouse=True)
def morning(freeze):
    return freeze(local(DAY, 10, 0))


def test_a_new_shift_is_a_draft_until_published(staff, django_capture_on_commit_callbacks):
    company = staff.ali.company
    shift = services.create_shift(
        company,
        by=staff.manager,
        membership=staff.ali,
        date=MONDAY,
        starts_at=time(9),
        ends_at=time(18),
    )
    assert shift.published_at is None and shift.status == WorkShift.Status.PLANNED
    assert not queries.shifts_between(
        company, MONDAY, MONDAY, branch_ids=None, drafts=False
    ).exists()
    with django_capture_on_commit_callbacks(execute=True):
        assert (
            services.publish_roster(
                company, by=staff.manager, start=MONDAY, end=MONDAY + timedelta(days=6)
            )
            == 1
        )
    shift.refresh_from_db()
    assert shift.published_at is not None
    told = Notification.objects.get(kind="attendance.roster", recipient=staff.ali)
    assert "New shifts" in told.title and "09:00–18:00" in told.body
    assert AuditLog.objects.filter(action="attendance.roster_published").exists()


def test_open_shifts_are_offered_on_publish(staff, chilonzor, django_capture_on_commit_callbacks):
    company = staff.ali.company
    services.create_shift(
        company,
        by=staff.manager,
        date=MONDAY,
        starts_at=time(12),
        ends_at=time(21),
        branch=chilonzor,
        position=staff.cashier,
    )
    with django_capture_on_commit_callbacks(execute=True):
        services.publish_roster(company, by=staff.manager, start=MONDAY, end=MONDAY)
    offered = set(
        Notification.objects.filter(kind="attendance.open_shift").values_list(
            "recipient_id", flat=True
        )
    )
    assert offered == {staff.ali.pk, staff.vali.pk}


def test_overlaps_and_leave_are_refused(staff):
    company = staff.ali.company
    shift_at(staff.ali, MONDAY)
    with pytest.raises(DomainError, match="already has a shift"):
        services.create_shift(
            company,
            by=staff.manager,
            membership=staff.ali,
            date=MONDAY,
            starts_at=time(17),
            ends_at=time(23),
        )
    TimeOff.objects.create(
        company=company,
        membership=staff.vali,
        first_day=MONDAY,
        last_day=MONDAY,
        status=TimeOff.Status.APPROVED,
    )
    with pytest.raises(DomainError, match="on leave"):
        services.create_shift(
            company,
            by=staff.manager,
            membership=staff.vali,
            date=MONDAY,
            starts_at=time(9),
            ends_at=time(18),
        )


def test_moving_a_published_shift_tells_both_people(staff, django_capture_on_commit_callbacks):
    shift = shift_at(staff.ali, MONDAY)
    with django_capture_on_commit_callbacks(execute=True):
        services.update_shift(
            shift,
            by=staff.manager,
            membership=staff.vali,
            starts_at=time(10, 0),
            ends_at=time(19, 0),
        )
    shift.refresh_from_db()
    assert shift.membership == staff.vali and shift.starts_at == local(MONDAY, 10)
    titles = dict(
        Notification.objects.filter(kind="attendance.roster").values_list("recipient_id", "title")
    )
    assert "no longer work" in titles[staff.ali.pk]
    assert "changed" in titles[staff.vali.pk]
    assert AuditLog.objects.filter(action="attendance.shift_changed").exists()


def test_a_shift_with_a_check_in_stays_put(staff):
    shift = shift_at(staff.ali, DAY)
    services.update_settings(staff.ali.company, by=staff.manager, require_location=False)
    services.check_in(staff.ali, now=local(DAY, 8, 58))
    with pytest.raises(DomainError, match="checked in"):
        services.update_shift(shift, by=staff.manager, starts_at=time(11))
    with pytest.raises(DomainError, match="checked in"):
        services.delete_shift(shift, by=staff.manager)


def test_deleting_a_draft_removes_it_and_a_published_one_is_cancelled(
    staff, django_capture_on_commit_callbacks
):
    draft = shift_at(staff.ali, MONDAY, published=False)
    published = shift_at(staff.ali, MONDAY + timedelta(days=1))
    services.delete_shift(draft, by=staff.manager)
    assert not WorkShift.objects.filter(pk=draft.pk).exists()
    with django_capture_on_commit_callbacks(execute=True):
        services.delete_shift(published, by=staff.manager)
    published.refresh_from_db()
    assert published.status == WorkShift.Status.CANCELLED
    assert Notification.objects.filter(
        kind="attendance.roster", recipient=staff.ali, title__contains="removed"
    ).exists()


def test_bulk_copy_week_apply_schedule_and_clear(staff):
    company = staff.ali.company
    last_monday = MONDAY - timedelta(days=7)
    shift_at(staff.ali, last_monday + timedelta(days=2), time(14), time(22))  # Wed
    assert services.bulk_roster(company, by=staff.manager, action="copy_week", week=MONDAY) == 1
    copied = WorkShift.objects.get(membership=staff.ali, date=MONDAY + timedelta(days=2))
    assert copied.published_at is None and copied.starts_at == local(copied.date, 14)

    assign(staff.vali, weekly_schedule(company, days=[0, 1]), DAY)
    assert (
        services.bulk_roster(
            company,
            by=staff.manager,
            action="apply_schedule",
            week=MONDAY,
            member_ids=[staff.vali.pk],
        )
        == 2
    )

    published = shift_at(staff.bob, MONDAY + timedelta(days=4))
    count = services.bulk_roster(company, by=staff.manager, action="clear", week=MONDAY)
    assert count == 4
    published.refresh_from_db()
    assert published.status == WorkShift.Status.CANCELLED
    assert not WorkShift.objects.filter(date__gte=MONDAY, published_at__isnull=True).exists()


def test_a_branch_lead_sees_and_changes_only_their_branch(staff, yunusobod):
    company = staff.ali.company
    theirs = shift_at(staff.sara, MONDAY)
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services.update_shift(theirs, by=staff.lead, note="x")
    with pytest.raises(PermissionDenied):
        services.create_shift(
            company,
            by=staff.lead,
            membership=staff.sara,
            date=MONDAY + timedelta(days=1),
            starts_at=time(9),
            ends_at=time(18),
        )
    roster = queries.roster(company, MONDAY, branch_ids=[staff.ali.home_branch_id])
    assert {member["id"] for member in roster["members"]} >= {staff.ali.pk, staff.vali.pk}
    assert staff.sara.pk not in {member["id"] for member in roster["members"]}
    assert all(shift["member_id"] != staff.sara.pk for shift in roster["shifts"])


def test_time_off_turns_shifts_into_leave_and_back(staff, django_capture_on_commit_callbacks):
    """Through the real time-off services: their signals reach attendance on commit."""
    company = staff.ali.company
    shift = shift_at(staff.ali, MONDAY)
    time_off = TimeOff.objects.create(
        company=company,
        membership=staff.ali,
        first_day=MONDAY,
        last_day=MONDAY,
        status=TimeOff.Status.PENDING,
    )
    with django_capture_on_commit_callbacks(execute=True):
        timeoff_services.decide(time_off.pk, True, by=staff.manager.user)
    shift.refresh_from_db()
    assert (shift.status, shift.time_off) == (WorkShift.Status.LEAVE, time_off)
    time_off.refresh_from_db()
    with django_capture_on_commit_callbacks(execute=True):
        timeoff_services.cancel(time_off, by=staff.ali)
    shift.refresh_from_db()
    assert shift.status == WorkShift.Status.PLANNED and shift.time_off is None


def test_retroactive_time_off_excuses_absences(staff):
    past = DAY - timedelta(days=2)
    shift = shift_at(staff.ali, past)
    record = AttendanceRecord.objects.create(
        company=shift.company,
        membership=staff.ali,
        shift=shift,
        date=past,
        status=AttendanceRecord.Status.ABSENT,
    )
    time_off = TimeOff.objects.create(
        company=shift.company,
        membership=staff.ali,
        first_day=past,
        last_day=past,
        status=TimeOff.Status.APPROVED,
    )
    services.time_off_approved(time_off)
    record.refresh_from_db()
    assert record.status == AttendanceRecord.Status.EXCUSED


def test_leaving_closes_the_check_in_and_cancels_coming_shifts(
    staff, member, django_capture_on_commit_callbacks
):
    company = staff.ali.company
    owner = member.registered(company, "Owner")
    services.update_settings(company, by=staff.manager, require_location=False)
    today = shift_at(staff.ali, DAY)
    services.check_in(staff.ali, now=local(DAY, 8, 58))
    coming = shift_at(staff.ali, MONDAY)
    draft = shift_at(staff.ali, MONDAY + timedelta(days=1), published=False)
    other = shift_at(staff.vali, MONDAY + timedelta(days=2))
    swap = services.request_swap(staff.vali, shift=other, kind="cover", target=staff.ali)
    with django_capture_on_commit_callbacks(execute=True):
        member_services.offboard(staff.ali, by=owner.user)
    record = AttendanceRecord.objects.get(shift=today)
    coming.refresh_from_db()
    swap.refresh_from_db()
    assert record.status == AttendanceRecord.Status.CLOSED
    assert coming.status == WorkShift.Status.CANCELLED
    assert not WorkShift.objects.filter(pk=draft.pk).exists()
    assert swap.status == ShiftSwap.Status.CANCELLED


def test_schedule_archive_drops_untouched_future_shifts(staff):
    company = staff.ali.company
    schedule = weekly_schedule(company, days=range(7))
    assign(staff.ali, schedule, DAY)
    services.generate_shifts(company, days=3)
    services.archive_schedule(schedule, by=staff.manager)
    assert not WorkShift.objects.filter(membership=staff.ali, starts_at__gt=local(DAY, 10)).exists()
    assert MemberSchedule.objects.get(membership=staff.ali).schedule is None
