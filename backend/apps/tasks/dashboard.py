"""Read models of the owner console's task pages (docs/PLAN-OWNER.md §6.2): the board, the
calendar, the KPI numbers, the photo wall, a task's merged timeline and routine statistics.
Everything starts from `queries.visible_tasks`, so personal tasks and branch scope (§2.6, §3.2)
apply everywhere. Personal tasks never count in KPIs."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, F, Q, QuerySet
from django.utils import timezone

from apps.audit import registry as audit_registry
from apps.audit.queries import events
from apps.members.models import Membership
from apps.reminders.models import ReminderLog
from apps.tasks import queries, rules
from apps.tasks.models import Task, TaskTemplate

BOARD_LIMIT = 60
CALENDAR_LIMIT = 600
# Finished from the assignee's point of view: waiting for a check counts as done on time.
FINISHED = (Task.Status.DONE, Task.Status.REVIEW)
SHARED = (Task.Kind.DAILY, Task.Kind.ASSIGNED)


def with_rows(tasks: QuerySet[Task]) -> QuerySet[Task]:
    """What `TaskRowSerializer` reads, loaded up front (safe to apply twice)."""
    return tasks.prefetch_related("checklist")


# Board -------------------------------------------------------------------------------------


def board(tasks: QuerySet[Task], now: datetime, company) -> list[dict]:
    """Five columns of cards (To do, In progress, Waiting, Sent back, Done) from an already
    filtered queryset; each capped at `BOARD_LIMIT`, with its full count. Done shows the last
    7 days, newest first; the others by deadline."""
    done_since = now - timedelta(days=7)
    columns = []
    for column in rules.Column:
        cards = tasks.filter(status=column.value)
        if column == rules.Column.DONE:
            cards = cards.filter(completed_at__gte=done_since).order_by("-completed_at", "-pk")
        else:
            cards = cards.order_by(F("due_at").asc(nulls_last=True), "pk")
        columns.append(
            {
                "id": column.value,
                "count": cards.count(),
                "items": list(with_rows(cards)[:BOARD_LIMIT]),
            }
        )
    return columns


# Calendar ----------------------------------------------------------------------------------


def calendar(tasks: QuerySet[Task], company, start: date, end: date, now: datetime) -> dict:
    """Due tasks per company-local day from `start` to `end` (both inclusive): counts per day
    and the tasks themselves (capped)."""
    first, _ = queries.day_bounds(company, start)
    _, last = queries.day_bounds(company, end)
    due = tasks.filter(due_at__gte=first, due_at__lt=last).exclude(status=Task.Status.CANCELLED)
    rows = list(due.values_list("due_at", "status"))
    days: dict[date, dict] = {}
    tz = ZoneInfo(company.timezone)
    for due_at, status in rows:
        day = timezone.localtime(due_at, tz).date()
        entry = days.setdefault(day, {"total": 0, "done": 0, "review": 0, "open": 0, "late": 0})
        entry["total"] += 1
        if status == Task.Status.DONE:
            entry["done"] += 1
        elif status == Task.Status.REVIEW:
            entry["review"] += 1
        else:
            entry["open"] += 1
            if due_at < now:
                entry["late"] += 1
    items = list(with_rows(due.order_by("due_at", "pk"))[:CALENDAR_LIMIT])
    return {
        "days": [{"date": day, **days[day]} for day in sorted(days)],
        "items": items,
        "truncated": len(rows) > CALENDAR_LIMIT,
    }


# KPI numbers -------------------------------------------------------------------------------


def summary(
    member: Membership, now: datetime, *, branch_ids: list[int] | None, assignee_id=None
) -> dict:
    """The Tasks KPI strip and Overview widgets: today's done/total, late now, waiting for a
    check, 7-day on-time % against the 7 days before, and a 14-day series."""
    company = member.company
    shared = queries.visible_tasks(member).filter(kind__in=SHARED)
    if branch_ids is not None:
        shared = shared.filter(branch_id__in=branch_ids)
    if assignee_id is not None:
        shared = shared.filter(assignee_id=assignee_id)
    today = queries.company_today(company, now)
    start, end = queries.day_bounds(company, today)
    todays = shared.filter(due_at__gte=start, due_at__lt=end).exclude(status=Task.Status.CANCELLED)
    counts = todays.aggregate(
        total=Count("pk"),
        done=Count("pk", filter=Q(status__in=FINISHED)),
    )
    late_now = shared.filter(status__in=Task.OPEN_STATUSES, due_at__lt=now).count()
    review = shared.filter(status=Task.Status.REVIEW).count()
    open_count = shared.filter(status__in=Task.OPEN_STATUSES).count()
    series = daily_series(shared, company, today - timedelta(days=13), today, now)
    week = _window(series[-7:])
    before = _window(series[:7])
    return {
        "today": today,
        "done_today": counts["done"],
        "total_today": counts["total"],
        "late_now": late_now,
        "review": review,
        "open": open_count,
        "on_time_percent": week["on_time_percent"],
        "on_time_previous": before["on_time_percent"],
        "done_7d": week["done"],
        "done_prev_7d": before["done"],
        "series": series,
    }


def daily_series(
    tasks: QuerySet[Task], company, first: date, last: date, now: datetime
) -> list[dict]:
    """Per day: tasks due that day whose deadline passed, on time, late, missed, on-time %."""
    tz = ZoneInfo(company.timezone)
    start, _ = queries.day_bounds(company, first)
    _, end = queries.day_bounds(company, last)
    rows = (
        tasks.filter(due_at__gte=start, due_at__lt=min(end, now))
        .exclude(status=Task.Status.CANCELLED)
        .values_list("due_at", "status", "completed_at")
    )
    days: dict[date, dict] = defaultdict(lambda: {"on_time": 0, "late": 0, "missed": 0})
    for due_at, status, completed_at in rows:
        entry = days[timezone.localtime(due_at, tz).date()]
        if status in FINISHED and completed_at is not None:
            entry["on_time" if completed_at <= due_at else "late"] += 1
        else:
            entry["missed"] += 1
    out = []
    day = first
    while day <= last:
        entry = days.get(day, {"on_time": 0, "late": 0, "missed": 0})
        total = entry["on_time"] + entry["late"] + entry["missed"]
        out.append(
            {
                "date": day,
                **entry,
                "total": total,
                "done": entry["on_time"] + entry["late"],
                "on_time_percent": round(100 * entry["on_time"] / total, 1) if total else None,
            }
        )
        day += timedelta(days=1)
    return out


def _window(days: list[dict]) -> dict:
    on_time = sum(day["on_time"] for day in days)
    total = sum(day["total"] for day in days)
    return {
        "on_time_percent": round(100 * on_time / total, 1) if total else None,
        "done": sum(day["done"] for day in days),
    }


# Photo wall --------------------------------------------------------------------------------


def proofs(
    member: Membership, day: date, *, branch_ids: list[int] | None, routine_id=None
) -> list[Task]:
    """Tasks finished on `day` with a proof photo, newest first."""
    start, end = queries.day_bounds(member.company, day)
    tasks = (
        queries.visible_tasks(member)
        .exclude(proof_photo="")
        .filter(completed_at__gte=start, completed_at__lt=end)
    )
    if branch_ids is not None:
        tasks = tasks.filter(branch_id__in=branch_ids)
    if routine_id is not None:
        tasks = tasks.filter(template_id=routine_id)
    return list(with_rows(tasks.order_by("-completed_at", "-pk"))[:300])


# Timeline ----------------------------------------------------------------------------------


def timeline(task: Task, viewer: Membership) -> list[dict]:
    """Comments, reminders and audited changes of one task, oldest first:
    `{at, kind, title, actor, text, meta}` (kind: created, comment, heads_up, reminder,
    escalation, blocked, audit)."""
    entries: list[dict] = [
        {
            "at": task.created_at,
            "kind": "created",
            "actor": task.created_by,
            "action": "created",
            "text": "",
            "meta": {},
        }
    ]
    for comment in task.comments.select_related("author__user", "author__position"):
        entries.append(
            {
                "at": comment.created_at,
                "kind": "comment",
                "actor": comment.author,
                "action": "comment",
                "text": comment.text,
                "meta": {},
            }
        )
    for log in task.reminder_log.select_related("recipient__user", "recipient__position"):
        entries.append(
            {
                "at": log.sent_at,
                "kind": log.kind,
                "actor": log.recipient,
                "action": log.kind,
                "text": log.error,
                "meta": {"step": log.step, "delivered": log.delivered},
            }
        )
    if task.completed_at:
        entries.append(
            {
                "at": task.completed_at,
                "kind": "completed",
                "actor": task.assignee,
                "action": "completed",
                "text": task.proof_text,
                "meta": {},
            }
        )
    actors = {}
    for row in events(viewer, target_type="task", target_id=task.pk):
        user_id = row.actor_id
        if user_id is not None and user_id not in actors:
            actors[user_id] = (
                Membership.objects.select_related("user", "position")
                .filter(company_id=task.company_id, user_id=user_id)
                .first()
            )
        entries.append(
            {
                "at": row.created_at,
                "kind": "audit",
                "actor": actors.get(user_id),
                "action": row.action,
                "text": audit_registry.label(row.action),
                "meta": {
                    key: value
                    for key, value in (row.details or {}).items()
                    if key in ("changes", "reason", "assignee")
                },
            }
        )
    entries.sort(key=lambda entry: entry["at"])
    return entries


# Routines ----------------------------------------------------------------------------------


def routine_stats(
    templates: list[TaskTemplate], company, now: datetime, *, days: int = 30
) -> dict[int, dict]:
    """Per routine: tasks made in the last `days` days whose deadline passed, how many finished
    on time, the completion % and a 14-day sparkline of daily completion."""
    if not templates:
        return {}
    tz = ZoneInfo(company.timezone)
    today = queries.company_today(company, now)
    start, _ = queries.day_bounds(company, today - timedelta(days=days - 1))
    rows = (
        Task.objects.filter(
            template_id__in=[t.pk for t in templates], due_at__gte=start, due_at__lt=now
        )
        .exclude(status=Task.Status.CANCELLED)
        .values_list("template_id", "due_at", "status", "completed_at")
    )
    per: dict[int, dict] = {
        t.pk: {"made": 0, "on_time": 0, "done": 0, "days": defaultdict(lambda: [0, 0])}
        for t in templates
    }
    for template_id, due_at, status, completed_at in rows:
        entry = per[template_id]
        entry["made"] += 1
        finished = status in FINISHED and completed_at is not None
        if finished:
            entry["done"] += 1
            if completed_at <= due_at:
                entry["on_time"] += 1
        day = timezone.localtime(due_at, tz).date()
        entry["days"][day][0] += 1
        entry["days"][day][1] += int(finished)
    out = {}
    for template_id, entry in per.items():
        spark = []
        for offset in range(13, -1, -1):
            made, done = entry["days"].get(today - timedelta(days=offset), (0, 0))
            spark.append(round(100 * done / made) if made else None)
        out[template_id] = {
            "made_30d": entry["made"],
            "done_30d": entry["done"],
            "on_time_30d": entry["on_time"],
            "completion_30d": round(100 * entry["done"] / entry["made"], 1)
            if entry["made"]
            else None,
            "spark": spark,
        }
    return out


def routine_compliance(template: TaskTemplate, start: date, end: date, now: datetime) -> dict:
    """One routine over a range: per day and per person, made / on time / late / missed."""
    company = template.company
    tz = ZoneInfo(company.timezone)
    first, _ = queries.day_bounds(company, start)
    _, last = queries.day_bounds(company, end)
    rows = (
        Task.objects.filter(template=template, due_at__gte=first, due_at__lt=min(last, now))
        .exclude(status=Task.Status.CANCELLED)
        .select_related("assignee__user", "assignee__position")
    )
    days: dict[date, dict] = defaultdict(lambda: {"made": 0, "on_time": 0, "late": 0, "missed": 0})
    people: dict[int, dict] = {}
    for task in rows:
        outcome = _outcome(task)
        day = days[timezone.localtime(task.due_at, tz).date()]
        day["made"] += 1
        day[outcome] += 1
        row = people.setdefault(
            task.assignee_id,
            {"member": task.assignee, "made": 0, "on_time": 0, "late": 0, "missed": 0},
        )
        row["made"] += 1
        row[outcome] += 1
    series = []
    day = start
    while day <= end:
        entry = days.get(day, {"made": 0, "on_time": 0, "late": 0, "missed": 0})
        series.append(
            {"date": day, **entry, "on_time_percent": _percent(entry["on_time"], entry["made"])}
        )
        day += timedelta(days=1)
    totals = {
        key: sum(entry[key] for entry in series) for key in ("made", "on_time", "late", "missed")
    }
    totals["on_time_percent"] = _percent(totals["on_time"], totals["made"])
    rows_out = sorted(
        (
            {**row, "on_time_percent": _percent(row["on_time"], row["made"])}
            for row in people.values()
        ),
        key=lambda row: (
            row["on_time_percent"] is None,
            -(row["on_time_percent"] or 0),
            str(row["member"]),
        ),
    )
    return {"totals": totals, "series": series, "people": rows_out}


def _outcome(task: Task) -> str:
    if task.status in FINISHED and task.completed_at is not None:
        return "on_time" if task.completed_at <= task.due_at else "late"
    return "missed"


def _percent(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def reminder_counts(task_ids: list[int]) -> dict[int, int]:
    return dict(
        ReminderLog.objects.filter(task_id__in=task_ids, kind=ReminderLog.Kind.REMINDER)
        .values("task_id")
        .annotate(n=Count("pk"))
        .values_list("task_id", "n")
    )
