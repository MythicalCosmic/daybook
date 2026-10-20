"""What tasks hand the console's registries (docs/PLAN-OWNER.md §2.5, §13): palette search,
the "Needs you" reviews, live badges, the activity stream, branch cards, briefings, portfolio
facts, calendar dates, "copy setup" parts and the Excel/CSV exporter. Each provider applies the
caller's branch scope; personal tasks never count in numbers."""

from datetime import date, datetime, timedelta

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.console.contracts import Person
from apps.console.registry import CalendarItem, QueueAction, QueueItem, SearchHit, StreamItem
from apps.members.models import Membership, Position
from apps.members.scope import branch_ids
from apps.reminders.models import ReminderPolicy
from apps.tasks import dashboard, queries
from apps.tasks.models import Task, TaskTemplate

SHARED = (Task.Kind.DAILY, Task.Kind.ASSIGNED)


def _person(member: Membership | None) -> Person | None:
    return {"id": member.pk, "name": str(member)} if member is not None else None


def task_url(task_id: int, view: str = "") -> str:
    return f"tasks?{f'view={view}&' if view else ''}task={task_id}"


# Search ------------------------------------------------------------------------------------


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    q = q.strip()
    if len(q) < 2:
        return []
    tasks = (
        queries.visible_tasks(member)
        .filter(Q(title__icontains=q) | Q(description__icontains=q))
        .exclude(status=Task.Status.CANCELLED)
        .order_by("-created_at")[:limit]
    )
    return [
        SearchHit(
            type="tasks.task",
            id=task.pk,
            title=task.title,
            subtitle=" · ".join(filter(None, [str(task.assignee), task.get_status_display()])),
            url=task_url(task.pk),
        )
        for task in tasks
    ]


# Needs you: reviews ------------------------------------------------------------------------


def review_count(member: Membership) -> int:
    return queries.awaiting_review_by(member).count()


def review_items(member: Membership, limit: int) -> list[QueueItem]:
    tasks = queries.awaiting_review_by(member).order_by("completed_at", "pk")[:limit]
    return [
        QueueItem(
            kind="tasks.review",
            id=task.pk,
            title=task.title,
            subtitle=" · ".join(
                filter(None, [str(task.assignee), task.branch.name if task.branch_id else ""])
            ),
            created_at=task.completed_at,
            url=f"tasks/reviews?task={task.pk}",
            actions=(
                QueueAction("confirm", _("Accept"), "primary", "POST", f"tasks/{task.pk}/confirm/"),
                QueueAction(
                    "return",
                    _("Send back"),
                    "danger",
                    "POST",
                    f"tasks/{task.pk}/return/",
                    needs_reason=True,
                ),
            ),
        )
        for task in tasks
    ]


# Activity stream ---------------------------------------------------------------------------


def stream(member: Membership, since: datetime | None, limit: int) -> list[StreamItem]:
    tasks = (
        queries.visible_tasks(member)
        .filter(
            kind__in=SHARED,
            completed_at__isnull=False,
            status__in=(Task.Status.DONE, Task.Status.REVIEW),
        )
        .order_by("-completed_at")
    )
    if since is not None:
        tasks = tasks.filter(completed_at__gt=since)
    items = []
    for task in tasks[:limit]:
        thumb = task.proof_thumb or task.proof_photo
        items.append(
            StreamItem(
                at=task.completed_at,
                kind="tasks.done",
                actor=_person(task.assignee),
                title=_("Finished “%(title)s”") % {"title": task.title},
                url=task_url(task.pk),
                photo_url=thumb.url if thumb else None,
            )
        )
    return items


# Branch cards, briefings, portfolio --------------------------------------------------------


