"""Levels and every badge rule, once each, and the batched notices (PLAN-LEARNING §7.2, §7.3)."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.inbox.models import Notification
from apps.learning.skills import Mastery
from apps.learning.tests.factories import AssignmentFactory, CourseFactory
from apps.recognition import notify, progress, services
from apps.recognition.models import BadgeAward, LevelUp, Streak
from apps.recognition.tests.conftest import DAY, at
from apps.recognition.tests.factories import KudosFactory, PointsEntryFactory
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


def badges_of(member) -> set[tuple[str, str]]:
    return set(BadgeAward.objects.filter(membership=member).values_list("badge", "ref"))


def entries(member, reason, count, *, points=10):
    for index in range(count):
        PointsEntryFactory(membership=member, reason=reason, key=f"{reason}:{index}", points=points)


def test_levels_are_recorded_once_each(shop, ali):
    entries(ali, "quiz", 13, points=20)  # 260 points: level 3
    levels, _badges = progress.check(ali)
    assert sorted(row.number for row in levels) == [2, 3]
    assert progress.check(ali) == ([], [])
    PointsEntryFactory(membership=ali, reason="adjust", key="adjust:x", points=-200)
    assert progress.check(ali) == ([], [])  # going down takes nothing away
    PointsEntryFactory(membership=ali, reason="adjust", key="adjust:y", points=200)
    assert progress.check(ali)[0] == []  # level 3 again: no second celebration
    assert LevelUp.objects.filter(membership=ali).count() == 2


@pytest.mark.parametrize(
    ("reason", "count", "badge"),
    [
        ("lesson", 1, "first_lesson"),
        ("quiz", 1, "first_quiz"),
        ("quiz_perfect", 1, "perfect_score"),
        ("course", 1, "course_finisher"),
    ],
)
def test_first_time_badges(shop, ali, reason, count, badge):
    entries(ali, reason, count, points=0)  # worth nothing still counts
    progress.check(ali)
    assert (badge, "") in badges_of(ali)


def test_five_courses(shop, ali):
    entries(ali, "course", 4)
    progress.check(ali)
    assert ("five_courses", "") not in badges_of(ali)
    PointsEntryFactory(membership=ali, reason="course", key="course:last")
    progress.check(ali)
    assert {("course_finisher", ""), ("five_courses", "")} <= badges_of(ali)


def test_streak_badges_follow_the_best_run(shop, ali):
    Streak.objects.create(company=shop, membership=ali, current=2, best=31)
    progress.check(ali)
    assert {("streak_7", ""), ("streak_30", "")} <= badges_of(ali)
    assert ("streak_100", "") not in badges_of(ali)


def test_helper_and_thanked_count_shown_kudos(shop, ali, madina):
    for _ in range(9):
        KudosFactory(from_member=ali, to_member=madina)
    hidden = KudosFactory(from_member=ali, to_member=madina)
    hidden.hidden_at = timezone.now()
    hidden.save()
    progress.check(ali)
    progress.check(madina)
    assert ("helper", "") not in badges_of(ali) and ("thanked", "") not in badges_of(madina)
    KudosFactory(from_member=ali, to_member=madina)
    progress.check(ali)
    progress.check(madina)
    assert ("helper", "") in badges_of(ali) and ("thanked", "") in badges_of(madina)


def test_daily_10_counts_right_answers(shop, ali):
    from apps.learning.models import DailyQuestion
    from apps.learning.tests.factories import QuestionFactory

    question = QuestionFactory(company=shop)
    for index in range(10):
        DailyQuestion.objects.create(
            company=shop,
            membership=ali,
            day=DAY - timedelta(days=index),
            question=question,
            correct=index != 0,
        )
    progress.check(ali)
    assert ("daily_10", "") not in badges_of(ali)
    DailyQuestion.objects.create(
        company=shop, membership=ali, day=DAY - timedelta(days=20), question=question, correct=True
    )
    progress.check(ali)
    assert ("daily_10", "") in badges_of(ali)


def test_early_bird_a_mandatory_course_in_three_days(shop, ali, madina):
    mandatory = CourseFactory(company=shop, mandatory=True)
    optional = CourseFactory(company=shop, mandatory=False)
    start = at(DAY - timedelta(days=10))
    AssignmentFactory(
        course=optional,
        membership=madina,
        assigned_at=start,
        completed_at=start + timedelta(days=1),
    )
    AssignmentFactory(
        course=mandatory, membership=ali, assigned_at=start, completed_at=start + timedelta(days=4)
    )
    progress.check(ali)
    progress.check(madina)
    assert ("early_bird", "") not in badges_of(ali) | badges_of(madina)
    AssignmentFactory(
        course=mandatory,
        membership=madina,
        assigned_at=start,
        completed_at=start + timedelta(days=2, hours=23),
    )
    progress.check(madina)
    assert ("early_bird", "") in badges_of(madina)


def test_topic_expert_per_topic(shop, ali, monkeypatch):
    scores = {
        (ali.pk, 4): Mastery(score=92, answers=12, last_at=None, band="strong"),
        (ali.pk, 5): Mastery(score=95, answers=9, last_at=None, band="strong"),
        (ali.pk, 6): Mastery(score=89, answers=30, last_at=None, band="strong"),
    }
    monkeypatch.setattr("apps.learning.skills.mastery", lambda company, **kwargs: scores)
    progress.check(ali)
    assert {ref for key, ref in badges_of(ali) if key == "topic_expert"} == {"4"}
    scores[(ali.pk, 5)] = Mastery(score=95, answers=10, last_at=None, band="strong")
    progress.check(ali)
    assert {ref for key, ref in badges_of(ali) if key == "topic_expert"} == {"4", "5"}


def test_learning_badges_wait_for_the_learning_module(shop, ali, monkeypatch):
    shop.features = ["recognition"]
    shop.save(update_fields=["features"])
    monkeypatch.setattr(
        "apps.learning.skills.mastery",
        lambda company, **kwargs: {(ali.pk, 4): Mastery(99, 40, None, "strong")},
    )
    progress.check(ali)
    assert badges_of(ali) == set()


def test_on_time_week(shop, ali, head):
    monday = date(2026, 10, 26)
    for offset in range(5):
        due = at(monday + timedelta(days=offset), 18)
        TaskFactory(
            assignee=ali,
            created_by=head,
            due_at=due,
            status=Task.Status.DONE,
            completed_at=due - timedelta(hours=2),
        )
    assert progress.on_time_week(ali, monday)
    late = at(monday + timedelta(days=5), 18)
    TaskFactory(
        assignee=ali,
        created_by=head,
        due_at=late,
        status=Task.Status.DONE,
        completed_at=late + timedelta(minutes=5),
    )
    assert not progress.on_time_week(ali, monday)
    # Personal tasks never count, cancelled ones neither.
    assert not progress.on_time_week(ali, monday - timedelta(days=7))


def test_month_top_three(shop, ali, madina, nigora, head):
    october = date(2026, 10, 15)
    for person, points in ((ali, 40), (madina, 90), (nigora, 60), (head, 10)):
        PointsEntryFactory(membership=person, points=points, at=at(october), key=f"m:{person.pk}")
    made = services.award_month_top(shop, october)
    assert {badge.membership_id for badge in made} == {madina.pk, nigora.pk, ali.pk}
    assert ("top3_month", "2026-10") in badges_of(madina)
    assert services.award_month_top(shop, october) == []


def test_notices_are_batched_into_one_message(
    shop, ali, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        services.award(ali, reason="lesson", key="lesson:1:a", points=60)
        services.award(ali, reason="quiz", key="quiz:1:a", points=60)
    notices = Notification.objects.filter(recipient=ali, kind__startswith="recognition.")
    assert notices.count() == 1
    notice = notices.get()
    assert notice.kind == notify.LEVEL
    assert notice.title == "New level: Learner"
    assert "New badges: First lesson, First test" in notice.body
    assert "130 points to the next level." in notice.body
    assert len(sent_messages) == 1 and "Learner" in sent_messages[0]["text"]
    assert not BadgeAward.objects.filter(notified_at__isnull=True).exists()


def test_at_most_one_message_a_minute(
    shop, ali, sent_messages, monkeypatch, django_capture_on_commit_callbacks
):
    from apps.recognition import tasks

    waits = []
    monkeypatch.setattr(
        "apps.recognition.tasks.send_notices.apply_async",
        lambda args, kwargs=None, countdown=0: waits.append(countdown),
    )
    PointsEntryFactory(membership=ali, reason="lesson", key="lesson:x")
    progress.check(ali)
    notify.schedule_notices(ali.pk)
    notify.schedule_notices(ali.pk)  # already on its way: the same message carries it
    assert waits == [notify.FIRST_WAIT_SECONDS]
    with django_capture_on_commit_callbacks(execute=True):
        assert tasks.send_notices(ali.pk) is True  # the job itself, run now
    assert len(sent_messages) == 1
    notify.schedule_notices(ali.pk)
    assert len(waits) == 2 and waits[1] > 50  # a minute after the last one


def test_quiet_hours_hold_the_message(shop, ali, freeze, monkeypatch):
    from apps.recognition import tasks

    held = []
    freeze(at(DAY, 23, 30))
    PointsEntryFactory(membership=ali, reason="lesson", key="lesson:q")
    progress.check(ali)
    monkeypatch.setattr(
        "apps.recognition.tasks.send_notices.apply_async",
        lambda args, kwargs=None, countdown=0: held.append((kwargs, countdown)),
    )
    assert tasks.send_notices(ali.pk) is False
    assert held and held[0][0] == {"after_quiet": True} and held[0][1] > 3600
    assert BadgeAward.objects.get(membership=ali).notified_at is None
