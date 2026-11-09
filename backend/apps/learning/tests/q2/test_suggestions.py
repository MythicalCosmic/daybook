"""The tutor's suggestions (docs/PLAN-LEARNING.md §4.10): when each kind is made, that it
resolves itself when its reason goes, and that a decided one isn't made again that week."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.learning import queries, suggestions
from apps.learning.models import AnswerLog, TutorSuggestion
from apps.learning.queries import Compliance, LatePerson
from apps.learning.tests.factories import CourseFactory
from apps.learning.tests.q2.fixtures import person, question, topic
from apps.recognition.models import PointsEntry

pytestmark = pytest.mark.django_db


def answers(member, topic_row, shares):
    asked = question(member.company, "true_false", topic=topic_row)
    start = timezone.now() - timedelta(days=3)
    for index, share in enumerate(shares):
        AnswerLog.objects.create(
            company=member.company,
            membership=member,
            question=asked,
            topic=topic_row,
            source="attempt",
            correct=share == 1,
            share=share,
            at=start + timedelta(minutes=index),
        )


def kinds(company) -> set[tuple]:
    return set(
        TutorSuggestion.objects.filter(company=company, state="open").values_list(
            "membership_id", "kind", "topic_id", "course_id"
        )
    )


@pytest.fixture
def covering(monkeypatch):
    """Q1's courses_for_topic, as it will answer: `covering[topic_id] = [course]`."""
    found: dict = {}
    monkeypatch.setattr(
        queries, "courses_for_topic", lambda company, topic_id: found.get(topic_id, [])
    )
    return found


def test_weak_in_a_covered_topic_assign_the_course(pharmacy, staff, covering):
    cold = topic(pharmacy)
    course = CourseFactory(company=pharmacy, title="Sovuq zanjir")
    covering[cold.pk] = [course]
    answers(staff, cold, [0, 0, 1])
    made, resolved = suggestions.refresh(pharmacy)
    assert (made, resolved) == (1, 0)
    assert kinds(pharmacy) == {(staff.pk, "assign", cold.pk, course.pk)}
    row = TutorSuggestion.objects.get()
    assert row.params == {"score": 39, "answers": 3}
    # Run again: nothing new; better now: it resolves itself.
    assert suggestions.refresh(pharmacy) == (0, 0)
    answers(staff, cold, [1, 1, 1, 1, 1])
    assert suggestions.refresh(pharmacy) == (0, 1)
    row.refresh_from_db()
    assert row.state == "done"


def test_two_weak_people_and_nothing_to_learn_from_a_lesson_is_needed(pharmacy, staff, covering):
    prices = topic(pharmacy, "Narxlar")
    other = person(pharmacy)
    answers(staff, prices, [0, 0, 0])
    suggestions.refresh(pharmacy)
    assert kinds(pharmacy) == set()  # one person is not enough
    answers(other, prices, [0, 1, 0])
    suggestions.refresh(pharmacy)
    assert kinds(pharmacy) == {(None, "lesson_needed", prices.pk, None)}
    assert TutorSuggestion.objects.get().params == {"weak": 2}


def test_strong_where_others_are_weak_could_coach(pharmacy, staff, covering):
    cold = topic(pharmacy)
    madina = person(pharmacy, first_name="Madina", last_name="Saidova")
    answers(madina, cold, [1] * 10)
    answers(staff, cold, [0, 0, 0])
    suggestions.refresh(pharmacy)
    mentor = TutorSuggestion.objects.get(kind="mentor")
    assert (mentor.membership, mentor.topic, mentor.params) == (
        madina,
        cold,
        {"score": 100, "weak": 1},
    )
    assert (
        suggestions.text(mentor)
        == "Madina Saidova knows Sovuq zanjir well (100 %) and could coach the 1 person weak in it."
    )


def test_the_weeks_top_learners_with_thirty_points(pharmacy, staff, covering):
    madina = person(pharmacy, first_name="Madina", last_name="Saidova")
    now = timezone.now()
    for member, points in ((madina, 45), (staff, 20)):
        PointsEntry.objects.create(
            company=pharmacy,
            membership=member,
            points=points,
            reason="quiz",
            key=f"test:{member.pk}",
            at=now,
        )
    suggestions.refresh(pharmacy, now)
    assert kinds(pharmacy) == {(madina.pk, "praise", None, None)}


def test_late_with_mandatory_training(pharmacy, staff, covering, monkeypatch):
    course = CourseFactory(company=pharmacy, title="Sovuq zanjir", mandatory=True)
    late = LatePerson(
        membership_id=staff.pk,
        name=str(staff),
        course_id=course.pk,
        course_title=course.title,
        due_at=timezone.now() - timedelta(days=5),
        days_late=5,
    )
    monkeypatch.setattr(
        queries,
        "compliance",
        lambda company, *, branch_ids, now=None: Compliance(1, 0, 1, late=[late]),
    )
    suggestions.refresh(pharmacy)
    row = TutorSuggestion.objects.get(kind="overdue")
    assert suggestions.text(row) == "Alisher Valiyev is 5 days late with «Sovuq zanjir»."


def test_a_dismissed_suggestion_waits_for_next_week(pharmacy, staff, manager, covering):
    prices = topic(pharmacy, "Narxlar")
    answers(staff, prices, [0, 0, 0])
    answers(person(pharmacy), prices, [0, 0, 0])
    suggestions.refresh(pharmacy)
    row = TutorSuggestion.objects.get()
    suggestions.dismiss(row, by=manager)
    assert suggestions.refresh(pharmacy) == (0, 0)
    assert suggestions.refresh(pharmacy, timezone.now() + timedelta(days=7)) == (1, 0)


def test_after_a_check_round_only_when_the_tutor_runs(pharmacy, staff, covering):
    from types import SimpleNamespace

    answers(staff, topic(pharmacy, "Narxlar"), [0, 0, 0])
    answers(person(pharmacy), topic(pharmacy, "Narxlar"), [0, 0, 0])
    assert suggestions.after_check_round(SimpleNamespace(company=pharmacy)) == 0
    assert not TutorSuggestion.objects.exists()
