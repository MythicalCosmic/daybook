"""Deadline watcher: late work reaches whoever gave it, once (v0.2 AI contract §3).

Every 30 minutes outside the quiet hours: a task given to someone that is late by
`escalate_after_hours` goes to its giver (or to the assignee's head when the giver is gone),
with Open and "+1 hour". Once per task: the watcher claims the reminders' own escalation mark
(`Task.escalated_at`), so a task the reminder policy already escalated is left alone, and one
the watcher escalated is never escalated again by the reminders.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.ai import bot_messages, events
from apps.ai.agents import registry
from apps.ai.agents.registry import Agent, EventTemplate, Field
from apps.members.departments import manager_of
from apps.members.models import Membership
from apps.notifications import tasks as telegram_jobs
from apps.notifications.telegram import BotName, serialize_markup
from apps.tasks.models import Task

KEY = "deadline_watcher"
EVERY = timedelta(minutes=30)
BATCH = 200


def in_quiet_hours(local: datetime, config: dict) -> bool:
    start, end = time.fromisoformat(config["quiet_from"]), time.fromisoformat(config["quiet_to"])
    now = local.time()
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end  # 21:00-08:00 spans midnight


def next_run(config: dict, now: datetime, company) -> datetime:
    """Half an hour on, or the end of the quiet hours."""
    zone = ZoneInfo(company.timezone)
    later = timezone.localtime(now + EVERY, zone)
    if not in_quiet_hours(later, config):
        return now + EVERY
    end = time.fromisoformat(config["quiet_to"])
    day = later.date() if later.time() < end else later.date() + timedelta(days=1)
    return datetime.combine(day, end, tzinfo=zone)


def _schedule(config: dict) -> str:
    return _("Every 30 minutes, %(start)s–%(end)s") % {
        "start": config["quiet_to"],
        "end": config["quiet_from"],
    }


def run(company, state, now: datetime) -> int:
    config = registry.config_of(AGENT, state)
    zone = ZoneInfo(company.timezone)
    if in_quiet_hours(timezone.localtime(now, zone), config):
        return 0
    late_before = now - timedelta(hours=int(config["escalate_after_hours"]))
    late = (
        watched(company)
        .filter(due_at__lt=late_before)
        .select_related("assignee__user", "created_by__user", "company")
        .order_by("due_at")[:BATCH]
    )
    told = 0
    for task in late:
        recipient = _who_hears(task)
        if recipient is None or recipient.user.telegram_id is None:
            continue
        if not _claim(task, now):
            continue  # the reminders (or another run) escalated it meanwhile
        _tell(task, recipient, now)
        told += 1
    return told


def watched(company):
    """The work it looks after: tasks given to someone still working here, open, not blocked,
    and not escalated yet."""
    return Task.objects.for_company(company).filter(
        kind=Task.Kind.ASSIGNED,
        status__in=Task.OPEN_STATUSES,
        escalated_at__isnull=True,
        blocked_at__isnull=True,
        assignee__status=Membership.Status.APPROVED,
    )


def upcoming(company, state, now: datetime) -> list[tuple[None, str]]:
    due = watched(company).filter(due_at__gte=now, due_at__lt=now + timedelta(hours=24)).count()
    return [(None, _("Tasks due in the next 24 hours: %(count)s") % {"count": due})]


def _who_hears(task: Task) -> Membership | None:
    giver = task.created_by
    if giver is not None and giver.pk != task.assignee_id and giver.status == "approved":
        return giver
    head = manager_of(task.assignee)
    return head if head is not None and head.status == "approved" else None


def _claim(task: Task, now: datetime) -> bool:
    with transaction.atomic():
        return bool(
            Task.objects.filter(pk=task.pk, escalated_at__isnull=True).update(escalated_at=now)
        )


def _tell(task: Task, recipient: Membership, now: datetime) -> None:
    hours = max(1, int((now - task.due_at).total_seconds() // 3600))
    with translation.override(recipient.user.language):
        text, markup = bot_messages.late_task(task, recipient, now)
    transaction.on_commit(
        lambda: telegram_jobs.send_telegram_message.delay(
            BotName.EMPLOYEE, recipient.user.telegram_id, text, serialize_markup(markup)
        )
    )
    events.log(
        task.company,
        KEY,
        "escalated",
        params={
            "task": task.title,
            "assignee": str(task.assignee),
            "to": str(recipient),
            "hours": hours,
        },
        actor=None,
        subject=("task", task.pk),
        branch_id=task.branch_id,
        dedupe_key=f"late:{task.pk}",
    )


AGENT = registry.register(
    Agent(
        key=KEY,
        order=20,
        name=gettext_lazy("Deadline watcher"),
        description=gettext_lazy(
            "Tells whoever gave a task when it is late, once, with a button to open it or "
            "give an hour more. Never repeats what the reminders already said."
        ),
        icon="alarm-clock",
        needs_claude=False,
        default_enabled=True,
        fields=(
            Field(
                "escalate_after_hours",
                "int",
                gettext_lazy("Late by"),
                2,
                help=gettext_lazy("How late a task is before its giver hears."),
                min=1,
                max=48,
                unit=gettext_lazy("hours"),
            ),
            Field("quiet_from", "time", gettext_lazy("Quiet from"), "21:00"),
            Field("quiet_to", "time", gettext_lazy("Quiet until"), "08:00"),
        ),
        schedule=_schedule,
        run=run,
        next_run=next_run,
        upcoming=upcoming,
        events={
            "escalated": EventTemplate(
                gettext_lazy("Told %(to)s that «%(task)s» is late (%(assignee)s)"),
                level="warning",
            ),
        },
    )
)
