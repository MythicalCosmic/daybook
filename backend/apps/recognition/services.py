"""Business logic of recognition: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

**The contract other apps call** (docs/PLAN-LEARNING.md §7.4; signatures fixed, pinned by
`tests/test_contract.py`):

    award(member, reason=PointsEntry.Reason.QUIZ, key=f"quiz:{quiz.pk}:{member.pk}")
    touch_streak(member, day)                 # the company's date of something learned

Both are safe to call from anywhere, any number of times: they do nothing while the company's
`recognition` module is off, and `key` / `day` make a repeat a no-op. For a wrong answer to the
question of the day pass the "tried" points:

    tried = rules.points_for(conf.get_settings(company), "daily_tried")
    award(member, reason="daily", key=f"daily:{daily.pk}", points=tried)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, F
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.recognition import conf, progress, rules, streaks
from apps.recognition.audit_actions import RecognitionAction
from apps.recognition.models import BadgeAward, Kudos, LevelUp, PointsEntry, Streak

PULSE = "recognition"
SMALLINT = 32767
MESSAGE_MAX = 200


# Helpers --------------------------------------------------------------------------------------


def _user(by: Membership | None):
    return by.user if by is not None else None


def _bump(company_id: int) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE))


def _check_later(member_id: int) -> None:
    """After commit: the levels and badges the new points may have earned (a Celery job on the
    default queue, one per person at a time)."""

    def run() -> None:
        from apps.recognition import tasks

        if cache.add(f"recognition:check:{member_id}", 1, timeout=10):
            tasks.check_member.delay(member_id)

    transaction.on_commit(run)


def local_today(company, now: datetime | None = None) -> date:
    return timezone.localtime(now or timezone.now(), ZoneInfo(company.timezone)).date()


def day_bounds(company, day: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(company.timezone)
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    return start, start + timedelta(days=1)


def _ensure_manager(by: Membership | None, company) -> None:
    if by is None:
        return
    if by.company_id != company.pk or not by.has_perm(Perm.RECOGNITION_MANAGE):
        raise PermissionDenied(_("Only owners change points, kudos and recognition settings."))


def _ensure_on(company) -> None:
    if not conf.is_on(company):
        raise DomainError(_("Recognition isn't switched on in this company."))


# The contract ---------------------------------------------------------------------------------


def award(
    member: Membership,
    *,
    reason: str,
    key: str,
    points: int | None = None,
    note: str = "",
    at: datetime | None = None,
    by: Membership | None = None,
) -> PointsEntry | None:
    """Give `member` points for one thing, once per `key` in the company.

    `points` defaults to the company's points for `reason` (`RecognitionSettings.points_table`,
    else the defaults of `apps.recognition.rules`). Returns the new entry, or None when nothing
    was given: the module or its points are off, `member` isn't approved, or `key` was already
    used. After commit it checks the badges the award may have earned and the level reached,
    and tells the person (one message, never more than one a minute). Must stay cheap: called
    in the request that finished the lesson or the quiz.

    What was earned is kept even when it is worth nothing (the company gives 0 for it, or its
    points are off): badges count it, the totals don't."""
    if reason not in PointsEntry.Reason.values:
        raise ValueError(f"Unknown points reason {reason!r}.")
    if not key or len(key) > 80:
        raise ValueError(f"A points key has 1 to 80 characters, not {key!r}.")
    company = member.company
    if not conf.is_on(company) or member.status != Membership.Status.APPROVED:
        return None
    settings = conf.get_settings(company)
    if points is None:
        points = rules.points_for(settings, reason)
    points = max(-SMALLINT, min(SMALLINT, int(points))) if settings.points_enabled else 0
    try:
        with transaction.atomic():
            entry = PointsEntry.objects.create(
                company=company,
                membership=member,
                points=points,
                reason=reason,
                key=key,
                at=at or timezone.now(),
                note=(note or "")[:MESSAGE_MAX],
                by=by,
            )
    except IntegrityError:
        return None  # this key was used already: nothing twice
    _check_later(member.pk)
    if points:
        _bump(company.pk)
    return entry if points else None