def branch_facts(company, day: date, now: datetime, scope: list[int]) -> dict[int, dict]:
    """Per branch: shared tasks due `day`, how many are finished, how many are late now."""
    start, end = queries.day_bounds(company, day)
    rows = (
        Task.objects.for_company(company)
        .filter(kind__in=SHARED, due_at__gte=start, due_at__lt=end, branch__isnull=False)
        .exclude(status=Task.Status.CANCELLED)
    )
    if scope is not None:
        rows = rows.filter(branch_id__in=scope)
    counts = rows.values("branch").annotate(
        total=Count("pk"),
        done=Count("pk", filter=Q(status__in=dashboard.FINISHED)),
        late=Count("pk", filter=Q(status__in=Task.OPEN_STATUSES, due_at__lt=now)),
    )
    return {
        row["branch"]: {"done": row["done"], "total": row["total"], "late": row["late"]}
        for row in counts
    }


def brief(company, day: date, now: datetime, scope: list[int] | None) -> dict | None:
    """The tasks section of briefings and `/today`: today's progress, late work, checks waiting,
    the 7-day on-time rate and the five most overdue tasks. None on a day with no shared work."""
    tasks = Task.objects.for_company(company).filter(kind__in=SHARED)
    if scope is not None:
        tasks = tasks.filter(branch_id__in=scope)
    start, end = queries.day_bounds(company, day)
    today = tasks.filter(due_at__gte=start, due_at__lt=end).exclude(status=Task.Status.CANCELLED)
    totals = today.aggregate(
        total=Count("pk"), done=Count("pk", filter=Q(status__in=dashboard.FINISHED))
    )
    late = tasks.filter(status__in=Task.OPEN_STATUSES, due_at__lt=now)
    review = tasks.filter(status=Task.Status.REVIEW).count()
    if not totals["total"] and not late.exists() and not review:
        return None
    week = dashboard.daily_series(tasks, company, day - timedelta(days=6), day, now)
    on_time = sum(row["on_time"] for row in week)
    counted = sum(row["total"] for row in week)
    worst = late.select_related("assignee__user", "branch").order_by("due_at")[:5]
    return {
        "done": totals["done"],
        "total": totals["total"],
        "late": late.count(),
        "review": review,
        "on_time_7d": f"{100 * on_time / counted:.1f}" if counted else None,
        "late_tasks": [
            {
                "id": task.pk,
                "title": task.title,
                "assignee": _person(task.assignee),
                "branch": task.branch.name if task.branch_id else None,
                "due_at": task.due_at.isoformat(),
            }
            for task in worst
        ],
    }


def company_facts(company, period, member: Membership) -> dict:
    """Portfolio card (§13.2): today's shared tasks done and total, late now, in the caller's
    branch scope."""
    now = timezone.now()
    scope = branch_ids(member)
    facts = branch_facts(company, queries.company_today(company, now), now, scope)
    no_branch = {"done": 0, "total": 0, "late": 0}
    if scope is None:  # company-wide tasks (no branch) belong to the card too
        start, end = queries.day_bounds(company, queries.company_today(company, now))
        rows = (
            Task.objects.for_company(company)
            .filter(kind__in=SHARED, due_at__gte=start, due_at__lt=end, branch__isnull=True)
            .exclude(status=Task.Status.CANCELLED)
        )
        no_branch = rows.aggregate(
            total=Count("pk"),
            done=Count("pk", filter=Q(status__in=dashboard.FINISHED)),
            late=Count("pk", filter=Q(status__in=Task.OPEN_STATUSES, due_at__lt=now)),
        )
    return {
        key: sum(values[key] for values in facts.values()) + no_branch[key]
        for key in ("done", "total", "late")
    }


# Company calendar --------------------------------------------------------------------------


