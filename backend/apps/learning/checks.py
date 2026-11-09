"""Regular checks: "mandatory stuff asking" (package Q2; docs/PLAN-LEARNING.md §4.9).

A check sends its quiz to its audience (everyone or chosen positions, narrowed to chosen
branches) every week (a weekday) or month (a day 1 to 28) at `at` in the company's time, to
answer within `answer_within_hours`. Each sending is a round with an entry per person.

    check = checks.create_check(company, by=manager, title="Dushanba tekshiruvi", quiz_id=4,
                                every="week", weekday=0, at="10:00", answer_within_hours=48)
    checks.run_checks()                      # the job, every ten minutes
    rows = checks.my_checks(member)          # the app's list: open rounds and the last closed

`run_checks` starts the rounds that are due (a round per period: `CheckRound` is unique per
check and start, and `next_run_at` moves on; after a pause or an outage only the latest
period still open is sent), notifies each person with "Start" (the mini app's check), reminds
whoever hasn't answered at half time and two hours before the end, and closes each round at its
end: attempts still open are graded with what was saved, the counts are kept, and every manager
of learning hears how the people they see did (done, passed, the hardest question, who didn't
answer). People on time off when a round starts get no entry; reminders skip them too.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.companies.models import Branch, Feature
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.learning import attempts, notify_quizzes, quizzes
from apps.learning.audit_actions import QuizAction
from apps.learning.models import (
    AnswerLog,
    Attempt,
    CheckEntry,
    CheckRound,
    Quiz,
    RegularCheck,
    Status,
)
from apps.learning.services import ensure_manager
from apps.members import scope
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.timeoff.queries import members_off

logger = logging.getLogger(__name__)

PULSE_KEY = "learning.checks"
WINDOW = (1, 168)
LAST_CALL = timedelta(hours=2)
TITLE_MAX = 200
# Closed rounds the app still lists, and for how long.
RECENT_CLOSED = 5
RECENT_DAYS = 14
CHECK_FIELDS = {
    "title",
    "quiz_id",
    "every",
    "weekday",
    "month_day",
    "at",
    "answer_within_hours",
    "audience_all",
    "position_ids",
    "branch_ids",
}


# Making and changing checks -----------------------------------------------------------------


def _record(action: str, check: RegularCheck, by: Membership | None, **details) -> None:
    audit.record(
        action,
        company_id=check.company_id,
        actor=by.user if by is not None else None,
        target=check,
        **details,
    )
    company_id = check.company_id
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))


def _time(value) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    try:
        return time.fromisoformat(str(value)).replace(second=0, microsecond=0)
    except ValueError:
        raise DomainError(_("Enter the time as HH:MM.")) from None


def _whole(value, low: int, high: int, message: str) -> int:
    if isinstance(value, bool):
        raise DomainError(message)
    try:
        value = int(value)
    except TypeError, ValueError:
        raise DomainError(message) from None
    if not low <= value <= high:
        raise DomainError(message)
    return value


def _values(company, changes: dict) -> dict:
    values: dict = {}
    if "title" in changes:
        title = " ".join((changes["title"] or "").split())
        if not title:
            raise DomainError(_("Give the check a name."))
        if len(title) > TITLE_MAX:
            raise DomainError(_("Keep the name under %(max)s characters.") % {"max": TITLE_MAX})
        values["title"] = title
    if "quiz_id" in changes:
        quiz = Quiz.objects.filter(company=company, pk=changes["quiz_id"]).first()
        if quiz is None or quiz.status == Status.ARCHIVED:
            raise DomainError(_("Pick a quiz of this company that isn't archived."))
        values["quiz"] = quiz
    if "every" in changes:
        if changes["every"] not in RegularCheck.Every.values:
            raise DomainError(_("Pick every week or every month."))
        values["every"] = changes["every"]
    if "weekday" in changes:
        values["weekday"] = (
            None
            if changes["weekday"] in (None, "")
            else _whole(changes["weekday"], 0, 6, _("Pick a day of the week."))
        )
    if "month_day" in changes:
        values["month_day"] = (
            None
            if changes["month_day"] in (None, "")
            else _whole(changes["month_day"], 1, 28, _("Pick a day of the month, 1–28."))
        )
    if "at" in changes:
        values["at"] = _time(changes["at"])
    if "answer_within_hours" in changes:
        values["answer_within_hours"] = _whole(
            changes["answer_within_hours"],
            *WINDOW,
            _("Give 1–168 hours to answer."),
        )
    if "audience_all" in changes:
        values["audience_all"] = bool(changes["audience_all"])
    return values


def _check_schedule(check: RegularCheck) -> None:
    if check.every == RegularCheck.Every.WEEK and check.weekday is None:
        raise DomainError(_("Pick a day of the week."))
    if check.every == RegularCheck.Every.MONTH and check.month_day is None:
        raise DomainError(_("Pick a day of the month, 1–28."))


def _set_relations(check: RegularCheck, changes: dict) -> list[str]:
    changed = []
    if "position_ids" in changes:
        wanted = {int(pk) for pk in changes["position_ids"] or []}
        found = list(Position.objects.filter(company=check.company, pk__in=wanted))
        if len(found) != len(wanted):
            raise DomainError(_("Pick positions of this company."))
        check.positions.set(found)
        changed.append("positions")
    if "branch_ids" in changes:
        wanted = {int(pk) for pk in changes["branch_ids"] or []}
        found = list(Branch.objects.filter(company=check.company, pk__in=wanted))
        if len(found) != len(wanted):
            raise DomainError(_("Pick branches of this company."))
        check.branches.set(found)
        changed.append("branches")
    return changed


@transaction.atomic
def create_check(company, *, by: Membership | None, **fields) -> RegularCheck:
    ensure_manager(by)
    unknown = set(fields) - CHECK_FIELDS
    if unknown:
        raise ValueError(f"Unknown check fields: {sorted(unknown)}")
    for needed in ("title", "quiz_id"):
        if needed not in fields:
            raise DomainError(
                _("Give the check a name.") if needed == "title" else _("Pick a quiz.")
            )
    values = _values(company, fields)
    check = RegularCheck(company=company, created_by=by, **values)
    _check_schedule(check)
    check.next_run_at = next_occurrence(check, timezone.now())
    check.save()
    _set_relations(check, fields)
    _record(QuizAction.CHECK_SAVED, check, by, title=check.title)
    return check


@transaction.atomic
def update_check(check: RegularCheck, *, by: Membership | None, **changes) -> RegularCheck:
    """Change the check; its schedule moves to the next time it is due (a round already sent
    stays as it is)."""
    ensure_manager(by)
    unknown = set(changes) - CHECK_FIELDS
    if unknown:
        raise ValueError(f"Unknown check fields: {sorted(unknown)}")
    check = RegularCheck.objects.select_for_update().get(pk=check.pk)
    values = _values(check.company, changes)
    changed = sorted(name for name, value in values.items() if getattr(check, name) != value)
    for name, value in values.items():
        setattr(check, name, value)
    _check_schedule(check)
    if check.state == RegularCheck.State.ACTIVE and {"every", "weekday", "month_day", "at"} & set(
        values
    ):
        check.next_run_at = next_occurrence(check, timezone.now())
    check.save()
    changed += _set_relations(check, changes)
    if changed:
        _record(QuizAction.CHECK_SAVED, check, by, fields=changed)
    return check


@transaction.atomic
def set_check_state(check: RegularCheck, state: str, *, by: Membership | None) -> RegularCheck:
    """Pause, restart or archive a check. A paused or archived one sends nothing; started again
    it goes on from its next time (no catching up on what it missed)."""
    ensure_manager(by)
    if state not in RegularCheck.State.values:
        raise DomainError(_("Pick a state."))
    check = RegularCheck.objects.select_for_update().get(pk=check.pk)
    if check.state == state:
        return check
    check.state = state
    if state == RegularCheck.State.ACTIVE:
        check.next_run_at = next_occurrence(check, timezone.now())
    check.save(update_fields=["state", "next_run_at", "updated_at"])
    action = {
        RegularCheck.State.ACTIVE: QuizAction.CHECK_RESUMED,
        RegularCheck.State.PAUSED: QuizAction.CHECK_PAUSED,
        RegularCheck.State.ARCHIVED: QuizAction.CHECK_ARCHIVED,
    }[state]
    _record(action, check, by)
    return check


# The schedule -----------------------------------------------------------------------------


def next_occurrence(check: RegularCheck, after: datetime) -> datetime:
    """The first time after `after` the check is due, in the company's time."""
    zone = ZoneInfo(check.company.timezone)
    local = timezone.localtime(after, zone)
    if check.every == RegularCheck.Every.WEEK:
        day = local.date() + timedelta(days=(check.weekday - local.weekday()) % 7)
        moment = datetime.combine(day, check.at, tzinfo=zone)
        if moment <= after:
            moment = datetime.combine(day + timedelta(days=7), check.at, tzinfo=zone)
        return moment
    day = local.date().replace(day=check.month_day)
    moment = datetime.combine(day, check.at, tzinfo=zone)
    if moment <= after:
        year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
        moment = datetime.combine(date(year, month, check.month_day), check.at, tzinfo=zone)
    return moment


