"""The question of the day (package Q2; docs/PLAN-LEARNING.md §4.8, §9.2).

    daily = daily.today_for(member)                  # today's question of theirs, if any
    outcome = daily.answer(daily, member, {"option": "b"})

On the company's workdays at `LearningSettings.daily_at` (company time) each approved person
(only the positions in `daily_position_ids` when set) who isn't on time off or suspended gets
one question (`send_daily_questions`, every ten minutes): from the topics of their open courses
and the company's topics, their weakest rated topic first, then the unrated ones, never a
question they saw in the last 30 days while others are left, and a kind they had least lately.
One-tap kinds (`single`, `multi`, `true_false`) come to the employee bot with buttons; the
others only to the mini app's Home card (the bot message says "Answer in the app").

It can be answered, in the bot or the app, until the end of that day: the result, the
explanation, the right answer, points (`daily`: 5 right, 1 for trying) and the streak. Whichever
answered first, the bot message is edited to the result. Someone who switched the kind
`learning.daily` off for Telegram still gets the app's card.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.companies.models import Company, Feature
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.inbox.models import NotificationPreference
from apps.knowledge.models import Topic
from apps.learning import bot_messages, conf, grading, queries, quizzes, skills
from apps.learning.models import AnswerLog, DailyQuestion, Question
from apps.members.models import Membership
from apps.notifications import tasks as telegram_jobs
from apps.notifications import telegram
from apps.notifications.telegram import BotName, serialize_markup
from apps.recognition import conf as recognition_conf
from apps.recognition import queries as recognition_queries
from apps.recognition import services as recognition
from apps.recognition.models import PointsEntry
from apps.timeoff.queries import is_holiday, members_off

logger = logging.getLogger(__name__)

# Kinds answered with buttons in the bot; the others only in the app.
BOT_KINDS = bot_messages.BOT_KINDS
# Points for a try that wasn't right (a right answer earns the company's points for "daily").
TRIED_POINTS = 1
# A question of the day isn't asked again within this many days while others are left; the
# recent dailies whose kinds the next one varies from.
SEEN_DAYS = 30
RECENT_KINDS = 10
KIND = "learning.daily"


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


# Answering --------------------------------------------------------------------------------


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


def points_of(daily: DailyQuestion) -> int | None:
    """What answering it earned (None while recognition is off or nothing was given)."""
    if not recognition_conf.is_on(daily.membership.company):
        return None
    return (
        PointsEntry.objects.filter(company_id=daily.company_id, key=f"daily:{daily.pk}")
        .values_list("points", flat=True)
        .first()
    )


def answer(
    daily: DailyQuestion,
    member: Membership,
    answer,
    *,
    now: datetime | None = None,
    in_bot: bool = False,
) -> Outcome:
    """Answer the question of the day (in the bot or the app). Once only: answering again gives
    the first result back (no points). DomainError for someone else's question, a day that is
    over, or an answer that doesn't fit. Answered in the app, the bot message is edited to the
    result after commit (`in_bot`: the bot edits it itself)."""
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
        daily_id, company_id = daily.pk, daily.company_id
        if not in_bot:
            transaction.on_commit(lambda: edit_bot_message(daily_id))
        transaction.on_commit(lambda: pulse.bump(company_id, quizzes.PULSE_KEY))
    return result


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


def toggle(
    daily: DailyQuestion, member: Membership, option: str, *, now: datetime | None = None
) -> list[str]:
    """Several right answers in the bot: choose or unchoose `option`; the options chosen, in
    the order shown. Kept on the question (not yet answered) until "Answer"."""
    now = now or timezone.now()
    with transaction.atomic():
        daily = (
            DailyQuestion.objects.select_for_update(of=("self",))
            .select_related("question", "membership__company")
            .get(pk=daily.pk)
        )
        if daily.membership_id != member.pk:
            raise DomainError(_("This question isn't yours."))
        if daily.answered_at is not None:
            raise DomainError(_("You've answered it already."))
        if daily.day != today(member.company, now):
            raise DomainError(_("This was the question of another day."))
        question = daily.question
        order = grading.reconcile(question.kind, question.data, daily.order)
        if question.kind != Question.Kind.MULTI or option not in order:
            raise DomainError(_("This answer doesn't fit the question."))
        chosen = set((daily.answer or {}).get("options") or []) ^ {option}
        picked = [value for value in order if value in chosen]
        daily.answer = {"options": picked}
        daily.save(update_fields=["answer", "updated_at"])
    return picked


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
    """The bot's message of an answered question becomes the result, wherever it was answered."""
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
    with translation.override(user.language):
        text, markup = bot_messages.daily_result(
            daily, points=points_of(daily), streak=streak_of(daily.membership)
        )
    telegram_jobs.edit_telegram_message.delay(
        BotName.EMPLOYEE, user.telegram_id, daily.chat_message_id, text, serialize_markup(markup)
    )