def touch_streak(member: Membership, day: date, *, kind: str = "learning") -> Streak | None:
    """Count `day` (the company's date) for `member`'s streak of `kind`: the run grows by one
    when the last counted day was the previous workday (days off, holidays and approved leave
    in between don't break it), stays when `day` was already counted, starts again at 1
    otherwise. Streak milestones (7, 30, 100 days) award points and badges. Returns the streak,
    or None while the module is off."""
    company = member.company
    if not conf.is_on(company) or member.status != Membership.Status.APPROVED:
        return None
    if isinstance(day, datetime):
        day = timezone.localtime(day, ZoneInfo(company.timezone)).date()
    with transaction.atomic():
        streak, _created = (
            Streak.objects.select_for_update()
            .filter(company=company)
            .get_or_create(membership=member, kind=kind, defaults={"company": company})
        )
        if streak.last_day is not None and day <= streak.last_day:
            return streak  # counted already (or an older day reported late)
        if streak.last_day is not None and streaks.continues(member, streak.last_day, day):
            streak.current += 1
        else:
            streak.current = 1
            streak.started_on = day
        if streak.started_on is None:
            streak.started_on = day
        streak.best = max(streak.best, streak.current)
        streak.last_day = day
        streak.save(update_fields=["current", "best", "last_day", "started_on", "updated_at"])
    if streak.current in rules.STREAK_MILESTONES:
        length = streak.current
        award(
            member,
            reason=PointsEntry.Reason.STREAK,
            key=f"streak:{member.pk}:{kind}:{length}:{streak.started_on.isoformat()}",
            points=rules.points_for(conf.get_settings(company), f"streak_{length}"),
        )
    _check_later(member.pk)
    return streak


# Corrections ----------------------------------------------------------------------------------


def adjust(member: Membership, *, points: int, note: str, by: Membership | None) -> PointsEntry:
    """An owner's correction (± points with a note), audited."""
    company = member.company
    _ensure_manager(by, company)
    _ensure_on(company)
    if not conf.get_settings(company).points_enabled:
        raise DomainError(_("Points are switched off in this company."))
    if isinstance(points, bool) or not isinstance(points, int) or points == 0:
        raise DomainError(_("Give a whole number of points, above or below zero."))
    if abs(points) > rules.MAX_ADJUST:
        raise DomainError(
            _("A correction is at most %(max)s points either way.") % {"max": rules.MAX_ADJUST}
        )
    note = (note or "").strip()
    if not note:
        raise DomainError(_("Say why: the person sees the note next to the points."))
    if len(note) > MESSAGE_MAX:
        raise DomainError(_("Keep the note under %(max)s characters.") % {"max": MESSAGE_MAX})
    entry = PointsEntry.objects.create(
        company=company,
        membership=member,
        points=points,
        reason=PointsEntry.Reason.ADJUST,
        key=f"adjust:{uuid.uuid4().hex}",
        at=timezone.now(),
        note=note,
        by=by,
    )
    audit.record(
        RecognitionAction.POINTS_ADJUSTED,
        company_id=company.pk,
        actor=_user(by),
        target=member,
        required_perm=Perm.RECOGNITION_MANAGE,
        points=points,
        note=note,
    )
    _check_later(member.pk)
    _bump(company.pk)
    return entry


# Kudos ----------------------------------------------------------------------------------------


def kudos_left(member: Membership, *, now: datetime | None = None) -> int:
    """How many more colleagues `member` may thank today (the company's day)."""
    settings = conf.get_settings(member.company)
    start, end = day_bounds(member.company, local_today(member.company, now))
    given = Kudos.objects.filter(
        from_member=member, created_at__gte=start, created_at__lt=end
    ).count()
    return max(0, settings.kudos_per_day - given)


