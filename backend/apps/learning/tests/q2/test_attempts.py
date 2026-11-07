"""Attempts (docs/PLAN-LEARNING.md §4.7): start and resume, autosave, the time limit, grading,
answer logs, counters, limits, the wait, reset, a manager's tries, checks and the review."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.learning import attempts, grading
from apps.learning.models import AnswerLog, Attempt, CheckEntry, CheckRound, Question, Status
from apps.learning.tests.q2.fixtures import person, position, question, quiz, topic

pytestmark = pytest.mark.django_db


@pytest.fixture
def awards(monkeypatch):
    """Recognition as R will answer: each new key earns points once."""
    given = {}

    def award(member, *, reason, key, points=None, note="", at=None, by=None):
        if key in given:
            return None
        given[key] = (member.pk, reason)
        return SimpleNamespace(points={"quiz": 20, "quiz_perfect": 10, "check": 15}[reason])

    monkeypatch.setattr("apps.recognition.services.award", award)
    monkeypatch.setattr("apps.recognition.conf.is_on", lambda company: True)
    return given


@pytest.fixture
def steps(monkeypatch):
    """Q1's course steps: which attempts it was told about."""
    told = []

    def on_attempt_finished(attempt):
        told.append(attempt.pk)
        return ["step"] if attempt.passed else []

    monkeypatch.setattr("apps.learning.courses.on_attempt_finished", on_attempt_finished)
    return told


def right_answers(attempt) -> dict:
    found = {
        row.pk: row
        for row in Question.objects.filter(pk__in=[i["question"] for i in attempt.items])
    }
    return {
        item["question"]: grading.right_answer(
            item["kind"], found[item["question"]].data, item["order"]
        )
        for item in attempt.items
    }


@pytest.fixture
def cold_quiz(pharmacy):
    cold = topic(pharmacy)
    asked = [
        question(pharmacy, "single", topic=cold, points=2),
        question(pharmacy, "true_false", topic=cold),
        question(pharmacy, "number", topic=cold),
    ]
    return quiz(pharmacy, asked, pass_percent=70)


def test_starting_draws_and_starting_again_resumes(cold_quiz, staff):
    attempt, started = attempts.start(cold_quiz, staff)
    assert started and attempt.number == 1 and attempt.state == "in_progress"
    assert [item["kind"] for item in attempt.items] == ["single", "true_false", "number"]
    assert [item["points"] for item in attempt.items] == [2, 1, 1]
    again, started = attempts.start(cold_quiz, staff)
    assert (again.pk, started) == (attempt.pk, False)


def test_answers_are_saved_one_by_one_and_checked(cold_quiz, staff):
    attempt, _new = attempts.start(cold_quiz, staff)
    first, second, third = (item["question"] for item in attempt.items)
    attempts.save_answer(attempt, first, {"option": "b"})
    attempts.save_answer(attempt, third, {"value": "37,25"})
    attempt.refresh_from_db()
    assert attempt.answers == {str(first): {"option": "b"}, str(third): {"value": 37.25}}
    attempts.save_answer(attempt, first, None)
    attempt.refresh_from_db()
    assert str(first) not in attempt.answers
    with pytest.raises(DomainError):
        attempts.save_answer(attempt, second, {"value": "yes"})
    with pytest.raises(DomainError):
        attempts.save_answer(attempt, 999999, {"value": True})


def test_finishing_grades_logs_counts_and_awards(cold_quiz, staff, awards, steps):
    attempt, _new = attempts.start(cold_quiz, staff)
    for question_id, answer in right_answers(attempt).items():
        attempts.save_answer(attempt, question_id, answer)
    done = attempts.finish(attempt)
    assert (done.state, done.percent, done.passed) == ("finished", 100, True)
    assert (done.score, done.max_score) == (4, 4)
    assert done.points == 30  # the first pass (20) and a perfect score (10)
    assert done.course_step_done is True and steps == [done.pk]
    logs = AnswerLog.objects.filter(attempt=done)
    assert logs.count() == 3 and all(log.correct and log.share == 1 for log in logs)
    assert {log.topic.name for log in logs} == {"Sovuq zanjir"}
    assert set(
        Question.objects.filter(pk__in=logs.values("question")).values_list("answered", "correct")
    ) == {(1, 1)}
    # Finishing again changes nothing; passing again earns nothing new.
    assert attempts.finish(done).points == 30
    assert AnswerLog.objects.filter(attempt=done).count() == 3
    second, _new = attempts.start(cold_quiz, staff)
    for question_id, answer in right_answers(second).items():
        attempts.save_answer(second, question_id, answer)
    assert attempts.finish(second).points == 0