# Choosing a question ---------------------------------------------------------------------


def course_topic_ids(member: Membership) -> set[int]:
    """Topics of the steps of `member`'s open courses (their lessons, pages and quizzes)."""
    open_ids = list(queries.open_assignments(member).values_list("course_id", flat=True))
    if not open_ids:
        return set()
    return set(
        Topic.objects.filter(company_id=member.company_id)
        .filter(
            Q(lessons__steps__course_id__in=open_ids)
            | Q(quizzes__steps__course_id__in=open_ids)
            | Q(pages__learning_steps__course_id__in=open_ids)
        )
        .values_list("pk", flat=True)
    )


def topic_order(member: Membership, topic_ids: list[int | None], rng) -> list[int | None]:
    """The topics to ask from, best first (§4.8): the weakest rated one (unless it is strong),
    then the unrated ones, then the other rated ones from the weakest; in each group the topics
    of their open courses first."""
    found = skills.mastery(member.company, member_ids=[member.pk])
    in_courses = course_topic_ids(member)

    def score(topic_id) -> int | None:
        rated = found.get((member.pk, topic_id))
        return rated.score if rated is not None else None

    rated = sorted(
        (topic_id for topic_id in topic_ids if score(topic_id) is not None),
        key=lambda topic_id: (score(topic_id), topic_id not in in_courses),
    )
    unrated = [topic_id for topic_id in topic_ids if score(topic_id) is None]
    rng.shuffle(unrated)
    unrated.sort(key=lambda topic_id: topic_id not in in_courses)
    first = [rated[0]] if rated and score(rated[0]) < skills.STRONG else []
    return first + unrated + [topic_id for topic_id in rated if topic_id not in first]


def pick(member: Membership, day: date, rng=None) -> Question | None:
    """The question of the day for `member` (§4.8); None when the bank has none in use."""
    rng = rng or random.SystemRandom()
    pool = list(
        Question.objects.filter(company_id=member.company_id, state=Question.State.ACTIVE)
        .only("pk", "kind", "topic_id", "data")
        .order_by("pk")
    )
    if not pool:
        return None
    asked = dict(
        DailyQuestion.objects.filter(membership=member)
        .order_by("day")
        .values_list("question_id", "day")
    )
    cutoff = day - timedelta(days=SEEN_DAYS)
    fresh = [question for question in pool if asked.get(question.pk, date.min) < cutoff]
    if not fresh:  # everything was asked lately: the ones asked longest ago
        oldest = min(asked.get(question.pk, date.min) for question in pool)
        fresh = [question for question in pool if asked.get(question.pk, date.min) == oldest]
    recent_kinds = list(
        DailyQuestion.objects.filter(membership=member)
        .order_by("-day")
        .values_list("question__kind", flat=True)[:RECENT_KINDS]
    )
    by_topic: dict[int | None, list[Question]] = {}
    for question in fresh:
        by_topic.setdefault(question.topic_id, []).append(question)
    best = topic_order(member, list(by_topic), rng)[0]
    choices = by_topic[best]
    rng.shuffle(choices)
    least = min(recent_kinds.count(question.kind) for question in choices)
    return next(question for question in choices if recent_kinds.count(question.kind) == least)


# The job ---------------------------------------------------------------------------------


def due_today(company, now: datetime) -> bool:
    """Whether the company sends its questions now: learning and the question of the day on,
    a workday that isn't a holiday, and past `daily_at` in its own time."""
    if not company.is_active or not conf.is_on(company):
        return False
    settings_row = conf.get_settings(company)
    if not settings_row.daily_question:
        return False
    local = local_now(company, now)
    if local.weekday() not in (company.workdays or []) or is_holiday(company, local.date()):
        return False
    return local.time() >= settings_row.daily_at


def audience(company, day: date):
    """Who gets one today: approved people (of the chosen positions), not on time off."""
    settings_row = conf.get_settings(company)
    people = Membership.objects.for_company(company).filter(status=Membership.Status.APPROVED)
    if settings_row.daily_position_ids:
        people = people.filter(position_id__in=settings_row.daily_position_ids)
    return (
        people.exclude(pk__in=members_off(company, day))
        .select_related("user", "company")
        .order_by("pk")
    )


