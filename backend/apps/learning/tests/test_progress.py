"""Who watched what (docs/PLAN-LEARNING.md §4.2), golden cases: overlapping ranges count once,
forged ranges are capped by real time at twice the speed, seeking to the end doesn't complete, 90 %
completes once, YouTube learns its duration from the first report."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.learning import progress
from apps.learning.models import Assignment, Lesson, LessonProgress, Video
from apps.learning.tests.factories import (
    AssignmentFactory,
    CourseFactory,
    CourseStepFactory,
    LessonFactory,
)
from apps.learning.tests.helpers_courses import turn_on

pytestmark = pytest.mark.django_db

T0 = timezone.now().replace(microsecond=0)


@pytest.fixture
def staff(company, member):
    turn_on(company)
    return member(company)


@pytest.fixture
def lesson(company):
    return LessonFactory(company=company, duration_seconds=100)


def send(lesson, person, ranges, *, at, session="s1", position=None, duration=100):
    end = ranges[-1][1] if ranges else 0
    return progress.report(
        lesson,
        person,
        session=session,
        position=end if position is None else position,
        duration=duration,
        ranges=ranges,
        playing=True,
        now=T0 + timedelta(seconds=at),
    )


def row(lesson, person) -> LessonProgress:
    return LessonProgress.objects.get(lesson=lesson, membership=person)


def test_ranges_are_merged_and_overlaps_count_once(lesson, staff):
    send(lesson, staff, [[0, 10]], at=0)
    send(lesson, staff, [[5, 15]], at=10)
    send(lesson, staff, [[30, 40], [12.4, 20.4]], at=30)
    got = row(lesson, staff)
    assert got.ranges == [[0, 20], [30, 40]]
    assert got.watched_seconds == 30
    assert got.percent == 30


def test_back_to_back_reports_with_fractions_stay_joined(lesson, staff):
    send(lesson, staff, [[0, 9.6]], at=0)
    send(lesson, staff, [[9.6, 19.5]], at=10)
    send(lesson, staff, [[19.5, 29.4]], at=20)
    assert row(lesson, staff).ranges == [[0, 29]]


def test_a_forged_report_is_cut_to_real_time_at_twice_the_speed(lesson, staff):
    # The first report of a session may cover 30 s at twice the speed plus 5 s.
    send(lesson, staff, [[0, 100]], at=0)
    assert row(lesson, staff).watched_seconds == 65
    # Ten seconds later: 10 x 2 + 5 more, cut from the end of the newest range.
    send(lesson, staff, [[65, 100]], at=10)
    got = row(lesson, staff)
    assert got.ranges == [[0, 90]]
    assert got.completed_at is not None  # 90 % reached at real time


def test_watching_faster_than_twice_the_speed_counts_as_twice(lesson, staff):
    send(lesson, staff, [[0, 10]], at=0)
    send(lesson, staff, [[10, 50]], at=10)  # 40 s of video in 10 s: four times the speed
    assert row(lesson, staff).watched_seconds == 10 + 25


def test_the_excess_is_cut_from_the_newest_range(lesson, staff):
    send(lesson, staff, [[0, 5]], at=0)
    send(lesson, staff, [[20, 30], [50, 70]], at=10)  # 30 s claimed, 25 allowed
    assert row(lesson, staff).ranges == [[0, 5], [20, 30], [50, 65]]


def test_a_report_the_day_after_cant_claim_the_night(lesson, staff):
    send(lesson, staff, [[0, 10]], at=0)
    send(lesson, staff, [[10, 100]], at=86_400, session="next-day")
    assert row(lesson, staff).watched_seconds == 10 + 65
    assert row(lesson, staff).sessions == 2


def test_seeking_to_the_end_doesnt_complete(lesson, staff):
    send(lesson, staff, [[0, 10]], at=0)
    result = send(lesson, staff, [[90, 100]], at=12)
    got = row(lesson, staff)
    assert got.watched_seconds == 20
    assert not result.completed and got.completed_at is None
    assert result.position == 0  # within 5 s of the end: start over next time
    assert send(lesson, staff, [[20, 30]], at=30).position == 30


def test_ninety_percent_completes_once(company, lesson, staff, monkeypatch):
    awarded = []
    monkeypatch.setattr(
        "apps.recognition.services.award",
        lambda member, **kwargs: awarded.append(kwargs["key"]) or None,
    )
    results = [send(lesson, staff, [[s, s + 10]], at=s) for s in range(0, 100, 10)]
    done_now = [r.completed_now for r in results]
    assert done_now == [False] * 8 + [True, False]  # at 90 s of 100
    first = row(lesson, staff).completed_at
    assert first == T0 + timedelta(seconds=80)
    send(lesson, staff, [[0, 10]], at=200)
    assert row(lesson, staff).completed_at == first
    assert awarded == [f"lesson:{lesson.pk}:{staff.pk}"]
    assert row(lesson, staff).spent_seconds == 110


def test_youtube_learns_its_duration_from_the_first_report(company, staff):
    lesson = LessonFactory(company=company, duration_seconds=0)
    send(lesson, staff, [[0, 10]], at=0, duration=212.4)
    lesson.refresh_from_db()
    assert lesson.duration_seconds == 212
    send(lesson, staff, [[10, 20]], at=10, duration=999)  # kept once known
    lesson.refresh_from_db()
    assert lesson.duration_seconds == 212
    assert row(lesson, staff).percent == 20 * 100 // 212


def test_nonsense_in_a_report_is_ignored(lesson, staff):
    send(lesson, staff, [["a", 5], [7], None, [3, 2], [-10, 4], [99, 1e9]], at=0)
    assert row(lesson, staff).ranges == [[0, 4], [99, 100]]


def test_a_video_still_processing_cant_be_watched(company, staff):
    video = Video.objects.create(company=company, state=Video.State.PROCESSING)
    lesson = LessonFactory(company=company, source=Lesson.Source.UPLOAD, video=video, youtube_id="")
    with pytest.raises(DomainError, match="still being prepared"):
        send(lesson, staff, [[0, 10]], at=0)


def test_an_uploaded_video_uses_its_own_length_not_the_players(company, staff):
    video = Video.objects.create(company=company, state=Video.State.READY, duration_seconds=50)
    lesson = LessonFactory(company=company, source=Lesson.Source.UPLOAD, video=video, youtube_id="")
    send(lesson, staff, [[0, 10]], at=0, duration=5000)
    assert row(lesson, staff).percent == 20


def test_watching_moves_the_courses_that_hold_the_lesson(company, lesson, staff):
    course = CourseFactory(company=company)
    CourseStepFactory(course=course, lesson=lesson)
    assignment = AssignmentFactory(course=course, membership=staff, assigned_at=T0)
    send(lesson, staff, [[0, 10]], at=0)
    assignment.refresh_from_db()
    assert assignment.state == Assignment.State.IN_PROGRESS
    for second in range(10, 100, 10):
        send(lesson, staff, [[second, second + 10]], at=second)
    assignment.refresh_from_db()
    assert assignment.state == Assignment.State.COMPLETED
    assert assignment.steps_done == assignment.steps_total == 1


def test_trim_and_merge_helpers():
    assert progress.merge([[5, 8], [0, 5], [10, 12], [11, 15]]) == [[0, 8], [10, 15]]
    assert progress.trim([[0, 10], [5, 30]], 20) == [[0, 10], [5, 20]]
    assert progress.trim([[0, 10], [20, 25]], 7) == [[0, 7]]
    assert progress.clip([[1.5, 2.49]], 100) == []  # both ends round to 2: nothing played
    assert progress.clip([[0.4, 3.5]], 100) == [[0, 4]]