def test_an_unanswered_question_scores_nothing_and_writes_no_log(cold_quiz, staff):
    attempt, _new = attempts.start(cold_quiz, staff)
    single = attempt.items[0]
    right = right_answers(attempt)[single["question"]]
    attempts.save_answer(attempt, single["question"], right)
    done = attempts.finish(attempt)
    assert (done.score, done.percent, done.passed) == (2, 50, False)
    assert AnswerLog.objects.filter(attempt=done).count() == 1


def test_partial_credit_follows_the_quiz(pharmacy, staff):
    multi = question(pharmacy, "multi")
    for partial, percent in ((True, 50), (False, 0)):
        test = quiz(pharmacy, [multi], partial_credit=partial, title=f"Test {partial}")
        attempt, _new = attempts.start(test, staff)
        attempts.save_answer(attempt, multi.pk, {"options": ["a"]})
        assert attempts.finish(attempt).percent == percent


def test_after_the_time_limit_what_was_saved_is_graded(cold_quiz, staff, awards):
    cold_quiz.time_limit_seconds = 60
    cold_quiz.save()
    start = timezone.now() - timedelta(minutes=5)
    attempt, _new = attempts.start(cold_quiz, staff, now=start)
    assert attempt.deadline_at == start + timedelta(seconds=60)
    first = attempt.items[0]
    attempts.save_answer(
        attempt, first["question"], right_answers(attempt)[first["question"]], now=start
    )
    with pytest.raises(DomainError):
        attempts.save_answer(attempt, attempt.items[1]["question"], {"value": False})
    attempt.refresh_from_db()
    assert (attempt.state, attempt.score, attempt.finished_at) == (
        "expired",
        2,
        attempt.deadline_at,
    )


def test_the_job_grades_attempts_whose_time_ran_out_where_learning_runs(
    cold_quiz, staff, other_company
):
    cold_quiz.time_limit_seconds = 60
    cold_quiz.save()
    long_ago = timezone.now() - timedelta(hours=1)
    attempt, _new = attempts.start(cold_quiz, staff, now=long_ago)
    other = quiz(other_company, [question(other_company, "true_false")], time_limit_seconds=60)
    outsider = person(other_company)
    theirs = Attempt.objects.create(
        company=other_company,
        quiz=other,
        membership=outsider,
        started_at=long_ago,
        deadline_at=long_ago + timedelta(minutes=1),
        items=[],
    )
    assert attempts.expire_attempts() == 1
    attempt.refresh_from_db()
    theirs.refresh_from_db()
    assert attempt.state == "expired" and theirs.state == "in_progress"


def test_reading_an_attempt_after_its_time_grades_it(cold_quiz, staff):
    cold_quiz.time_limit_seconds = 60
    cold_quiz.save()
    attempts.start(cold_quiz, staff, now=timezone.now() - timedelta(minutes=2))
    found = attempts.standing(cold_quiz, staff)
    assert found.in_progress is None and found.attempts_used == 1


def test_max_attempts_and_the_wait(cold_quiz, staff):
    cold_quiz.max_attempts, cold_quiz.retry_after_minutes = 2, 30
    cold_quiz.save()
    attempt, _new = attempts.start(cold_quiz, staff)
    attempt = attempts.finish(attempt)
    found = attempts.standing(cold_quiz, staff)
    assert (found.can_start, found.code, found.attempts_used) == (False, "wait", 1)
    assert found.retry_at == attempt.finished_at + timedelta(minutes=30)
    later = timezone.now() + timedelta(minutes=31)
    attempt, _new = attempts.start(cold_quiz, staff, now=later)
    attempts.finish(attempt, now=later)
    found = attempts.standing(cold_quiz, staff, now=later + timedelta(days=1))
    assert (found.can_start, found.code, found.max_attempts) == (False, "used_up", 2)
    with pytest.raises(DomainError):
        attempts.start(cold_quiz, staff, now=later + timedelta(days=1))


def test_a_manager_resets_attempts_and_the_person_starts_again(cold_quiz, staff, manager):
    cold_quiz.max_attempts = 1
    cold_quiz.save()
    attempt, _new = attempts.start(cold_quiz, staff)
    attempts.finish(attempt)
    assert attempts.standing(cold_quiz, staff).code == "used_up"
    assert attempts.reset(cold_quiz, staff, by=manager) == 1
    assert attempts.standing(cold_quiz, staff).can_start
    attempt.refresh_from_db()
    assert attempt.reset_at is not None and attempt.state == "finished"  # still in history


def test_a_managers_tries_never_count(cold_quiz, manager, awards, steps):
    cold_quiz.max_attempts = 1
    cold_quiz.save()
    for _ in range(3):  # no limit for a try
        attempt, _new = attempts.start(cold_quiz, manager)
        assert attempt.trial
        for question_id, answer in right_answers(attempt).items():
            attempts.save_answer(attempt, question_id, answer)
        done = attempts.finish(attempt)
        assert done.passed and done.points is None
    assert not AnswerLog.objects.exists()
    assert set(Question.objects.values_list("answered", flat=True)) == {0}
    assert awards == {} and steps == []


