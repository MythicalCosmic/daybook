"""Attempts: starting or resuming one, saving answers, the time limit, finishing and grading
(package Q2; docs/PLAN-LEARNING.md §4.7).

    found = attempts.standing(quiz, member)                    # may they start, and why not
    attempt, started = attempts.start(quiz, member, entry=entry)
    attempts.save_answer(attempt, question_id, {"option": "b"})
    attempt = attempts.finish(attempt)                         # graded, logged, points

**Who may start** a published quiz: someone in its audience (everyone, or its positions), with
an open course holding it (`queries.open_assignments`), with an open check entry for it, or a
manager of learning trying it. A manager's own tries (`Attempt.trial`: no assignment and no
check entry) never count: no answer logs, no counters, no points, no course step, and no limit.

**Limits** are counted in the attempt's context: the attempts of one check entry (one try,
or the quiz's `max_attempts` when it sets one), else the person's other attempts of the quiz
(within the assignment's cycle when one is given). Attempts a manager reset stay in history
but no longer count, for the limit or the wait (`retry_after_minutes`).

**Finishing** grades on the server (partial credit as the quiz says), writes an `AnswerLog` per
answered question with the question's topic at that time, moves the question's counters,
calls `courses.on_attempt_finished` (Q1) and recognition (`quiz` on the first pass, `quiz_perfect`
at 100 %, `check` for a passed check entry, and the learning streak). A time limit sets
`deadline_at`; past it the attempt is graded with what was saved (`expire_attempts` every five
minutes, and on any read), as "expired". The right answers reach the person only in the
result, as the quiz's `show_answers` allows.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.learning import conf, grading, queries, quizzes
from apps.learning.audit_actions import QuizAction
from apps.learning.models import (
    AnswerLog,
    Assignment,
    Attempt,
    CheckEntry,
    Question,
    Quiz,
)
from apps.learning.services import ensure_manager
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.recognition import conf as recognition_conf
from apps.recognition import services as recognition
from apps.recognition.models import PointsEntry

logger = logging.getLogger(__name__)

DONE = (Attempt.State.FINISHED, Attempt.State.EXPIRED)
OPEN_ASSIGNMENT = (Assignment.State.ASSIGNED, Assignment.State.IN_PROGRESS)
EXPIRE_BATCH = 500


@dataclass(frozen=True)
class Standing:
    """Where a person stands with a quiz, in one context (a check entry, an assignment)."""

    can_start: bool
    reason: str | None  # why not, in the person's words
    code: str | None
    attempts_used: int
    max_attempts: int | None
    retry_at: datetime | None
    best: Attempt | None
    in_progress: Attempt | None
    questions: int
    trial: bool
    entry: CheckEntry | None = None
    assignment: Assignment | None = None


class NotAllowed(Exception):
    """The person may not take this quiz (in this context): the API answers 404."""


def local_day(company, moment: datetime):
    return timezone.localtime(moment, ZoneInfo(company.timezone)).date()


# Who may take it --------------------------------------------------------------------------


def in_audience(quiz: Quiz, member: Membership) -> bool:
    if quiz.audience_all:
        return True
    return member.position_id is not None and quiz.positions.filter(pk=member.position_id).exists()


def course_assignments(quiz: Quiz, member: Membership):
    """`member`'s open assignments whose course has a step with `quiz`."""
    return queries.open_assignments(member).filter(course__steps__quiz=quiz).distinct()


def open_entry(quiz: Quiz, member: Membership, now: datetime) -> CheckEntry | None:
    """`member`'s entry of a check round of `quiz` still open."""
    return (
        CheckEntry.objects.filter(
            membership=member,
            check_round__regular_check__quiz=quiz,
            check_round__closed_at__isnull=True,
            check_round__starts_at__lte=now,
            check_round__due_at__gt=now,
        )
        .select_related("check_round__regular_check")
        .order_by("check_round__due_at")
        .first()
    )