def window(check: RegularCheck) -> timedelta:
    return timedelta(hours=check.answer_within_hours)


# Rounds -----------------------------------------------------------------------------------


def audience(check: RegularCheck, day: date):
    """Who answers a round starting on `day`: approved people of its positions (everyone when
    `audience_all`), in its branches when it names any, not on time off that day."""
    people = Membership.objects.for_company(check.company).filter(status=Membership.Status.APPROVED)
    if not check.audience_all:
        people = people.filter(position__in=check.positions.all())
    branch_ids = list(check.branches.values_list("pk", flat=True))
    if branch_ids:
        people = people.filter(Q(branches__in=branch_ids) | Q(home_branch_id__in=branch_ids))
    people = Membership.objects.filter(pk__in=people.values("pk")).exclude(
        pk__in=members_off(check.company, day)
    )
    return people.select_related("user", "company").order_by("pk")


def start_round(check: RegularCheck, starts_at: datetime) -> CheckRound | None:
    """The round of `check` starting at `starts_at`, once: an entry and a notice per person.
    None when it was started already or there is nobody to ask."""
    company = check.company
    day = timezone.localtime(starts_at, ZoneInfo(company.timezone)).date()
    people = list(audience(check, day))
    try:
        with transaction.atomic():
            round_ = CheckRound.objects.create(
                company=company,
                regular_check=check,
                starts_at=starts_at,
                due_at=starts_at + window(check),
                people=len(people),
            )
    except IntegrityError:
        return None  # this period's round is out already
    entries = CheckEntry.objects.bulk_create(
        [CheckEntry(company=company, check_round=round_, membership=member) for member in people]
    )
    questions = quizzes.available(check.quiz)
    for entry, member in zip(entries, people, strict=True):
        entry.membership = member
        entry.check_round = round_
        notify_quizzes.check_started(entry, questions)
    company_id = company.pk
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))
    return round_


