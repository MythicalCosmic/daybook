"""The demo's shared story (apps/core/demo_plan.py) and running code at its moments
(apps/core/demo_time.py)."""

from datetime import datetime, time, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction
from django.utils import timezone

from apps.companies.models import Branch
from apps.core import demo_plan
from apps.core.demo_time import moment, quiet, run_hooks

pytestmark = pytest.mark.django_db

ZONE = ZoneInfo("Asia/Tashkent")
NOW = datetime(2026, 10, 21, 14, 0, tzinfo=ZONE)  # a Wednesday


@pytest.fixture
def story(company):
    company.slug = demo_plan.PHARMACY
    company.save(update_fields=["slug"])
    Branch.objects.create(company=company, name="Yunusobod", order=1)
    return demo_plan.Plan(company, {}, NOW)


def test_two_on_two_off_rotas_cover_every_night_at_yunusobod(story):
    for offset in range(-30, 30):
        day = story.day(offset)
        nights = [key for key in ("nigora", "dilshod") if story.rostered(key, day)]
        assert len(nights) == 1, day
    shift = story.rostered("nigora", story.today)
    assert shift.night and shift.ends - shift.starts == timedelta(hours=12)


def test_nobody_works_while_away_and_a_colleague_covers(story):
    # Madina is on leave today and tomorrow; Sardor works her evening shifts.
    assert story.away("madina", story.today) == "time_off"
    assert story.shift("madina", story.today) is None
    cover = story.shift("sardor", story.today)
    assert cover.cover_for == "madina" and cover.starts.hour == 10
    # Nobody works before joining, while suspended or after leaving.
    assert story.away("kamola", story.day(-30)) == "not_joined"
    assert story.shift("kamola", story.day(-30)) is None
    assert story.away("bobur", story.today) == "suspended"
    assert story.away("bobur", story.day(6)) is None
    assert story.away("nodira", story.today) == "left"
    # A revoked day counts again: Farrux works the stock count.
    inventory = story.inventory_day()
    assert inventory.weekday() == 5 and story.works("farrux", inventory)
    assert story.away("farrux", inventory - timedelta(days=1)) == "time_off"


def test_work_is_moved_into_the_persons_hours(story):
    """Routines and cards are finished while the person is at work, even when early or late."""
    today = story.today
    # Alisher opens Chilonzor today, 08:00 to 20:00.
    assert story.at_work("worker", today, story.at(today, time(7, 20))) == story.at(
        today, time(8, 5)
    )
    assert story.at_work("worker", today, story.at(today, time(23, 40))) == story.at(
        today, time(19, 57)
    )
    noon = story.at(today, time(12, 0))
    assert story.at_work("worker", today, noon) == noon
    # A night pharmacist's hours run into the next morning.
    starts, ends = story.hours("nigora", today)
    assert (starts.hour, ends.hour, (ends - starts).days) == (20, 8, 0)
    past_midnight = story.at(today + timedelta(days=1), time(2, 30))
    assert story.at_work("nigora", today, past_midnight) == past_midnight
    # On a day they don't work nothing moves (Madina is on leave).
    assert story.hours("madina", today) is None
    assert story.at_work("madina", today, noon) == noon


def test_a_swapped_shift_belongs_to_whoever_worked_it(story):
    [swap] = story.swaps
    day = story.day(swap.day)
    assert story.rostered(swap.who, day) is not None
    assert story.shift(swap.who, day) is None
    assert story.shift(swap.cover, day).cover_for == swap.who


def test_the_till_is_opened_by_the_first_and_closed_by_the_last_at_the_counter(story):
    # People are looked up in the company: make the whole cast.
    from apps.core.management.commands.seed_demo import Command

    company = story.company
    Command()._staff(company, demo_plan.PEOPLE, dict(story.branches), NOW)
    full = demo_plan.Plan(company, {}, NOW)
    opener, closer = full.till("C", full.today)
    assert (opener.key, closer.key) == ("worker", "sardor")  # Madina is on leave
    assert opener.starts.hour == 8 and closer.ends.hour == 22
    day, night = full.till("Y", full.today), full.till("Y", full.today, night=True)
    assert day[0].key == day[1].key == "shahzoda"
    assert night[0].key == "nigora"
    # The distributor's warehouse closes on public holidays; the pharmacies never do.
    assert full.holiday(datetime(2026, 9, 1).date()) is None


def test_distributor_holidays(company):
    company.slug = demo_plan.DISTRIBUTOR
    company.save(update_fields=["slug"])
    story = demo_plan.Plan(company, {}, NOW)
    assert story.holiday(datetime(2026, 9, 1).date()) == "Mustaqillik kuni"
    assert story.away("worker", datetime(2026, 9, 1).date()) == "holiday"


def test_moment_runs_after_commit_work_at_that_moment():
    then = timezone.now() - timedelta(days=3)
    seen = []
    with transaction.atomic(), moment(then):
        transaction.on_commit(lambda: seen.append(timezone.now()))
        assert seen == []
    assert seen == [then]


def test_run_hooks_runs_what_the_hooks_add_too_and_nothing_twice():
    seen = []
    with transaction.atomic():
        with run_hooks():
            transaction.on_commit(
                lambda: (seen.append("first"), transaction.on_commit(lambda: seen.append("then")))
            )
        assert seen == ["first", "then"]
    assert seen == ["first", "then"]  # the outer commit doesn't run them again


def test_quiet_queues_no_jobs_and_bumps_nothing():
    from apps.console import pulse
    from apps.inbox import tasks

    with quiet(), mock.patch("kombu.Producer.publish") as publish:
        assert tasks.deliver_telegram.delay(1) is None
        assert pulse.bump(1, "inbox.unread") is None
    publish.assert_not_called()