def test_only_the_audience_may_take_a_quiz(cold_quiz, pharmacy, staff):
    pharmacists = position(pharmacy, "Farmatsevt")
    cold_quiz.audience_all = False
    cold_quiz.save()
    cold_quiz.positions.set([pharmacists])
    with pytest.raises(attempts.NotAllowed):
        attempts.standing(cold_quiz, staff)
    pharmacist = person(pharmacy, position=pharmacists)
    assert attempts.standing(cold_quiz, pharmacist).can_start


def test_a_draft_quiz_is_nobodys(pharmacy, staff):
    draft = quiz(pharmacy, [question(pharmacy, "true_false")], status=Status.DRAFT)
    with pytest.raises(attempts.NotAllowed):
        attempts.standing(draft, staff)


def test_a_course_of_theirs_lets_them_in(cold_quiz, pharmacy, staff, monkeypatch):
    from apps.learning.models import Assignment
    from apps.learning.tests.factories import AssignmentFactory, CourseFactory, CourseStepFactory

    cold_quiz.audience_all = False
    cold_quiz.save()
    cold_quiz.positions.set([position(pharmacy)])
    with pytest.raises(attempts.NotAllowed):
        attempts.standing(cold_quiz, staff)
    course = CourseFactory(company=pharmacy)
    CourseStepFactory(course=course, kind="quiz", quiz=cold_quiz, lesson=None)
    assignment = AssignmentFactory(course=course, membership=staff)
    monkeypatch.setattr(
        "apps.learning.queries.open_assignments",
        lambda member: Assignment.objects.filter(membership=member, state="assigned"),
    )
    assert attempts.standing(cold_quiz, staff).can_start
    attempt, _new = attempts.start(cold_quiz, staff, assignment=assignment)
    assert attempt.assignment == assignment and not attempt.trial


def make_entry(regular_quiz, member, *, hours=48):
    from apps.learning.models import RegularCheck

    check = RegularCheck.objects.create(
        company=regular_quiz.company, quiz=regular_quiz, title="Dushanba tekshiruvi", weekday=0
    )
    now = timezone.now()
    round_ = CheckRound.objects.create(
        company=regular_quiz.company,
        regular_check=check,
        starts_at=now - timedelta(hours=1),
        due_at=now + timedelta(hours=hours),
        people=1,
    )
    return CheckEntry.objects.create(
        company=regular_quiz.company, check_round=round_, membership=member
    )


def test_a_check_entry_allows_one_try_and_earns_check_points(cold_quiz, staff, awards):
    entry = make_entry(cold_quiz, staff)
    found = attempts.standing(cold_quiz, staff)  # the open entry is found by itself
    assert found.entry == entry and found.max_attempts == 1
    attempt, _new = attempts.start(cold_quiz, staff)
    assert attempt.check_entry == entry
    for question_id, answer in right_answers(attempt).items():
        attempts.save_answer(attempt, question_id, answer)
    done = attempts.finish(attempt)
    assert done.points == 45  # quiz 20 + check 15 + perfect 10
    entry.refresh_from_db()
    assert entry.attempt == done
    assert AnswerLog.objects.filter(attempt=done, source="check").count() == 3
    assert attempts.standing(cold_quiz, staff, entry=entry).code == "check_done"


def test_someone_elses_entry_is_not_theirs(cold_quiz, pharmacy, staff):
    entry = make_entry(cold_quiz, person(pharmacy))
    with pytest.raises(attempts.NotAllowed):
        attempts.standing(cold_quiz, staff, entry=entry)


def test_the_review_follows_show_answers(cold_quiz, staff):
    attempt, _new = attempts.start(cold_quiz, staff)
    attempts.save_answer(attempt, attempt.items[1]["question"], {"value": True})  # wrong
    done = attempts.finish(attempt)
    review = attempts.result_shape(done, staff.user)["review"]
    assert [row["correct"] for row in review] == [False, False, False]
    assert all(row["right_answer"] is not None for row in review)
    cold_quiz.show_answers = "passed"
    cold_quiz.save()
    done.refresh_from_db()
    review = attempts.result_shape(done, staff.user)["review"]
    assert all(row["right_answer"] is None and row["explanation"] is None for row in review)
    cold_quiz.show_answers = "never"
    cold_quiz.save()
    done.refresh_from_db()
    assert attempts.result_shape(done, staff.user)["review"] is None
    full = attempts.result_shape(done, staff.user, full=True)["review"]
    assert full[1]["right_answer"] == {"value": False}
