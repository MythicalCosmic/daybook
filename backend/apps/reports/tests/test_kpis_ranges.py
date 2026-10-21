"""The owner console's KPI contracts (docs/PLAN-OWNER.md §11.3, Package B): `team_grouped`,
`trend` and `routine_compliance` agree with `kpis.team`, follow branch scope and never count
personal tasks."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.members.tests.factories import PositionFactory
from apps.reports import kpis
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory, make_shop

pytestmark = pytest.mark.django_db

MONDAY = date(2026, 10, 12)


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


def at(shop, day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(shop.company.timezone))


@pytest.fixture
def week(shop):
    """A week of work at both branches, plus things that must never count."""
    cashier = PositionFactory(company=shop.company, name="Cashier")
    shop.worker.position = cashier
    shop.worker.save()
    routine = TaskTemplateFactory(
        company=shop.company, title="Close the till", assignees=[shop.worker]
    )

    def work(person, day, hour, *, done_at=None, **fields):
        return TaskFactory(
            assignee=person,
            created_by=shop.owner,
            branch=person.home_branch,
            due_at=at(shop, day, hour),
            completed_at=done_at,
            **({"status": Task.Status.DONE if done_at else Task.Status.TODO} | fields),
        )

    tuesday, thursday = MONDAY + timedelta(days=1), MONDAY + timedelta(days=3)
    work(
        shop.worker, MONDAY, 10, done_at=at(shop, MONDAY, 9), kind=Task.Kind.DAILY, template=routine
    )
    work(
        shop.worker,
        tuesday,
        10,
        done_at=at(shop, tuesday, 11),
        kind=Task.Kind.DAILY,
        template=routine,
    )
    work(shop.worker, thursday, 10, kind=Task.Kind.DAILY, template=routine)  # missed
    work(shop.colleague, tuesday, 12, done_at=at(shop, tuesday, 11))
    work(shop.colleague, thursday, 12, done_at=at(shop, thursday, 15))
    # Never counted: personal work and cancelled work.
    TaskFactory(assignee=shop.worker, due_at=at(shop, MONDAY, 13), branch=shop.here)
    work(shop.worker, MONDAY, 14, status=Task.Status.CANCELLED)
    return routine


def now_after(shop):
    return at(shop, MONDAY + timedelta(days=8), 9)


def test_grouped_by_member_matches_team_for_the_same_week(shop, week):
    now = now_after(shop)
    report = kpis.team(shop.company, MONDAY, MONDAY + timedelta(days=7), now, branch_ids=None)
    grouped = kpis.team_grouped(
        shop.company, MONDAY, MONDAY + timedelta(days=6), now, "member", branch_ids=None
    )
    assert [(row.member.pk, row.score) for row in grouped] == [
        (person.pk, score) for person, score in report.rows
    ]
    totals = kpis.sum_rows(grouped)
    assert (totals.on_time, totals.late, totals.missed) == (2, 2, 1)


def test_personal_tasks_never_count(shop, week):
    now = now_after(shop)
    rows = {
        row.key: row.score
        for row in kpis.team_grouped(
            shop.company, MONDAY, MONDAY + timedelta(days=6), now, "member", branch_ids=None
        )
    }
    assert rows[str(shop.worker.pk)].total == 3  # not 4: the personal one is left out


def test_branch_scope(shop, week):
    now = now_after(shop)
    here = kpis.team_grouped(
        shop.company, MONDAY, MONDAY + timedelta(days=6), now, "member", branch_ids=[shop.here.pk]
    )
    assert shop.colleague.pk not in {row.member.pk for row in here}
    assert kpis.sum_rows(here).total == 3
    nobody = kpis.team_grouped(
        shop.company, MONDAY, MONDAY + timedelta(days=6), now, "member", branch_ids=[]
    )
    assert nobody == []


def test_other_groupings(shop, week):
    now = now_after(shop)
    args = (shop.company, MONDAY, MONDAY + timedelta(days=6), now)
    positions = {
        row.label: row.score.total for row in kpis.team_grouped(*args, "position", branch_ids=None)
    }
    assert positions == {"Cashier": 3, "": 2}
    routines = {
        row.label: row.score.total for row in kpis.team_grouped(*args, "routine", branch_ids=None)
    }
    assert routines["Close the till"] == 3
    branches = {
        row.label: row.score.total for row in kpis.team_grouped(*args, "branch", branch_ids=None)
    }
    assert branches == {shop.here.name: 3, "Yunusobod": 2}
    days = kpis.team_grouped(*args, "day", branch_ids=None)
    assert len(days) == 7 and days[0].score.on_time == 1 and days[1].score.total == 2


def test_trend_per_day_and_week(shop, week):
    days = kpis.trend(
        shop.company, "on_time_percent", MONDAY, MONDAY + timedelta(days=6), "day", branch_ids=None
    )
    assert [day["total"] for day in days] == [1, 2, 0, 2, 0, 0, 0]
    assert days[0]["on_time_percent"] == 100.0 and days[2]["on_time_percent"] is None
    weeks = kpis.trend(
        shop.company, "done", MONDAY, MONDAY + timedelta(days=13), "week", branch_ids=None
    )
    assert [w["date"] for w in weeks] == [MONDAY, MONDAY + timedelta(days=7)]
    assert weeks[0]["done"] == 4


def test_routine_compliance_lists_idle_routines(shop, week):
    idle = TaskTemplateFactory(
        company=shop.company, title="Water the plants", assignees=[shop.worker]
    )
    rows = {
        row["title"]: row
        for row in kpis.routine_compliance(
            shop.company, MONDAY, MONDAY + timedelta(days=6), branch_ids=None
        )
    }
    till = rows["Close the till"]
    assert (till["made"], till["on_time"], till["late"], till["missed"]) == (3, 1, 1, 1)
    assert till["completion_percent"] == 66.7 and till["people"] == 1
    assert rows[idle.title]["made"] == 0


def test_unknown_groupings_are_refused(shop):
    with pytest.raises(ValueError):
        kpis.team_grouped(shop.company, MONDAY, MONDAY, timezone.now(), "planet", branch_ids=None)
    with pytest.raises(ValueError):
        kpis.trend(shop.company, "speed", MONDAY, MONDAY, "day", branch_ids=None)
