import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from celery import shared_task
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone, translation

from apps.companies.models import Company
from apps.groups import bot_messages, reports
from apps.groups.models import GroupEvent, GroupReport, TelegramGroup
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership, Position
from apps.notifications import telegram
from apps.notifications.telegram import BotName, serialize_markup
from apps.tasks.models import Task
from apps.tasks.queries import TASK_RELATIONS

logger = logging.getLogger(__name__)

# A daily report only goes out within this long after its time, not hours late.
REPORT_WINDOW = timedelta(hours=2)
# Telegram lets a bot post about 20 messages a minute to one group.
POST_GAP = timedelta(seconds=3)


@shared_task(
    bind=True,
    autoretry_for=(TelegramNetworkError, TelegramServerError),
    retry_backoff=True,
    max_retries=5,
)
def post_to_group(self, group_id, text, reply_markup=None, photo=None):
    group = TelegramGroup.objects.filter(pk=group_id, is_active=True).first()
    if group is None:
        return
    try:
        telegram.send_message(BotName.EMPLOYEE, group.chat_id, text, reply_markup, photo)
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc
    except TelegramMigrateToChat as exc:
        TelegramGroup.objects.move_chat(group.chat_id, exc.migrate_to_chat_id)
        raise self.retry(countdown=1) from exc
    except TelegramForbiddenError:
        logger.info("Removed from group %s; switching it off", group.chat_id)
        TelegramGroup.objects.filter(pk=group.pk).update(is_active=False)
    except TelegramBadRequest as exc:  # e.g. the bot was muted there; retrying won't help
        logger.warning("Post to group %s refused: %s", group.chat_id, exc)


def queue_post(group_id: int, message: BotMessage, photo: str | None = None) -> None:
    """Queue a post, spaced after the group's earlier ones so a burst doesn't hit the limit."""
    text, markup = message
    now = timezone.now()
    with transaction.atomic():
        group = (
            TelegramGroup.objects.select_for_update()
            .filter(pk=group_id)
            .only("next_post_at")
            .first()
        )
        if group is None:
            return
        slot = max(now, group.next_post_at or now)
        TelegramGroup.objects.filter(pk=group_id).update(next_post_at=slot + POST_GAP)
    post_to_group.apply_async(
        (group_id, text, serialize_markup(markup), photo),
        countdown=(slot - now).total_seconds(),
    )


def _post(
    company: Company, about: Membership, event: GroupEvent, build, photo: str | None = None
) -> None:
    """Post news about a member to each of the company's groups that wants it."""
    covers = Q(positions=None)
    if about.position_id:
        covers |= Q(positions=about.position_id)
    groups = list(
        TelegramGroup.objects.filter(covers, company=company, is_active=True)
        .filter(events__contains=[event])
        .values_list("pk", flat=True)
        .distinct()
    )
    if not groups:
        return
    with translation.override(company.default_language):
        message = build()
    for group_id in groups:
        queue_post(group_id, message, photo)


@shared_task
def announce_task_done(task_id: int) -> None:
    task = Task.objects.select_related(*TASK_RELATIONS).filter(pk=task_id).first()
    if task is None or task.completed_at is None:
        return
    event = {Task.Kind.DAILY: GroupEvent.DAILY_DONE, Task.Kind.ASSIGNED: GroupEvent.TASKS_DONE}
    if task.kind not in event:
        return  # personal tasks stay personal
    photo = task.proof_photo.name or None
    _post(
        task.company, task.assignee, event[task.kind], lambda: bot_messages.task_done(task), photo
    )


@shared_task
def announce_late(task_id: int) -> None:
    task = Task.objects.select_related(*TASK_RELATIONS).filter(pk=task_id).first()
    if task is None or not task.is_open:
        return
    now = timezone.now()
    _post(task.company, task.assignee, GroupEvent.LATE, lambda: bot_messages.late(task, now))


@shared_task
def announce_member(membership_id: int) -> None:
    member = (
        Membership.objects.select_related("company", "user", "position")
        .filter(pk=membership_id)
        .first()
    )
    if member is None or member.status != Membership.Status.APPROVED:
        return
    _post(member.company, member, GroupEvent.MEMBERS, lambda: bot_messages.member_joined(member))


@shared_task
def send_daily_reports() -> None:
    post_daily_reports(timezone.now())


def post_daily_reports(now: datetime) -> int:
    """Queue the morning plans and evening summaries that are due; return how many."""
    posted = 0
    for company in Company.objects.filter(is_active=True):
        local = timezone.localtime(now, ZoneInfo(company.timezone))
        if _in_window(local, company.morning_report_at):
            posted += _post_report(company, GroupEvent.MORNING, local)
        if _in_window(local, company.evening_report_at):
            posted += _post_report(company, GroupEvent.EVENING, local)
    return posted


def _in_window(local: datetime, at: time) -> bool:
    start = local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return start <= local < start + REPORT_WINDOW


def _post_report(company: Company, kind: GroupEvent, local: datetime) -> int:
    day = local.date()
    already = GroupReport.objects.filter(kind=kind, day=day).values("group")
    groups = (
        TelegramGroup.objects.filter(company=company, is_active=True, events__contains=[kind])
        .exclude(pk__in=already)
        .prefetch_related(Prefetch("positions", queryset=Position.objects.only("pk")))
    )
    built: dict[frozenset[int], BotMessage | None] = {}  # one report per position filter
    posted = 0
    for group in groups:
        positions = frozenset(position.pk for position in group.positions.all())
        if positions not in built:
            with translation.override(company.default_language):
                built[positions] = _report(company, kind, local, positions)
        if built[positions] is None:
            continue  # nothing to say, e.g. on a day off
        # The unique report row is the claim: a second run that gets here skips it.
        _, claimed = GroupReport.objects.get_or_create(group=group, kind=kind, day=day)
        if claimed:
            queue_post(group.pk, built[positions])
            posted += 1
    return posted


def _report(
    company: Company, kind: GroupEvent, local: datetime, positions: frozenset[int]
) -> BotMessage | None:
    day = local.date()
    if kind == GroupEvent.MORNING:
        rows = reports.morning_plan(company, day, positions)
        return bot_messages.morning(company, day, rows) if rows else None
    # Work due later tonight isn't late yet, so the summary leaves it out.
    stats = reports.day_stats(company, day, until=local, positions=positions)
    return bot_messages.evening(day, stats) if stats.total else None