def _context(
    quiz, member, *, assignment, entry, now
) -> tuple[Assignment | None, CheckEntry | None]:
    """The assignment and the entry an attempt belongs to, checked; NotAllowed otherwise."""
    if entry is not None and (
        entry.membership_id != member.pk
        or entry.check_round.regular_check.quiz_id != quiz.pk
        or entry.company_id != quiz.company_id
    ):
        raise NotAllowed
    if assignment is not None and (
        assignment.membership_id != member.pk
        or assignment.state not in OPEN_ASSIGNMENT
        or not assignment.course.steps.filter(quiz=quiz).exists()
    ):
        raise NotAllowed
    return assignment, entry


def _is_trial(quiz, member, *, assignment, entry, now) -> bool:
    if assignment is not None or entry is not None:
        return False
    return member.has_perm(Perm.LEARNING_MANAGE)


# Where they stand ------------------------------------------------------------------------


def _counted(quiz: Quiz, member: Membership, *, assignment, entry):
    rows = Attempt.objects.filter(quiz=quiz, membership=member, reset_at__isnull=True)
    if entry is not None:
        return rows.filter(check_entry=entry)
    rows = rows.filter(check_entry__isnull=True, trial=False)
    if assignment is not None:
        rows = rows.filter(started_at__gte=assignment.assigned_at)
    return rows


def limit(quiz: Quiz, *, entry) -> int | None:
    """Attempts allowed in a context: a check entry gets one try unless the quiz sets more."""
    if entry is not None:
        return quiz.max_attempts or 1
    return quiz.max_attempts


def in_progress(quiz: Quiz, member: Membership) -> Attempt | None:
    return (
        Attempt.objects.filter(quiz=quiz, membership=member, state=Attempt.State.IN_PROGRESS)
        .order_by("-started_at")
        .first()
    )


def standing(
    quiz: Quiz,
    member: Membership,
    *,
    assignment: Assignment | None = None,
    entry: CheckEntry | None = None,
    now: datetime | None = None,
) -> Standing:
    """Whether `member` may start `quiz` now (in the context given), and the numbers the
    quiz's intro shows. Raises NotAllowed when they may not take it at all."""
    now = now or timezone.now()
    if quiz.company_id != member.company_id:
        raise NotAllowed
    expire_due(quiz=quiz, member=member, now=now)
    attempted = Attempt.objects.filter(quiz=quiz, membership=member).exists()
    live = quizzes.is_live(quiz)
    if not live and not attempted:
        raise NotAllowed  # a draft, or archived before they ever took it
    if entry is None and assignment is None:
        entry = open_entry(quiz, member, now)
    assignment, entry = _context(quiz, member, assignment=assignment, entry=entry, now=now)
    trial = _is_trial(quiz, member, assignment=assignment, entry=entry, now=now)
    route = (
        trial
        or entry is not None
        or assignment is not None
        or in_audience(quiz, member)
        or course_assignments(quiz, member).exists()
    )
    if not route and not attempted:
        raise NotAllowed
    counted = _counted(quiz, member, assignment=assignment, entry=entry)
    done = counted.filter(state__in=DONE)
    used = done.count()
    allowed = None if trial else limit(quiz, entry=entry)
    best = done.order_by("-percent", "finished_at").first()
    current = in_progress(quiz, member)
    last = done.order_by("-finished_at").first()
    retry_at = None
    if not trial and last is not None and quiz.retry_after_minutes:
        moment = last.finished_at + timedelta(minutes=quiz.retry_after_minutes)
        retry_at = moment if moment > now else None
    questions = quizzes.available(quiz)
    code = None
    if current is not None:
        code = None  # resuming is always possible
    elif not live:
        code = "closed"
    elif not route:
        code = "no_route"
    elif entry is not None and (
        entry.check_round.closed_at is not None or entry.check_round.due_at <= now
    ):
        code = "check_closed"
    elif not questions:
        code = "empty"
    elif allowed is not None and used >= allowed:
        code = "check_done" if entry is not None else "used_up"
    elif retry_at is not None:
        code = "wait"
    return Standing(
        can_start=code is None,
        reason=REASONS[code]() if code else None,
        code=code,
        attempts_used=used,
        max_attempts=allowed,
        retry_at=retry_at,
        best=best,
        in_progress=current,
        questions=questions,
        trial=trial,
        entry=entry,
        assignment=assignment,
    )


