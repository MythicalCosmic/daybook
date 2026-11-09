"""The recognition demo on its own (no learning rows): the story of PLAN-LEARNING §14."""

import pytest
from django.utils import timezone

from apps.knowledge import topics
from apps.recognition import demo, queries
from apps.recognition.models import BadgeAward, Kudos, LevelUp, PointsEntry, Streak

pytestmark = pytest.mark.django_db


@pytest.fixture
def story(company, demo_people):
    company.features = ["recognition", "learning"]
    company.timezone = "Asia/Tashkent"
    company.save(update_fields=["features", "timezone"])
    people = demo_people(company)
    topics.add_pharmacy_topics(company, by=None)
    demo.seed(company, people, timezone.now())
    return company, people


def test_madina_leads_with_her_badges(story):
    company, people = story
    madina = people["madina"]
    for period in ("month", "all"):
        board = queries.leaderboard(company, period=period, branch_ids=None)
        assert board.rows[0].member == madina, period
    earned = set(BadgeAward.objects.filter(membership=madina).values_list("badge", flat=True))
    assert {
        "course_finisher",
        "streak_7",
        "topic_expert",
        "first_lesson",
        "perfect_score",
    } <= earned
    assert Streak.objects.get(membership=madina).current >= 7
    assert queries.summary(madina).level.number >= 3


def test_thanks_points_and_the_celebration_waiting(story):
    company, people = story
    assert Kudos.objects.filter(company=company).count() == len(demo.KUDOS)
    worker = people["worker"]
    me = queries.me(worker)
    assert [item["from"]["id"] for item in me["kudos_today"]] == [people["madina"].pk]
    assert me["unseen"], "Alisher's newest level or badge waits for the app"
    assert not BadgeAward.objects.filter(company=company, notified_at__isnull=True).exists()
    assert not LevelUp.objects.filter(company=company, notified_at__isnull=True).exists()
    # Badges and levels carry the day they were earned, not the day the demo was built.
    first = BadgeAward.objects.get(membership=people["madina"], badge="first_lesson")
    assert (timezone.now() - first.awarded_at).days >= 20
    assert PointsEntry.objects.filter(company=company, reason="adjust").count() == 1
    assert PointsEntry.objects.filter(company=company, reason="kudos").count() == len(demo.KUDOS)