def calendar_events(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    """One all-day entry per day with shared tasks due: "12 tasks due" (§13.5 `tasks.due`)."""
    first, _ = queries.day_bounds(company, start)
    _, last = queries.day_bounds(company, end)
    tasks = (
        queries.visible_tasks(member)
        .filter(kind__in=SHARED, due_at__gte=first, due_at__lt=last)
        .exclude(status=Task.Status.CANCELLED)
    )
    data = dashboard.calendar(tasks, company, start, end, timezone.now())
    return [
        CalendarItem(
            id=f"tasks.due:{day['date'].isoformat()}",
            kind="tasks.due",
            title=_("%(count)d tasks due") % {"count": day["total"]}
            if day["total"] != 1
            else _("1 task due"),
            start=day["date"],
            end=None,
            all_day=True,
            color="danger" if day["late"] else "primary",
            url=f"tasks?view=calendar&month={day['date'].isoformat()[:7]}",
        )
        for day in data["days"]
    ]


# Copy setup (§13.2) ------------------------------------------------------------------------


def copy_routines(source, target, by: Membership) -> int:
    return _copy_templates(source, target, by, onboarding=False)


def copy_onboarding(source, target, by: Membership) -> int:
    return _copy_templates(source, target, by, onboarding=True)


def _copy_templates(source, target, by: Membership, *, onboarding: bool) -> int:
    """Routines (or onboarding templates) of `source` as new ones of `target`. People are never
    copied: positions, branches and reminder policies are matched by name; a routine left with
    nobody to do it is copied paused, to finish in the editor."""
    positions = {p.name.lower(): p for p in Position.objects.filter(company=target)}
    branches = {b.name.lower(): b for b in target.branches.all()}
    policies = {p.name.lower(): p for p in ReminderPolicy.objects.filter(company=target)}
    taken = set(
        TaskTemplate.objects.filter(company=target, personal=False).values_list("title", flat=True)
    )
    created = 0
    templates = (
        TaskTemplate.objects.filter(company=source, personal=False, onboarding=onboarding)
        .select_related("branch", "reminder_policy")
        .prefetch_related("positions")
    )
    for template in templates:
        if template.title in taken:
            continue
        matched = [
            positions[p.name.lower()]
            for p in template.positions.all()
            if p.name.lower() in positions
        ]
        copy = TaskTemplate.objects.create(
            company=target,
            title=template.title,
            description=template.description,
            weekdays=template.weekdays,
            due_time=template.due_time,
            proof=template.proof,
            needs_confirmation=template.needs_confirmation,
            is_active=template.is_active and (bool(matched) or onboarding),
            created_by=by,
            reminder_policy=policies.get(template.reminder_policy.name.lower())
            if template.reminder_policy
            else None,
            branch=branches.get(template.branch.name.lower()) if template.branch else None,
            checklist=template.checklist,
            onboarding=template.onboarding,
            due_after_days=template.due_after_days,
        )
        copy.positions.set(matched)
        audit.record(
            AuditLog.Action.TEMPLATE_CREATED,
            company_id=target.pk,
            actor=by.user,
            target=copy,
            copied_from=source.name,
        )
        taken.add(template.title)
        created += 1
    return created


# Exporter ----------------------------------------------------------------------------------


class _Params:
    """A plain dict read like a QueryDict, for the exporter's saved filters."""

    def __init__(self, params: dict):
        self.params = params or {}

    def get(self, key, default=None):
        value = self.params.get(key, default)
        return value[0] if isinstance(value, list) and value else value

    def getlist(self, key):
        value = self.params.get(key)
        if value in (None, ""):
            return []
        return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def export_rows(member: Membership, params: dict):
    """The task list as the table shows it, with its filters (the request's query keys)."""
    from apps.tasks.owner_api import order, parse_filters

    filters = parse_filters(_Params(params))
    tasks = queries.filtered(member.company, viewer=member, filters=filters, branch_ids=None)
    tasks = order(dashboard.with_rows(tasks), _Params(params).get("ordering"))
    for task in tasks.iterator(chunk_size=500):
        items = list(task.checklist.all())
        yield {
            "id": task.pk,
            "title": task.title,
            "status": task.get_status_display(),
            "kind": task.get_kind_display(),
            "priority": task.get_priority_display(),
            "assignee": str(task.assignee),
            "position": task.assignee.position.name if task.assignee.position_id else "",
            "branch": task.branch.name if task.branch_id else "",
            "routine": task.template.title
            if task.template_id and not task.template.personal
            else "",
            "due_at": task.due_at,
            "completed_at": task.completed_at,
            "created_by": str(task.created_by) if task.created_by_id else "",
            "checklist": f"{sum(i.is_done for i in items)}/{len(items)}" if items else "",
            "has_proof": bool(task.proof_photo or task.proof_text),
            "reward": task.reward,
        }
