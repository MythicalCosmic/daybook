from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.tasks.models import Task

# Everything a task card or serializer touches, so rendering never queries.
TASK_RELATIONS = (
    "company",
    "template",
    "assignee__user",
    "assignee__position",
    "created_by__user",
    "created_by__position",
)


def visible_tasks(member: Membership) -> QuerySet[Task]:
    """Tasks the member may see: their own, the ones they handed out, or all with tasks.view_all.

    Anyone allowed to confirm also sees the work waiting for a check.
    """
    tasks = Task.objects.for_company(member.company_id).select_related(*TASK_RELATIONS)
    if member.has_perm(Perm.TASKS_VIEW_ALL):
        return tasks
    visible = Q(assignee=member) | Q(created_by=member)
    if member.has_perm(Perm.TASKS_CONFIRM):
        visible |= Q(status=Task.Status.REVIEW)
    return tasks.filter(visible)


def todays_tasks(member: Membership, now: datetime) -> QuerySet[Task]:
    """What the member should work on: open tasks due by the end of today, or with no deadline."""
    tz = ZoneInfo(member.company.timezone)
    tomorrow = timezone.localtime(now, tz).date() + timedelta(days=1)
    end_of_today = datetime.combine(tomorrow, time.min, tzinfo=tz)
    return (
        Task.objects.for_company(member.company_id)
        .select_related(*TASK_RELATIONS)
        .filter(assignee=member, status__in=Task.OPEN_STATUSES)
        .filter(Q(due_at__lt=end_of_today) | Q(due_at__isnull=True))
    )


def awaiting_review_by(member: Membership) -> QuerySet[Task]:
    tasks = visible_tasks(member).filter(status=Task.Status.REVIEW).exclude(assignee=member)
    if member.has_perm(Perm.TASKS_CONFIRM):
        return tasks
    return tasks.filter(kind=Task.Kind.ASSIGNED, created_by=member)


def reviewers(task: Task) -> list[Membership]:
    """Who gets asked to confirm finished work."""
    creator = task.created_by
    if (
        task.kind == Task.Kind.ASSIGNED
        and creator is not None
        and creator.status == Membership.Status.APPROVED
    ):
        return [creator]
    return list(
        members_with_perm(task.company, Perm.TASKS_CONFIRM)
        .exclude(pk=task.assignee_id)
        .select_related("user", "role", "company")
    )
