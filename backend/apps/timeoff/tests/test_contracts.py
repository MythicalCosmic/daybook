"""What other apps get from time off: its signals and the leave queries payroll reads."""

from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.timeoff import queries, services
from apps.timeoff.models import Holiday, TimeOff
from apps.timeoff.signals import time_off_approved, time_off_cancelled

pytestmark = pytest.mark.django_db


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


@pytest.fixture
def heard():
    calls = []

    def approved(sender, time_off, by, **kwargs):
        calls.append(("approved", time_off.pk, by))

    def cancelled(sender, time_off, by, previous_status, **kwargs):
        calls.append(("cancelled", time_off.pk, by, previous_status))

    time_off_approved.connect(approved, dispatch_uid="t-approved")
    time_off_cancelled.connect(cancelled, dispatch_uid="t-cancelled")
    yield calls
    time_off_approved.disconnect(dispatch_uid="t-approved")
    time_off_cancelled.disconnect(dispatch_uid="t-cancelled")


def today(company):
    return timezone.localdate(timezone=ZoneInfo(company.timezone))


def ask(worker, start, days=2):
    return services.request_time_off(worker, first_day=start, last_day=start + timedelta(days - 1))


def test_approval_is_announced_with_the_approver(
    company, worker, manager, heard, django_capture_on_commit_callbacks
):
    time_off = ask(worker, today(company) + timedelta(days=3))

    with django_capture_on_commit_callbacks(execute=True):
        services.decide(time_off.pk, True, by=manager.user)

    assert heard == [("approved", time_off.pk, manager)]


def test_a_rejection_is_not_an_approval(
    company, worker, manager, heard, django_capture_on_commit_callbacks
):
    time_off = ask(worker, today(company) + timedelta(days=3))

    with django_capture_on_commit_callbacks(execute=True):
        services.decide(time_off.pk, False, by=manager.user)

    assert heard == []


def test_approvers_taking_time_off_themselves_announce_it(
    company, manager, heard, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        time_off = ask(manager, today(company) + timedelta(days=3))

    assert time_off.status == TimeOff.Status.APPROVED
    assert heard == [("approved", time_off.pk, manager)]


def test_cancelling_is_announced_with_what_it_was(
    company, worker, manager, heard, django_capture_on_commit_callbacks
):
    asked = ask(worker, today(company) + timedelta(days=3))
    taken = ask(worker, today(company) + timedelta(days=10))
    services.decide(taken.pk, True, by=manager.user)

    with django_capture_on_commit_callbacks(execute=True):
        services.cancel(asked, by=worker)
        services.cancel(taken, by=worker)

    assert heard == [
        ("cancelled", asked.pk, worker, TimeOff.Status.PENDING),
        ("cancelled", taken.pk, worker, TimeOff.Status.APPROVED),
    ]


def approved(member, start: date, end: date) -> TimeOff:
    return TimeOff.objects.create(
        company=member.company,
        membership=member,
        first_day=start,
        last_day=end,
        status=TimeOff.Status.APPROVED,
    )


def test_leave_summary_counts_approved_days_in_the_period(company, member, worker):
    other = member.registered(company)
    approved(worker, date(2026, 9, 28), date(2026, 10, 3))  # crosses into the month
    approved(other, date(2026, 10, 20), date(2026, 10, 21))
    TimeOff.objects.create(
        company=company,
        membership=other,
        first_day=date(2026, 10, 5),
        last_day=date(2026, 10, 6),
        status=TimeOff.Status.PENDING,
    )
    Holiday.objects.create(company=company, date=date(2026, 10, 1), name="Teachers' Day")

    summary = queries.leave_summary(company, date(2026, 10, 1), date(2026, 10, 31))

    assert set(summary) == {worker.pk, other.pk}
    mine = summary[worker.pk]
    assert [leave.day for leave in mine.days] == [date(2026, 10, 2), date(2026, 10, 3)]
    assert mine.paid_days == Decimal(2)
    assert mine.unpaid_days == Decimal(0)
    assert mine.on(date(2026, 10, 2)).kind == "day_off"
    assert mine.on(date(2026, 10, 2)).pay_percent == 100
    assert mine.on(date(2026, 10, 1)) is None  # the holiday isn't leave
    assert summary[other.pk].paid_days == Decimal(2)


def test_leave_summary_for_some_members_and_another_company(company, other_company, member, worker):
    stranger = member.registered(other_company)
    approved(worker, date(2026, 10, 5), date(2026, 10, 5))
    approved(stranger, date(2026, 10, 5), date(2026, 10, 5))

    assert set(queries.leave_summary(company, date(2026, 10, 1), date(2026, 10, 31))) == {worker.pk}
    assert (
        queries.leave_summary(company, date(2026, 10, 1), date(2026, 10, 31), member_ids=[]) == {}
    )


def test_overlapping_rows_count_a_day_once(company, worker):
    approved(worker, date(2026, 10, 5), date(2026, 10, 7))
    approved(worker, date(2026, 10, 7), date(2026, 10, 8))

    summary = queries.leave_summary(company, date(2026, 10, 1), date(2026, 10, 31))

    assert summary[worker.pk].paid_days == Decimal(4)


def test_balance_is_zero_until_leave_balances_exist(worker):
    assert queries.balance(worker, on=date(2026, 10, 31)) == Decimal(0)
    assert queries.balance(worker, kind="sick", on=date(2026, 10, 31)) == Decimal(0)