def due_start(check: RegularCheck, now: datetime) -> datetime | None:
    """The start of the period to send now: the latest one due that would still be open (after
    a pause or an outage, older ones are skipped). Moves `next_run_at` on."""
    moment = check.next_run_at
    if moment is None or moment > now:
        return None
    following = next_occurrence(check, moment)
    while following <= now:
        moment, following = following, next_occurrence(check, following)
    check.next_run_at = following
    check.save(update_fields=["next_run_at", "updated_at"])
    return moment if moment + window(check) > now else None


def waiting(round_: CheckRound):
    """Entries of the round not answered yet."""
    return (
        round_.entries.filter(attempt__isnull=True, membership__status=Membership.Status.APPROVED)
        .select_related("membership__user", "membership__company", "check_round__regular_check")
        .order_by("pk")
    )


def remind(round_: CheckRound, now: datetime) -> int:
    """At half time, then two hours before the end, whoever hasn't answered hears once; only
    the last call when both are due (a short window: no half-time one). How many heard."""
    half = round_.starts_at + (round_.due_at - round_.starts_at) / 2
    last = round_.due_at - LAST_CALL
    if round_.last_reminded_at is None and last > round_.starts_at and now >= last:
        step = "last"
    elif round_.half_reminded_at is None and half < last and now >= half:
        step = "half"
    else:
        return 0
    company = round_.company
    away = members_off(company, timezone.localtime(now, ZoneInfo(company.timezone)).date())
    told = 0
    with transaction.atomic():
        for entry in waiting(round_):
            if entry.membership_id in away:
                continue
            told += notify_quizzes.check_reminder(entry, step)
            entry.reminded_at = now
            entry.save(update_fields=["reminded_at", "updated_at"])
        if step == "last":
            round_.last_reminded_at = now
            round_.half_reminded_at = round_.half_reminded_at or now
        else:
            round_.half_reminded_at = now
        round_.save(update_fields=["half_reminded_at", "last_reminded_at", "updated_at"])
    return told


