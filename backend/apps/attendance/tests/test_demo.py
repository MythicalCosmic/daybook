"""The demo seeds a believable, coherent attendance story (apps/core/demo_plan.py)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.attendance import clock, demo, queries
from apps.attendance.models import (
    AttendanceCorrection,
    AttendanceRecord,
    ShiftSwap,
    WorkSchedule,
    WorkShift,
)
from apps.attendance.tests.conftest import DAY, local
from apps.companies.models import Feature
from apps.core.management.commands.ensure_company_defaults import ensure_company_defaults
from apps.core.management.commands.seed_demo import Command
from apps.timeoff import demo as timeoff_demo
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacy(freeze):
    """Demo Dorixona's people as seed_demo makes them, its time off, then this demo, on a
    Wednesday afternoon."""
    freeze(local(DAY, 14, 0))
    now = timezone.now()
    company, people = Command()._build_pharmacy(now)
    company.features = list(Feature.values)
    company.save()
    ensure_company_defaults(company)
    timeoff_demo.seed(company, people, now)
    demo.seed(company, people, now)
    return company, people


def test_demo_seeds_schedules_history_today_and_requests(pharmacy):
    company, _people = pharmacy
    assert WorkSchedule.objects.filter(company=company).count() >= 10
    assert WorkShift.objects.live().filter(company=company, date__lt=DAY).count() > 300
    assert AttendanceRecord.objects.filter(company=company).count() > 300
    assert AttendanceCorrection.objects.filter(company=company, status="pending").count() == 2
    # Alisher's shift Gulnora agreed to work, and a pharmacist claiming an open shift.
    assert ShiftSwap.objects.filter(company=company, status="accepted").count() == 2
    assert ShiftSwap.objects.filter(company=company, status="approved").count() == 1
    assert WorkShift.objects.filter(company=company, published_at__isnull=True).count() >= 2
    # Shahzoda's holiday leaves two Yunusobod day shifts open; the stock count needs a third.
    assert WorkShift.objects.live().filter(company=company, status="open").count() == 3
    board = queries.day_board(company, clock.today(company), branch_ids=None)
    states = {row["member"]["name"]: row["state"] for row in board["people"]}
    assert states["Bekzod Mirzayev"] == "in"
    assert states["Jasur Tursunov"] == "late"  # the courier
    assert states["Sardor Rahimov"] == "in"  # working Madina's evening shift
    assert states["Nigora Azimova"] == "not_yet"  # her night starts at 20:00
    assert board["totals"]["rostered"] >= 8


def test_nobody_away_has_a_shift_or_a_check_in(pharmacy):
    company, _people = pharmacy
    away = set()
    for row in TimeOff.objects.filter(company=company, status="approved"):
        day = row.first_day
        while day <= row.last_day:
            away.add((row.membership_id, day))
            day += timedelta(days=1)
    assert away
    for shift in WorkShift.objects.working().filter(company=company):
        assert (shift.membership_id, shift.date) not in away
    for record in AttendanceRecord.objects.filter(company=company).exclude(status="absent"):
        assert (record.membership_id, record.date) not in away
    # Madina's two days are leave on the roster, and Sardor works them.
    madina = company.memberships.get(user__first_name="Madina")
    assert WorkShift.objects.filter(membership=madina, date=DAY, status="leave").exists()
    cover = WorkShift.objects.get(membership__user__first_name="Sardor", date=DAY)
    assert cover.note == "Madina o‘rniga"


def test_demo_numbers_make_sense(pharmacy):
    company, people = pharmacy
    summary = queries.summary(company, DAY - timedelta(days=28), DAY, branch_ids=None)["totals"]
    assert summary["present"] > 200
    assert 70 <= float(summary["on_time_percent"]) <= 98
    assert queries.pending_overtime(people["owner"]).count() >= 1
    # Yunusobod is open around the clock: someone works every night.
    nights = WorkShift.objects.working().filter(
        company=company, branch__code="YNS", date__range=(DAY - timedelta(days=14), DAY)
    )
    night_days = {s.date for s in nights if clock.local(company, s.starts_at).hour == 20}
    assert len(night_days) == 15