def send_kudos(
    by: Membership,
    *,
    to: Membership,
    badge: str = Kudos.Badge.THANKS,
    message: str = "",
    task=None,
) -> Kudos:
    """Thanks from `by` to a colleague: never oneself, someone approved of the same company,
    at most `kudos_per_day` a day. The receiver gets the kudos points and a bot message."""
    company = by.company
    _ensure_on(company)
    settings = conf.get_settings(company)
    if not settings.kudos_enabled:
        raise DomainError(_("Thanks between colleagues aren't switched on in this company."))
    if by.status != Membership.Status.APPROVED:
        raise PermissionDenied(_("Only people working here can thank colleagues."))
    if to.company_id != company.pk:
        raise DomainError(_("Pick a colleague of this company."))
    if to.pk == by.pk:
        raise DomainError(_("You can't thank yourself. Pick a colleague."))
    if to.status != Membership.Status.APPROVED:
        raise DomainError(_("%(name)s isn't working here now.") % {"name": to})
    if badge not in Kudos.Badge.values:
        raise DomainError(_("Pick what you thank them for."))
    message = " ".join((message or "").split())
    if len(message) > MESSAGE_MAX:
        raise DomainError(_("Keep it under %(max)s characters.") % {"max": MESSAGE_MAX})
    if task is not None and task.company_id != company.pk:
        raise DomainError(_("Pick a task of this company."))
    with transaction.atomic():
        # One giver at a time, so two quick taps can't both pass the daily limit.
        Membership.objects.select_for_update().filter(pk=by.pk).first()
        if kudos_left(by) <= 0:
            raise DomainError(
                ngettext(
                    "You can thank %(count)s colleague a day. More tomorrow.",
                    "You can thank %(count)s colleagues a day. More tomorrow.",
                    settings.kudos_per_day,
                )
                % {"count": settings.kudos_per_day}
            )
        kudos = Kudos.objects.create(
            company=company,
            from_member=by,
            to_member=to,
            badge=badge,
            message=message,
            task=task,
        )
        award(
            to,
            reason=PointsEntry.Reason.KUDOS,
            key=f"kudos:{kudos.pk}",
            at=kudos.created_at,
            by=by,
        )
    _check_later(by.pk)  # the giver's "helper" badge
    kudos_id = kudos.pk
    transaction.on_commit(lambda: _kudos_sent(kudos_id))
    _bump(company.pk)
    return kudos


def _kudos_sent(kudos_id: int) -> None:
    from apps.recognition import tasks

    tasks.kudos_sent.delay(kudos_id)


def hide_kudos(kudos: Kudos, *, by: Membership | None) -> Kudos:
    """An owner hides an inappropriate thank-you: it disappears from every feed, and the points
    it gave go with it. Audited."""
    _ensure_manager(by, kudos.company)
    if kudos.hidden_at is not None:
        return kudos
    with transaction.atomic():
        kudos.hidden_at = timezone.now()
        kudos.hidden_by = _user(by)
        kudos.save(update_fields=["hidden_at", "hidden_by", "updated_at"])
        removed = PointsEntry.objects.filter(
            company_id=kudos.company_id, key=f"kudos:{kudos.pk}"
        ).delete()[0]
        audit.record(
            RecognitionAction.KUDOS_HIDDEN,
            company_id=kudos.company_id,
            actor=_user(by),
            target=kudos,
            required_perm=Perm.RECOGNITION_MANAGE,
            sender=str(kudos.from_member),
            receiver=str(kudos.to_member),
            message=kudos.message,
            points_removed=bool(removed),
        )
    _bump(kudos.company_id)
    return kudos


# Settings and what the person saw -------------------------------------------------------------

SETTING_FIELDS = (
    "points_enabled",
    "leaderboard_for_staff",
    "leaderboard_scope",
    "task_points",
    "kudos_enabled",
    "kudos_per_day",
    "post_kudos_to_groups",
    "points_table",
)


def update_settings(company, *, by: Membership | None, **changes):
    """Change the recognition settings (owners), audited with what changed."""
    _ensure_manager(by, company)
    row = conf.get_settings(company)
    before = {}
    for field, value in changes.items():
        if field not in SETTING_FIELDS:
            raise ValueError(f"Not a recognition setting: {field}")
        if field == "points_table":
            try:
                value = rules.clean_table(value)
            except ValueError as exc:
                raise DomainError(
                    _("Points are whole numbers from 0 to %(max)s.") % {"max": rules.MAX_POINTS}
                ) from exc
        if field == "kudos_per_day" and not 1 <= int(value) <= 20:
            raise DomainError(_("Allow from 1 to 20 thanks a day."))
        if field == "leaderboard_scope" and value not in row.Scope.values:
            raise DomainError(_("Pick the whole company or their branch."))
        if getattr(row, field) != value:
            before[field] = getattr(row, field)
            setattr(row, field, value)
    if not before:
        return row
    row.save(update_fields=list(before))
    audit.record(
        RecognitionAction.SETTINGS_CHANGED,
        company_id=company.pk,
        actor=_user(by),
        target=row,
        required_perm=Perm.RECOGNITION_MANAGE,
        changed={field: {"from": old, "to": getattr(row, field)} for field, old in before.items()},
    )
    _bump(company.pk)
    return row