def close_round(round_: CheckRound, now: datetime) -> int:
    """The round's end: open attempts graded with what was saved, the counts kept, and each
    manager of learning told how the people they see did. How many digests went."""
    with transaction.atomic():
        round_ = (
            CheckRound.objects.select_for_update()
            .select_related("regular_check__company", "regular_check__quiz")
            .get(pk=round_.pk)
        )
        if round_.closed_at is not None:
            return 0
        for attempt in Attempt.objects.filter(
            check_entry__check_round=round_, state=Attempt.State.IN_PROGRESS
        ):
            attempts.finish(attempt, now=now)
        entries = list(round_.entries.select_related("attempt", "membership"))
        round_.people = len(entries)
        round_.finished = sum(1 for entry in entries if entry.attempt_id)
        round_.passed = sum(1 for entry in entries if entry.attempt and entry.attempt.passed)
        round_.closed_at = now
        round_.save(update_fields=["people", "finished", "passed", "closed_at", "updated_at"])
        sent = send_results(round_, entries)
        company_id = round_.company_id
        transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))
    _after_close(round_)
    return sent


def _after_close(round_: CheckRound) -> None:
    """The tutor works out its suggestions after a closed round (when it is on)."""
    from apps.learning import suggestions

    try:
        with transaction.atomic():
            suggestions.after_check_round(round_)
    except Exception:
        logger.exception("Suggestions after check round %s failed", round_.pk)


def facts(round_: CheckRound, entries: list[CheckEntry]) -> dict:
    """How `entries` did: done, passed, the hardest question, who didn't answer."""
    done = [entry for entry in entries if entry.attempt_id]
    attempt_ids = [entry.attempt_id for entry in done]
    weakest = None
    if attempt_ids:
        by_question: dict[int, list[bool]] = defaultdict(list)
        texts = {}
        logs = AnswerLog.objects.filter(attempt_id__in=attempt_ids).select_related("question")
        for log in logs:
            by_question[log.question_id].append(log.correct)
            texts[log.question_id] = log.question.text
        if by_question:
            question_id, marks = min(
                by_question.items(), key=lambda item: (sum(item[1]) / len(item[1]), -len(item[1]))
            )
            text = " ".join(texts[question_id].split())
            weakest = {
                "question": question_id,
                "text": text if len(text) <= 120 else text[:119] + "…",
                "percent": math.floor(sum(marks) / len(marks) * 100),
            }
    return {
        "people": len(entries),
        "done": len(done),
        "passed": sum(1 for entry in done if entry.attempt and entry.attempt.passed),
        "weakest": weakest,
        "missing": sorted(str(entry.membership) for entry in entries if not entry.attempt_id),
    }