def make_for_day(company, now: datetime, rng=None) -> list[DailyQuestion]:
    """Today's question for everyone who should have one and hasn't yet (idempotent)."""
    day = today(company, now)
    has = set(
        DailyQuestion.objects.filter(company=company, day=day).values_list(
            "membership_id", flat=True
        )
    )
    made = []
    for member in audience(company, day):
        if member.pk in has:
            continue
        question = pick(member, day, rng)
        if question is None:
            break  # nothing in use in the bank: nobody gets one
        try:
            with transaction.atomic():
                made.append(
                    DailyQuestion.objects.create(
                        company=company,
                        membership=member,
                        day=day,
                        question=question,
                        order=grading.shown_order(question.kind, question.data, rng=rng),
                    )
                )
        except IntegrityError:  # another worker made it meanwhile
            continue
    return made


def wants_telegram(member: Membership) -> bool:
    return not NotificationPreference.objects.filter(
        membership=member, kind=KIND, telegram=False
    ).exists()


def send(daily: DailyQuestion, now: datetime) -> bool:
    """The bot's message of one question (once); whether it was dealt with. A failure that may
    pass (Telegram busy) leaves it for the next run that day."""
    member = daily.membership
    user = member.user
    message_id = None
    if user.telegram_id is not None and wants_telegram(member):
        with translation.override(user.language):
            text, markup = bot_messages.daily_message(daily)
        try:
            message_id = telegram.send_message(
                BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup)
            )
        except TelegramRetryAfter:
            return False
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            logger.info("Daily question %s not delivered: %s", daily.pk, exc)
        except Exception:
            logger.exception("Daily question %s could not be sent", daily.pk)
            return False
    DailyQuestion.objects.filter(pk=daily.pk).update(
        sent_at=now, chat_message_id=message_id, updated_at=now
    )
    return True


def send_daily_questions(now: datetime | None = None) -> int:
    """The job (every ten minutes): where it is due, make today's questions and send the bot's
    messages not sent yet. How many questions it dealt with."""
    now = now or timezone.now()
    done = 0
    for company in Company.objects.filter(is_active=True, features__contains=[Feature.LEARNING]):
        try:
            if not due_today(company, now):
                continue
            make_for_day(company, now)
            waiting = DailyQuestion.objects.filter(
                company=company,
                day=today(company, now),
                sent_at__isnull=True,
                answered_at__isnull=True,
            ).select_related("question", "membership__user", "membership__company")
            for daily in waiting:
                if send(daily, now):
                    done += 1
        except Exception:  # one company's trouble never stops the others
            logger.exception("Daily questions of company %s failed", company.pk)
    return done


# Settings ---------------------------------------------------------------------------------


SETTING_FIELDS = {"daily_question", "daily_at", "daily_position_ids"}


@transaction.atomic
def update_settings(company, *, by: Membership | None, **changes):
    """The question of the day's settings (`LearningSettings.daily_*`), audited."""
    from datetime import time

    from apps.audit import services as audit
    from apps.learning.audit_actions import QuizAction
    from apps.learning.services import ensure_manager
    from apps.members.models import Position

    ensure_manager(by)
    unknown = set(changes) - SETTING_FIELDS
    if unknown:
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    row = conf.get_settings(company)
    row = type(row).objects.select_for_update().get(pk=row.pk)
    changed = []
    if "daily_question" in changes and row.daily_question != bool(changes["daily_question"]):
        row.daily_question = bool(changes["daily_question"])
        changed.append("daily_question")
    if "daily_at" in changes:
        try:
            moment = time.fromisoformat(str(changes["daily_at"])).replace(second=0, microsecond=0)
        except ValueError:
            raise DomainError(_("Enter the time as HH:MM.")) from None
        if moment != row.daily_at:
            row.daily_at = moment
            changed.append("daily_at")
    if "daily_position_ids" in changes:
        wanted = sorted({int(pk) for pk in changes["daily_position_ids"] or []})
        found = Position.objects.filter(company=company, pk__in=wanted).count()
        if found != len(wanted):
            raise DomainError(_("Pick positions of this company."))
        if wanted != sorted(row.daily_position_ids or []):
            row.daily_position_ids = wanted
            changed.append("daily_position_ids")
    if changed:
        row.save()
        audit.record(
            QuizAction.DAILY_CHANGED,
            company_id=company.pk,
            actor=by.user if by is not None else None,
            target=row,
            fields=changed,
        )
        company_id = company.pk
        transaction.on_commit(lambda: pulse.bump(company_id, quizzes.PULSE_KEY))
    return row


def today_stats(company, now: datetime | None = None) -> dict:
    """Today's questions of the day: how many were asked, answered and answered right."""
    day = today(company, now)
    rows = DailyQuestion.objects.filter(company=company, day=day)
    return {
        "day": day,
        "asked": rows.count(),
        "answered": rows.filter(answered_at__isnull=False).count(),
        "right": rows.filter(correct=True).count(),
    }
