"""The demo seeds a believable attendance story through `demo_people`."""

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
from apps.attendance.tests.conftest import CHILONZOR, DAY, YUNUSOBOD, local
from apps.companies.models import Branch

pytestmark = pytest.mark.django_db


@pytest.fixture
def demo_shop(company, demo_people, freeze):
    freeze(local(DAY, 14, 0))
    company.features = ["attendance"]
    company.save()
    first = company.branches.first()
    first.name, first.latitude, first.longitude = "Chilonzor", *CHILONZOR
    first.save()
    Branch.objects.create(
        company=company, name="Yunusobod", latitude=YUNUSOBOD[0], longitude=YUNUSOBOD[1], order=1
    )
    people = demo_people(company)
    demo.seed(company, people, timezone.now())
    return company, people


def test_demo_seeds_schedules_history_today_and_requests(demo_shop):
    company, _people = demo_shop
    assert WorkSchedule.objects.filter(company=company).count() >= 6
    assert WorkShift.objects.live().filter(company=company, date__lt=DAY).count() > 100
    assert AttendanceRecord.objects.filter(company=company).count() > 100
    assert AttendanceCorrection.objects.filter(company=company, status="pending").count() == 2
    assert ShiftSwap.objects.filter(company=company, status="accepted").count() == 2
    assert WorkShift.objects.filter(company=company, published_at__isnull=True).count() >= 2
    assert WorkShift.objects.live().filter(company=company, status="open").count() == 2
    board = queries.day_board(company, clock.today(company), branch_ids=None)
    states = {row["member"]["name"]: row["state"] for row in board["people"]}
    assert states["Bekzod Mirzayev"] == "in"
    assert states["Jasur Tursunov"] == "late"
    assert board["totals"]["rostered"] >= 4


def test_demo_numbers_make_sense(demo_shop):
    company, _people = demo_shop
    summary = queries.summary(company, DAY - timedelta(days=28), DAY, branch_ids=None)["totals"]
    assert summary["present"] > 50
    assert 70 <= float(summary["on_time_percent"]) <= 98
    assert queries.pending_overtime(_people["owner"]).count() >= 1