def sees(reader: Membership, member: Membership, branch_ids: list[int] | None) -> bool:
    if branch_ids is None or reader.pk == member.pk:
        return True
    return any(branch.pk in branch_ids for branch in member.branches.all())


def send_results(round_: CheckRound, entries: list[CheckEntry]) -> int:
    readers = (
        members_with_perm(round_.company, Perm.LEARNING_MANAGE)
        .select_related("user", "role", "company")
        .order_by("pk")
    )
    members = {entry.membership_id for entry in entries}
    prefetched = {
        member.pk: member
        for member in Membership.objects.filter(pk__in=members).prefetch_related("branches")
    }
    for entry in entries:
        entry.membership = prefetched.get(entry.membership_id, entry.membership)
    sent = 0
    for reader in readers:
        branch_ids = scope.branch_ids(reader)
        mine = [entry for entry in entries if sees(reader, entry.membership, branch_ids)]
        if mine:
            sent += notify_quizzes.check_results(round_, reader, facts(round_, mine))
    return sent


def run_checks(now: datetime | None = None) -> int:
    """The job (every ten minutes): start what is due, remind, close. How many things it did."""
    now = now or timezone.now()
    done = 0
    live = Q(company__is_active=True, company__features__contains=[Feature.LEARNING])
    checks = RegularCheck.objects.filter(live, state=RegularCheck.State.ACTIVE).select_related(
        "company", "quiz"
    )
    for check in checks:
        try:
            with transaction.atomic():
                if check.next_run_at is None:
                    check.next_run_at = next_occurrence(check, now)
                    check.save(update_fields=["next_run_at", "updated_at"])
                    continue
                starts_at = due_start(check, now)
                if starts_at is None:
                    continue
                if not quizzes.is_live(check.quiz):
                    logger.info("Check %s skipped a round: its quiz isn't published", check.pk)
                    continue
                if start_round(check, starts_at) is not None:
                    done += 1
        except Exception:  # one check's trouble never stops the others
            logger.exception("Check %s could not start a round", check.pk)
    rounds = CheckRound.objects.filter(live, closed_at__isnull=True).select_related(
        "company", "regular_check"
    )
    for round_ in rounds.order_by("due_at"):
        try:
            done += close_round(round_, now) if now >= round_.due_at else remind(round_, now)
        except Exception:
            logger.exception("Check round %s could not be reminded or closed", round_.pk)
    return done


# Reading ----------------------------------------------------------------------------------


def my_checks(member: Membership, now: datetime | None = None) -> list[dict]:
    """`member`'s check entries: the open rounds (soonest due first), then the last closed."""
    now = now or timezone.now()
    rows = CheckEntry.objects.filter(membership=member).select_related(
        "check_round__regular_check", "attempt"
    )
    open_rows = rows.filter(
        check_round__closed_at__isnull=True,
        check_round__starts_at__lte=now,
        check_round__due_at__gt=now,
    ).order_by("check_round__due_at", "pk")
    closed = (
        rows.filter(check_round__starts_at__gte=now - timedelta(days=RECENT_DAYS))
        .filter(Q(check_round__closed_at__isnull=False) | Q(check_round__due_at__lte=now))
        .order_by("-check_round__due_at", "-pk")[:RECENT_CLOSED]
    )
    return [card(entry) for entry in [*open_rows, *closed]]


def card(entry: CheckEntry) -> dict:
    attempt = entry.attempt
    done = attempt is not None and attempt.finished_at is not None
    check = entry.check_round.regular_check
    return {
        "entry_id": entry.pk,
        "title": check.title,
        "quiz_id": check.quiz_id,
        "due_at": entry.check_round.due_at,
        "done": done,
        "passed": bool(attempt.passed) if done else None,
    }
