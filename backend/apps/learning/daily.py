"""The question of the day (package Q2; docs/PLAN-LEARNING.md §4.8, §9.2).

    daily = daily.today_for(member)                  # today's question of theirs, if any
    outcome = daily.answer(daily, member, {"option": "b"})

On the company's workdays at `LearningSettings.daily_at` (company time) each approved person
(only the positions in `daily_position_ids` when set) who isn't on time off or suspended gets
one question (`send_daily_questions`, every ten minutes): from the topics of their open courses
and the company's topics, their weakest rated topic first, then the unrated ones, never a
question they saw in the last 30 days while others are left. One-tap kinds (`single`, `multi`,
`true_false`) come to the employee bot with buttons; the others only to the mini app's Home
card (the bot message says "Answer in the app").

It can be answered, in the bot or the app, until the end of that day: the result, the
explanation, the right answer, points (`daily`: 5 right, 1 for trying) and the streak. Whichever
answered first, the bot message is edited to the result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.learning import grading, quizzes
from apps.learning.models import AnswerLog, DailyQuestion, Question
from apps.members.models import Membership
from apps.recognition import conf as recognition_conf
from apps.recognition import queries as recognition_queries
from apps.recognition import services as recognition
from apps.recognition.models import PointsEntry

logger = logging.getLogger(__name__)

# Kinds answered with buttons in the bot; the others only in the app.
BOT_KINDS = (Question.Kind.SINGLE, Question.Kind.MULTI, Question.Kind.TRUE_FALSE)
# Points for a try that wasn't right (a right answer earns the company's points for "daily").
TRIED_POINTS = 1


def local_now(company, now: datetime | None = None) -> datetime:
    return timezone.localtime(now or timezone.now(), ZoneInfo(company.timezone))


def today(company, now: datetime | None = None) -> date:
    return local_now(company, now).date()


def today_for(member: Membership, now: datetime | None = None) -> DailyQuestion | None:
    """`member`'s question of the day for the company's today (made by the job), if any."""
    return (
        DailyQuestion.objects.filter(membership=member, day=today(member.company, now))
        .select_related("question__image")
        .first()
    )


@dataclass(frozen=True)
class Outcome:
    correct: bool
    share: float
    right_answer: dict
    explanation: str
    points: int | None
    streak: int | None
    answered_now: bool


def _grade(daily: DailyQuestion, answer) -> grading.Grade:
    question = daily.question
    return grading.grade(question.kind, question.data, daily.order, answer, partial=True)


def outcome_of(
    daily: DailyQuestion, *, points: int | None, streak: int | None, now: bool
) -> Outcome:
    question = daily.question
    found = _grade(daily, daily.answer)
    return Outcome(
        correct=bool(daily.correct),
        share=float(grading.share_decimal(found.share)),
        right_answer=grading.right_answer(question.kind, question.data, daily.order),
        explanation=question.explanation,
        points=points,
        streak=streak,
        answered_now=now,
    )


def streak_of(member: Membership) -> int | None:
    """The person's learning streak (None while recognition is off)."""
    summary = recognition_queries.summary(member)
    return summary.streak if summary is not None else None


def answer(
    daily: DailyQuestion, member: Membership, answer, *, now: datetime | None = None
) -> Outcome:
    """Answer the question of the day (in the bot or the app). Once only: answering again gives
    the first result back (no points). DomainError for someone else's question, a day that is
    over, or an answer that doesn't fit; the bot message is edited to the result after commit."""
    now = now or timezone.now()
    with transaction.atomic():
        daily = (
            DailyQuestion.objects.select_for_update(of=("self",))
            .select_related("question", "membership__company", "membership__user")
            .get(pk=daily.pk)
        )
        if daily.membership_id != member.pk:
            raise DomainError(_("This question isn't yours."))
        if daily.answered_at is not None:
            return outcome_of(daily, points=None, streak=streak_of(member), now=False)
        if daily.day != today(member.company, now):
            raise DomainError(_("This was the question of another day."))
        question = daily.question
        clean = grading.clean_answer(question.kind, question.data, daily.order, answer)
        if clean is None:
            raise DomainError(_("Choose an answer first."))
        found = _grade(daily, clean)
        daily.answer = clean
        daily.answered_at = now
        daily.correct = found.correct
        daily.save(update_fields=["answer", "answered_at", "correct", "updated_at"])
        AnswerLog.objects.create(
            company_id=daily.company_id,
            membership=member,
            question=question,
            topic_id=question.topic_id,
            source=AnswerLog.Source.DAILY,
            daily=daily,
            correct=found.correct,
            share=grading.share_decimal(found.share),
            at=now,
        )
        Question.objects.filter(pk=question.pk).update(
            answered=F("answered") + 1, correct=F("correct") + int(found.correct)
        )
        points = _award(daily, member, found.correct, now)
        streak = _touch_streak(member, daily.day)
        result = outcome_of(daily, points=points, streak=streak, now=True)
        daily_id = daily.pk
        transaction.on_commit(lambda: edit_bot_message(daily_id))
        company_id = daily.company_id
        transaction.on_commit(lambda: _bump(company_id))
    return result


def _bump(company_id: int) -> None:
    from apps.console import pulse

    pulse.bump(company_id, quizzes.PULSE_KEY)


def _award(daily: DailyQuestion, member: Membership, correct: bool, now: datetime) -> int | None:
    if not recognition_conf.is_on(member.company):
        return None
    try:
        with transaction.atomic():
            entry = recognition.award(
                member,
                reason=PointsEntry.Reason.DAILY,
                key=f"daily:{daily.pk}",
                points=None if correct else TRIED_POINTS,
                at=now,
            )
    except Exception:
        logger.exception("Recognition of daily question %s failed", daily.pk)
        return None
    return entry.points if entry is not None else 0


def _touch_streak(member: Membership, day: date) -> int | None:
    try:
        with transaction.atomic():
            streak = recognition.touch_streak(member, day)
    except Exception:
        logger.exception("The streak of %s could not be counted", member.pk)
        return None
    return streak.current if streak is not None else None


def play_shape(daily: DailyQuestion, user) -> dict:
    """The Home card's question of the day: the right answer only once answered."""
    question = daily.question
    answered = daily.answered_at is not None
    return {
        "id": daily.pk,
        "day": daily.day,
        "question": grading.play(
            question, daily.order, image_url=quizzes.image_url(question.image, user)
        ),
        "answered": answered,
        "correct": daily.correct if answered else None,
        "answer": daily.answer if answered else None,
        "right_answer": grading.right_answer(question.kind, question.data, daily.order)
        if answered
        else None,
        "explanation": (question.explanation or "") if answered else None,
    }


def edit_bot_message(daily_id: int) -> None:
    """Edit the bot's message of a question answered in the app (or the bot) to the result."""
    from apps.learning import bot_messages
    from apps.notifications import tasks as telegram_jobs
    from apps.notifications.telegram import BotName, serialize_markup

    daily = (
        DailyQuestion.objects.select_related("question", "membership__user", "membership__company")
        .filter(pk=daily_id)
        .first()
    )
    if daily is None or daily.chat_message_id is None or daily.answered_at is None:
        return
    user = daily.membership.user
    if user.telegram_id is None:
        return
    from django.utils import translation

    with translation.override(user.language):
        text, markup = bot_messages.daily_result(daily, streak=streak_of(daily.membership))
    telegram_jobs.edit_telegram_message.delay(
        BotName.EMPLOYEE, user.telegram_id, daily.chat_message_id, text, serialize_markup(markup)
    )
