"""Learning streaks: days off, holidays, leave and rostered rest days never break them
(PLAN-LEARNING §7.4). The company works Monday to Saturday; 7 November 2026 is a Saturday."""

from datetime import date, time, timedelta

import pytest

from apps.attendance.models import WorkShift
from apps.recognition import queries, services
from apps.recognition.models import PointsEntry, Streak
from apps.recognition.tests.conftest import at
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db

MON = date(2026, 11, 2)
FRI, SAT, SUN = date(2026, 11, 6), date(2026, 11, 7), date(2026, 11, 8)
NEXT_MON = date(2026, 11, 9)


def run(member, *days):
    streak = None
    for day in days:
        streak = services.touch_streak(member, day)
    return streak


def test_consecutive_workdays_grow_and_the_same_day_counts_once(shop, ali):
    streak = run(ali, MON, MON + timedelta(days=1), MON + timedelta(days=1))
    assert (streak.current, streak.best, streak.last_day) == (2, 2, MON + timedelta(days=1))
    assert streak.started_on == MON


def test_the_weekend_does_not_break_it(shop, ali):
    assert run(ali, FRI, SAT, NEXT_MON).current == 3  # Sunday is no workday


def test_a_missed_workday_breaks_it_and_best_stays(shop, ali):
    run(ali, MON, MON + timedelta(days=1), MON + timedelta(days=2))
    streak = run(ali, FRI)  # Thursday missed
    assert (streak.current, streak.best, streak.started_on) == (1, 3, FRI)


def test_learning_on_a_day_off_counts_and_continues(shop, ali):
    assert run(ali, SAT, SUN, NEXT_MON).current == 3


def test_holidays_are_skipped(shop, ali):
    Holiday.objects.create(company=shop, date=SAT, name="Bayram")
    assert run(ali, FRI, NEXT_MON).current == 2


def test_approved_leave_is_skipped_but_not_a_pending_request(shop, ali, nigora):
    TimeOff.objects.create(
        company=shop,
        membership=ali,
        first_day=MON,
        last_day=SAT,
        status=TimeOff.Status.APPROVED,
    )
    assert run(ali, date(2026, 10, 31), NEXT_MON).current == 2
    TimeOff.objects.create(
        company=shop, membership=nigora, first_day=MON, last_day=SAT, status="pending"
    )
    assert run(nigora, date(2026, 10, 31), NEXT_MON).current == 1


def test_a_rostered_rest_day_is_skipped(shop, ali, chilonzor):
    shop.features = [*shop.features, "attendance"]
    shop.save(update_fields=["features"])
    # A 2/2 schedule: works Monday and Tuesday, rests Wednesday and Thursday, works Friday.
    for day in (MON, MON + timedelta(days=1), FRI, SAT):
        WorkShift.objects.create(
            company=shop,
            membership=ali,
            date=day,
            starts_at=at(day, 8),
            ends_at=at(day, 20),
            branch=chilonzor,
            published_at=at(MON, 0),
        )
    assert run(ali, MON, MON + timedelta(days=1), FRI).current == 3
    # Without the attendance module the company's workdays rule: Wednesday was missed.
    shop.features = ["recognition", "learning"]
    shop.save(update_fields=["features"])
    Streak.objects.all().delete()
    assert run(ali, MON, MON + timedelta(days=1), FRI).current == 1


def test_an_older_day_reported_late_changes_nothing(shop, ali):
    run(ali, FRI)
    streak = run(ali, MON)
    assert (streak.current, streak.last_day) == (1, FRI)


def test_milestones_award_points_once(shop, ali, freeze):
    days = []
    day = date(2026, 10, 26)  # a Monday
    while len(days) < 7:
        if day.weekday() != 6:
            days.append(day)
        day += timedelta(days=1)
    streak = run(ali, *days)
    assert streak.current == 7
    milestone = PointsEntry.objects.get(membership=ali, reason="streak")
    assert milestone.points == 20
    assert milestone.key == f"streak:{ali.pk}:learning:7:2026-10-26"
    run(ali, days[-1])
    assert PointsEntry.objects.filter(membership=ali, reason="streak").count() == 1


def test_the_shown_streak_ends_when_a_workday_passed(shop, ali, freeze):
    run(ali, date(2026, 11, 4), date(2026, 11, 5))  # Wednesday, Thursday
    freeze(at(SAT, 9))  # Friday passed without learning
    assert queries.current_streak(Streak.objects.get(membership=ali), ali) == 0
    freeze(at(FRI, 9))
    assert queries.current_streak(Streak.objects.get(membership=ali), ali) == 2


def test_a_moment_is_read_as_the_company_day(shop, ali):
    late_evening = at(FRI, 23, 30)
    streak = services.touch_streak(ali, late_evening)
    assert streak.last_day == FRI
    assert time(23, 30) == late_evening.timetz().replace(tzinfo=None)
