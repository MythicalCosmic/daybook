"""The numbers behind the morning plan and the evening summary.

`positions` narrows a report to people in those positions; empty means everyone.
"""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Min

from apps.companies.models import Company
from apps.members.models import Membership
from apps.tasks.bot_messages import display_title
from apps.tasks.models import Task

FINISHED = (Task.Status.DONE, Task.Status.REVIEW)
# Personal tasks are nobody else's business.
SHARED_KINDS = (Task.Kind.DAILY, Task.Kind.ASSIGNED)


@dataclass
class PlanRow:
    name: str
    count: int
    first_due: datetime


@dataclass
class DayStats:
    on_time: int = 0
    late: int = 0
    not_done: list[tuple[str, str]] = field(default_factory=list)  # (person, task)

    @property
    def total(self) -> int:
        return self.on_time + self.late + len(self.not_done)


def day_bounds(company: Company, day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(company.timezone))
    return start, start + timedelta(days=1)


def _due_on(company: Company, day: date, positions: Collection[int]):
    start, end = day_bounds(company, day)
    tasks = (
        Task.objects.for_company(company)
        .filter(
            kind__in=SHARED_KINDS,
            due_at__gte=start,
            due_at__lt=end,
            assignee__status=Membership.Status.APPROVED,
        )
        .exclude(status=Task.Status.CANCELLED)
    )
    return tasks.filter(assignee__position__in=positions) if positions else tasks


def morning_plan(company: Company, day: date, positions: Collection[int] = ()) -> list[PlanRow]:
    rows = list(
        _due_on(company, day, positions)
        .values("assignee")
        .annotate(count=Count("id"), first_due=Min("due_at"))
        .order_by("first_due")
    )
    people = {
        member.pk: str(member)
        for member in Membership.objects.filter(
            pk__in=[row["assignee"] for row in rows]
        ).select_related("user")
    }
    return [PlanRow(people[row["assignee"]], row["count"], row["first_due"]) for row in rows]


def day_stats(
    company: Company, day: date, until: datetime | None = None, positions: Collection[int] = ()
) -> DayStats:
    """How the day's work went; with `until`, only work that was due by then counts."""
    stats = DayStats()
    tasks = (
        _due_on(company, day, positions)
        .select_related("assignee__user", "project", "card")
        .order_by("due_at")
    )
    if until is not None:
        tasks = tasks.filter(due_at__lte=until)
    for task in tasks:
        if task.status in FINISHED:
            if task.completed_at and task.completed_at <= task.due_at:
                stats.on_time += 1
            else:
                stats.late += 1
        else:
            stats.not_done.append((str(task.assignee), display_title(task)))
    return stats