def mark_seen(member: Membership, *, kudos: bool = False, now: datetime | None = None) -> None:
    """The app showed the person's new levels and badges (and, with `kudos`, the thanks they
    got): the celebration doesn't come again."""
    now = now or timezone.now()
    LevelUp.objects.filter(membership=member, seen_at__isnull=True).update(seen_at=now)
    BadgeAward.objects.filter(membership=member, seen_at__isnull=True).update(seen_at=now)
    if kudos:
        Kudos.objects.filter(to_member=member, seen_at__isnull=True).update(seen_at=now)


# The nightly work ------------------------------------------------------------------------------


def award_task_points(company, day: date) -> int:
    """`task` points for shared work finished on time on `day` (the company's date): routine
    work and tasks given by someone else (never personal ones, never one given to oneself), done
    (confirmed) by its deadline, at most `rules.TASKS_A_DAY` a person for the day. Idempotent:
    the key is the task. Returns the points entries made."""
    if not conf.is_on(company):
        return 0
    settings = conf.get_settings(company)
    if not (settings.task_points and settings.points_enabled):
        return 0
    from apps.tasks.models import Task

    start, end = day_bounds(company, day)
    done = (
        Task.objects.filter(
            company=company,
            kind__in=(Task.Kind.DAILY, Task.Kind.ASSIGNED),
            status=Task.Status.DONE,
            due_at__isnull=False,
            completed_at__gte=start,
            completed_at__lt=end,
            completed_at__lte=F("due_at"),
            assignee__status=Membership.Status.APPROVED,
        )
        .exclude(kind=Task.Kind.ASSIGNED, created_by_id=F("assignee_id"))
        .order_by("assignee_id", "completed_at", "pk")
        .values_list("pk", "assignee_id", "completed_at")
    )
    rows = list(done)
    if not rows:
        return 0
    keys = {f"task:{pk}" for pk, _member, _at in rows}
    used = set(
        PointsEntry.objects.filter(company=company, key__in=keys).values_list("key", flat=True)
    )
    counted = dict(
        PointsEntry.objects.filter(
            company=company, reason=PointsEntry.Reason.TASK, at__gte=start, at__lt=end
        )
        .values("membership_id")
        .annotate(n=Count("pk"))
        .values_list("membership_id", "n")
    )
    people = {
        member.pk: member
        for member in Membership.objects.select_related("company").filter(
            pk__in={member_id for _pk, member_id, _at in rows}
        )
    }
    made = 0
    for pk, member_id, at in rows:
        key = f"task:{pk}"
        if key in used or counted.get(member_id, 0) >= rules.TASKS_A_DAY:
            continue
        if award(people[member_id], reason=PointsEntry.Reason.TASK, key=key, at=at) is not None:
            made += 1
            counted[member_id] = counted.get(member_id, 0) + 1
    return made


def award_month_top(company, month: date, *, now: datetime | None = None) -> list[BadgeAward]:
    """`top3_month` for the three with the most points in `month` (any day of it)."""
    from apps.recognition import queries

    if not conf.is_on(company):
        return []
    now = now or timezone.now()
    board = queries.leaderboard(company, period="month", day=month, branch_ids=None)
    ref = month.strftime("%Y-%m")
    made = []
    for row in board.rows[:3]:
        badge = progress.give(row.member, "top3_month", ref, now=now)
        if badge is not None:
            made.append(badge)
    return made


def sweep(company, *, now: datetime | None = None) -> int:
    """The nightly badge sweep: every approved person's levels and badges, and on Mondays the
    "on time all week" badge for the week that ended. Returns the people with something new."""
    from apps.recognition import notify

    if not conf.is_on(company):
        return 0
    now = now or timezone.now()
    today = local_today(company, now)
    last_monday = today - timedelta(days=today.weekday() + 7)
    lucky = set()
    for member in Membership.objects.select_related("company").filter(
        company=company, status=Membership.Status.APPROVED
    ):
        levels, badges = progress.check(member, now=now)
        week = (
            today.weekday() == 0
            and progress.on_time_week(member, last_monday)
            and progress.give(member, "on_time_week", now=now) is not None
        )
        if levels or badges or week:
            lucky.add(member.pk)
    if today.day <= 3:
        first = today.replace(day=1)
        previous = first - timedelta(days=1)
        lucky.update(badge.membership_id for badge in award_month_top(company, previous, now=now))
    for member_id in lucky:
        notify.schedule_notices(member_id)
    return len(lucky)