REASONS = {
    "closed": lambda: _("This quiz isn't open at the moment."),
    "no_route": lambda: _("This quiz isn't open for you at the moment."),
    "check_closed": lambda: _("This check has closed."),
    "empty": lambda: _("This quiz has no questions yet."),
    "used_up": lambda: _("You've used all your attempts at this quiz."),
    "check_done": lambda: _("You've already answered this check."),
    "wait": lambda: _("You can try again a little later."),
}


# Starting ---------------------------------------------------------------------------------


def start(
    quiz: Quiz,
    member: Membership,
    *,
    assignment: Assignment | None = None,
    entry: CheckEntry | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> tuple[Attempt, bool]:
    """The attempt in progress (resumed), or a new one with a fresh draw; whether it is new.
    DomainError says why one can't start; NotAllowed when they may not take the quiz. `rng`
    draws the questions and orders their options (a seeded one makes the demo repeatable);
    without it the draw is truly random."""
    now = now or timezone.now()
    with transaction.atomic():
        # One start at a time per person: two taps never make two attempts.
        Membership.objects.select_for_update().filter(pk=member.pk).first()
        found = standing(quiz, member, assignment=assignment, entry=entry, now=now)
        if found.in_progress is not None:
            return found.in_progress, False
        if not found.can_start:
            raise DomainError(found.reason)
        entry, assignment = found.entry, found.assignment
        questions = quizzes.draw(quiz, member, rng=rng)
        if not questions:
            raise DomainError(REASONS["empty"]())
        items = [
            {
                "question": question.pk,
                "kind": question.kind,
                "points": question.points,
                "order": grading.shown_order(
                    question.kind, question.data, shuffle=quiz.shuffle_options, rng=rng
                ),
            }
            for question in questions
        ]
        attempt = Attempt.objects.create(
            company_id=quiz.company_id,
            quiz=quiz,
            membership=member,
            assignment=assignment,
            check_entry=entry,
            number=Attempt.objects.filter(quiz=quiz, membership=member).count() + 1,
            started_at=now,
            deadline_at=now + timedelta(seconds=quiz.time_limit_seconds)
            if quiz.time_limit_seconds
            else None,
            items=items,
            answers={},
            trial=found.trial,
        )
    return attempt, True


# Answering --------------------------------------------------------------------------------


def _item(attempt: Attempt, question_id) -> dict | None:
    try:
        wanted = int(question_id)
    except TypeError, ValueError:
        return None
    return next((item for item in attempt.items if item["question"] == wanted), None)


def save_answer(attempt: Attempt, question_id, answer, *, now: datetime | None = None) -> None:
    """Keep one answer (autosave); `None` takes it back. DomainError after the time limit (the
    attempt is graded then) or once the attempt is over, or for an answer that doesn't fit."""
    now = now or timezone.now()
    with transaction.atomic():
        attempt = Attempt.objects.select_for_update().get(pk=attempt.pk)
        if attempt.state != Attempt.State.IN_PROGRESS:
            raise DomainError(_("This attempt is over."))
        if attempt.deadline_at is not None and now > attempt.deadline_at:
            expired = True
        else:
            expired = False
            item = _item(attempt, question_id)
            if item is None:
                raise DomainError(_("This question isn't in your attempt."))
            question = Question.objects.filter(pk=item["question"]).first()
            if question is None or question.kind != item["kind"]:
                raise DomainError(_("This question can't be answered any more."))
            clean = grading.clean_answer(question.kind, question.data, item["order"], answer)
            key = str(question.pk)
            if clean is None:
                attempt.answers.pop(key, None)
            else:
                attempt.answers[key] = clean
            attempt.save(update_fields=["answers", "updated_at"])
    if expired:
        finish(attempt, now=now)
        raise DomainError(_("Time is up: your attempt was graded with the answers you saved."))


# Finishing --------------------------------------------------------------------------------


def finish(attempt: Attempt, *, now: datetime | None = None) -> Attempt:
    """Grade the attempt (once; a finished one comes back as it is)."""
    now = now or timezone.now()
    with transaction.atomic():
        attempt = (
            Attempt.objects.select_for_update(of=("self",))
            .select_related("quiz", "membership__company", "membership__user")
            .get(pk=attempt.pk)
        )
        if attempt.state != Attempt.State.IN_PROGRESS:
            return attempt
        late = attempt.deadline_at is not None and now > attempt.deadline_at
        graded = grade_items(attempt)
        found = grading.total([(item["points"], result) for item, _q, result in graded])
        quiz = attempt.quiz
        attempt.state = Attempt.State.EXPIRED if late else Attempt.State.FINISHED
        attempt.finished_at = attempt.deadline_at if late else now
        attempt.score, attempt.max_score = found.score, found.max_score
        attempt.percent = found.percent
        attempt.passed = found.percent >= quiz.pass_percent
        attempt.save()
        if not attempt.trial:
            _log_answers(attempt, graded)
            attempt.course_step_done = _course_steps(attempt)
            attempt.points = _award(attempt)
            _touch_streak(attempt)
            if attempt.check_entry_id:
                _link_entry(attempt)
            attempt.save(update_fields=["course_step_done", "points", "updated_at"])
        company_id = attempt.company_id
        transaction.on_commit(lambda: pulse.bump(company_id, quizzes.PULSE_KEY))
    return attempt


def grade_items(attempt: Attempt) -> list[tuple[dict, Question | None, grading.Grade]]:
    """Each drawn question with its grade (a question gone or changed kind scores 0)."""
    ids = [item["question"] for item in attempt.items]
    found = {
        question.pk: question
        for question in Question.objects.filter(pk__in=ids).select_related("image")
    }
    graded = []
    for item in attempt.items:
        question = found.get(item["question"])
        if question is None or question.kind != item["kind"]:
            graded.append((item, question, grading.NOTHING))
            continue
        result = grading.grade(
            question.kind,
            question.data,
            item["order"],
            (attempt.answers or {}).get(str(question.pk)),
            partial=attempt.quiz.partial_credit,
        )
        graded.append((item, question, result))
    return graded


def _log_answers(attempt: Attempt, graded) -> None:
    source = AnswerLog.Source.CHECK if attempt.check_entry_id else AnswerLog.Source.ATTEMPT
    logs = []
    for _found, question, result in graded:
        if question is None or not result.answered:
            continue
        logs.append(
            AnswerLog(
                company_id=attempt.company_id,
                membership_id=attempt.membership_id,
                question=question,
                topic_id=question.topic_id,
                source=source,
                attempt=attempt,
                correct=result.correct,
                share=grading.share_decimal(result.share),
                at=attempt.finished_at,
            )
        )
        Question.objects.filter(pk=question.pk).update(
            answered=F("answered") + 1, correct=F("correct") + int(result.correct)
        )
    AnswerLog.objects.bulk_create(logs)


def _course_steps(attempt: Attempt) -> bool:
    """Q1's course steps for the attempt; a failure there never loses the attempt."""
    from apps.learning import courses

    try:
        with transaction.atomic():
            return bool(courses.on_attempt_finished(attempt))
    except Exception:
        logger.exception("Course steps of attempt %s could not be marked", attempt.pk)
        return False


def _award(attempt: Attempt) -> int | None:
    """Recognition for a finished attempt: the points it earned now, None while recognition
    is off. Each award is once per key, so finishing again or passing again adds nothing."""
    member = attempt.membership
    if not recognition_conf.is_on(member.company):
        return None
    wanted = []
    if attempt.passed:
        wanted.append(
            (PointsEntry.Reason.QUIZ, f"quiz:{attempt.quiz_id}:{member.pk}"),
        )
        if attempt.check_entry_id:
            wanted.append((PointsEntry.Reason.CHECK, f"check:{attempt.check_entry_id}"))
    if attempt.percent == 100:
        wanted.append(
            (PointsEntry.Reason.QUIZ_PERFECT, f"quiz-perfect:{attempt.quiz_id}:{member.pk}")
        )
    earned = 0
    for reason, key in wanted:
        try:
            with transaction.atomic():
                entry = recognition.award(member, reason=reason, key=key, at=attempt.finished_at)
        except Exception:
            logger.exception("Recognition of attempt %s failed (%s)", attempt.pk, key)
            entry = None
        earned += entry.points if entry is not None else 0
    return earned


def _touch_streak(attempt: Attempt) -> None:
    member = attempt.membership
    try:
        with transaction.atomic():
            recognition.touch_streak(member, local_day(member.company, attempt.finished_at))
    except Exception:
        logger.exception("The streak of attempt %s could not be counted", attempt.pk)


def _link_entry(attempt: Attempt) -> None:
    """The check entry keeps its best attempt (a pass over a fail, then the higher score)."""
    entry = CheckEntry.objects.select_for_update().get(pk=attempt.check_entry_id)
    current = entry.attempt
    if current is None or (attempt.passed, attempt.percent or 0) > (
        bool(current.passed),
        current.percent or 0,
    ):
        entry.attempt = attempt
        entry.save(update_fields=["attempt", "updated_at"])


def expire_due(
    *, quiz: Quiz | None = None, member: Membership | None = None, now: datetime | None = None
) -> int:
    """Grade the attempts whose time ran out (of `quiz` and `member` when given)."""
    now = now or timezone.now()
    rows = Attempt.objects.filter(state=Attempt.State.IN_PROGRESS, deadline_at__lt=now)
    if quiz is not None:
        rows = rows.filter(quiz=quiz)
    if member is not None:
        rows = rows.filter(membership=member)
    done = 0
    for attempt in rows.order_by("deadline_at")[:EXPIRE_BATCH]:
        finish(attempt, now=now)
        done += 1
    return done


def expire_attempts(now: datetime | None = None) -> int:
    """The job (every five minutes): attempts past their time limit, in companies running
    learning, are graded with what was saved."""
    now = now or timezone.now()
    done = 0
    rows = (
        Attempt.objects.filter(state=Attempt.State.IN_PROGRESS, deadline_at__lt=now)
        .select_related("company")
        .order_by("deadline_at")[:EXPIRE_BATCH]
    )
    for attempt in rows:
        if not attempt.company.is_active or not conf.is_on(attempt.company):
            continue
        try:
            finish(attempt, now=now)
            done += 1
        except Exception:  # one attempt's trouble never stops the others
            logger.exception("Attempt %s could not be graded", attempt.pk)
    return done


# Resetting --------------------------------------------------------------------------------


@transaction.atomic
def reset(quiz: Quiz, member: Membership, *, by: Membership | None) -> int:
    """Let `member` take `quiz` again: their finished attempts stay in history but stop
    counting for the limit and the wait. Audited; how many attempts it released."""
    ensure_manager(by)
    if member.company_id != quiz.company_id:
        raise DomainError(_("Pick someone of this company."))
    now = timezone.now()
    count = (
        Attempt.objects.filter(quiz=quiz, membership=member, reset_at__isnull=True)
        .filter(state__in=DONE)
        .update(reset_at=now, updated_at=now)
    )
    audit.record(
        QuizAction.ATTEMPT_RESET,
        company_id=quiz.company_id,
        actor=by.user if by is not None else None,
        target=quiz,
        member=member.pk,
        name=str(member),
        attempts=count,
    )
    company_id = quiz.company_id
    transaction.on_commit(lambda: pulse.bump(company_id, quizzes.PULSE_KEY))
    return count


# What the person sees --------------------------------------------------------------------


def questions_of(attempt: Attempt) -> dict[int, Question]:
    ids = [item["question"] for item in attempt.items]
    return {
        question.pk: question
        for question in Question.objects.filter(pk__in=ids).select_related("image")
    }


def play_shape(attempt: Attempt, user) -> dict:
    """AttemptPlay: the attempt in progress as the person sees it, without a right answer."""
    found = questions_of(attempt)
    shown = []
    for item in attempt.items:
        question = found.get(item["question"])
        if question is None:
            continue
        shape = grading.play(
            question, item["order"], image_url=quizzes.image_url(question.image, user)
        )
        shape["points"] = item["points"]
        shown.append(shape)
    quiz = attempt.quiz
    return {
        "id": attempt.pk,
        "quiz": {
            "id": quiz.pk,
            "title": quiz.title,
            "emoji": quiz.emoji,
            "pass_percent": quiz.pass_percent,
        },
        "number": attempt.number,
        "started_at": attempt.started_at,
        "deadline_at": attempt.deadline_at,
        "questions": shown,
        "answers": attempt.answers or {},
    }


def shows_answers(attempt: Attempt) -> bool:
    """Whether the result may show the right answers (the quiz's `show_answers`)."""
    rule = attempt.quiz.show_answers
    if rule == Quiz.ShowAnswers.AFTER:
        return True
    if rule != Quiz.ShowAnswers.PASSED:
        return False
    if attempt.passed:
        return True
    earlier = Attempt.objects.filter(
        quiz_id=attempt.quiz_id, membership_id=attempt.membership_id, passed=True
    ).exclude(pk=attempt.pk)
    if not attempt.trial:
        earlier = earlier.filter(trial=False)
    return earlier.exists()


def result_shape(
    attempt: Attempt, user, *, now: datetime | None = None, full: bool = False
) -> dict:
    """AttemptResult. The review follows the quiz's `show_answers` (`full`: a manager's view,
    always with the right answers): with them, or which ones were right without them, or none
    at all ("never")."""
    quiz = attempt.quiz
    review = None
    answers_shown = full or shows_answers(attempt)
    if full or quiz.show_answers != Quiz.ShowAnswers.NEVER:
        review = []
        for item, question, result in grade_items(attempt):
            if question is None:
                continue
            shape = grading.play(
                question, item["order"], image_url=quizzes.image_url(question.image, user)
            )
            shape["points"] = item["points"]
            review.append(
                {
                    "question": shape,
                    "answer": (attempt.answers or {}).get(str(question.pk)),
                    "correct": result.correct,
                    "share": float(grading.share_decimal(result.share)),
                    "right_answer": grading.right_answer(
                        question.kind, question.data, item["order"]
                    )
                    if answers_shown
                    else None,
                    "explanation": (question.explanation or None) if answers_shown else None,
                }
            )
    retry_at = None
    if not attempt.trial and quiz.retry_after_minutes and attempt.finished_at:
        moment = attempt.finished_at + timedelta(minutes=quiz.retry_after_minutes)
        retry_at = moment if moment > (now or timezone.now()) else None
    return {
        "id": attempt.pk,
        "state": attempt.state,
        "score": float(attempt.score or 0),
        "max_score": float(attempt.max_score or 0),
        "percent": attempt.percent or 0,
        "passed": bool(attempt.passed),
        "points": attempt.points,
        "retry_at": retry_at,
        "course_step_done": attempt.course_step_done,
        "review": review,
    }
