"""When the reviews go out and to whom: Monday 08:00 in the company's time, once per period and
once per person, a review per reading scope, the beat for companies Maslahatchi doesn't write
for, Maslahatchi's own run where it does."""

from datetime import date, timedelta

import pytest

from apps.ai.agents import advisor, runner
from apps.ai.models import AgentEvent
from apps.briefings import conf, periods, reviews, scope
from apps.briefings.models import Briefing, BriefingDelivery, BriefingSettings
from apps.inbox.models import Notification

from .conftest import MONDAY, NOW, WEEK, at

pytestmark = pytest.mark.django_db


def weekly_notes(member):
    return Notification.objects.filter(recipient=member, kind="briefings.weekly")


def test_the_weekly_review_goes_on_monday_at_eight_once(ledger, people, pharmacy, freeze):
    freeze(at(MONDAY, 7, 55))
    assert reviews.tick() == 0
    assert not Briefing.objects.exists()

    freeze(NOW)
    assert reviews.tick() == 1

    review = Briefing.objects.get()
    assert (review.kind, review.day, review.language) == ("weekly", WEEK[0], "en")
    assert review.written_by == Briefing.WrittenBy.TEMPLATE
    [note] = weekly_notes(people.owner)
    assert note.title == "Weekly business review: 9–15 November"
    assert note.body.startswith(review.content["headline"])
    assert note.url == f"/c/{pharmacy.pk}/ai/advisor?review={review.pk}"
    delivery = BriefingDelivery.objects.get()
    assert (delivery.membership, delivery.via) == (people.owner, BriefingDelivery.Via.BOT)
    assert conf.get_settings(pharmacy).weekly_sent_for == WEEK[0]

    freeze(NOW + timedelta(minutes=10))
    assert reviews.tick() == 0
    freeze(at(MONDAY + timedelta(days=3), 9))
    assert reviews.tick() == 0
    assert weekly_notes(people.owner).count() == 1


def test_a_missed_monday_still_sends_it_later_that_week(ledger, people, pharmacy, freeze):
    freeze(at(MONDAY + timedelta(days=2), 14))

    assert reviews.tick() == 1
    assert Briefing.objects.get().day == WEEK[0]


def test_each_person_gets_it_once_however_often_it_is_written(ledger, people, pharmacy):
    reviews.tick()
    outcome = reviews.rewrite_latest(pharmacy, NOW, use_ai=False)

    assert outcome.reviews == 1 and outcome.sent == 0
    assert BriefingDelivery.objects.count() == 1
    assert weekly_notes(people.owner).count() == 1


def test_another_day_and_time_in_the_settings(ledger, people, pharmacy, freeze):
    from datetime import time

    row = conf.get_settings(pharmacy)
    row.weekday, row.send_at = 4, time(18, 30)
    row.save()

    assert reviews.tick() == 0
    freeze(at(MONDAY + timedelta(days=4), 18, 25))
    assert reviews.tick() == 0
    freeze(at(MONDAY + timedelta(days=4), 18, 35))
    assert reviews.tick() == 1


def test_a_switched_off_review_never_goes(ledger, people, pharmacy):
    row = conf.get_settings(pharmacy)
    row.weekly_enabled = False
    row.save()

    assert reviews.tick() == 0
    assert not Briefing.objects.exists()


def test_readers_with_reports_get_a_review_of_their_own_scope(ledger, till_days, people, pharmacy):
    row = conf.get_settings(pharmacy)
    row.recipients = BriefingSettings.Recipients.REPORTS
    row.save()

    assert reviews.tick() == 2

    owner_review = Briefing.objects.get(scope_key=scope.of(people.owner).key)
    manager_review = Briefing.objects.get(scope_key=scope.of(people.manager).key)
    assert "finance" in owner_review.facts and "finance" not in manager_review.facts
    assert manager_review.branch_ids == scope.of(people.manager).branch_ids
    assert BriefingDelivery.objects.get(membership=people.manager).briefing == manager_review
    assert not weekly_notes(people.clerk).exists()


def test_the_monthly_review_on_the_first(ledger, people, pharmacy, freeze):
    freeze(at(date(2026, 12, 1), 8, 10))

    reviews.tick()

    monthly = Briefing.objects.get(kind="monthly")
    assert monthly.day == date(2026, 11, 1)
    assert monthly.facts["period"]["end"] == "2026-11-30"
    assert (
        Notification.objects.filter(recipient=people.owner, kind="briefings.monthly").count() == 1
    )
    assert conf.get_settings(pharmacy).monthly_sent_for == date(2026, 11, 1)
    assert periods.is_due(conf.get_settings(pharmacy), "monthly", at(date(2026, 12, 2), 9)) is False


def test_where_maslahatchi_writes_the_beat_leaves_it_to_its_run(
    ledger, people, pharmacy, ai_on, freeze
):
    state = ai_on()

    assert reviews.tick() == 0  # its own run on the ai queue sends it
    state.forced = False
    assert advisor.run(pharmacy, state, NOW) == 1
    assert AgentEvent.objects.filter(agent="advisor", kind="weekly_sent").count() == 1
    assert advisor.run(pharmacy, state, NOW + timedelta(minutes=5)) == 0


def test_the_beat_sends_it_when_maslahatchis_run_is_an_hour_late(
    ledger, people, pharmacy, ai_on, freeze
):
    ai_on()
    freeze(at(MONDAY, 9, 10))

    assert reviews.tick() == 1
    assert Briefing.objects.get().written_by == Briefing.WrittenBy.TEMPLATE


def test_maslahatchis_next_run_follows_the_settings(ledger, people, pharmacy, ai_on, freeze):
    from datetime import time

    from apps.briefings import services

    state = ai_on()
    runner.schedule_first_run(state)
    state.save()
    assert state.next_run_at == at(MONDAY + timedelta(days=7), 8, 0)

    services.update_settings(pharmacy, by=people.owner, changes={"weekday": 2, "send_at": time(9)})

    state.refresh_from_db()
    assert state.next_run_at == at(MONDAY + timedelta(days=2), 9, 0)


def test_run_now_writes_last_weeks_review_again(ledger, people, pharmacy, ai_on, freeze):
    state = ai_on()
    state.forced = False
    advisor.run(pharmacy, state, NOW)
    first = Briefing.objects.get()

    state.forced = True
    later = freeze(NOW + timedelta(hours=2))
    advisor.run(pharmacy, state, later)

    again = Briefing.objects.get()
    assert again.pk == first.pk and again.written_at > first.written_at
    assert BriefingDelivery.objects.count() == 1
    assert AgentEvent.objects.filter(agent="advisor", kind="review_rewritten").exists()


def test_nothing_goes_to_a_company_with_nothing_to_review(pharmacy, people):
    assert reviews.tick() == 0
    assert not Briefing.objects.exists()


def test_the_upcoming_reviews_on_maslahatchis_page(ledger, people, pharmacy, ai_on):
    state = ai_on()

    found = advisor.upcoming(pharmacy, state, NOW)

    assert found[0] == (at(MONDAY + timedelta(days=7), 8, 0), "Weekly business review")
    assert found[1] == (at(date(2026, 12, 1), 8, 0), "Monthly business review")
    assert found[2] == (None, "Reviews written so far: 0")
