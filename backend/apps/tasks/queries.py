from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.members.scope import branch_ids
from apps.tasks import visibility
from apps.tasks.models import Task

# Everything a task card or serializer touches, so rendering never queries.
TASK_RELATIONS = (
    "company",
    "template",
    "assignee__user",
    "assignee__position",
    "created_by__user",
    "created_by__position",
    "confirmed_by__user",
    "escalate_to__user",
    "reminder_policy",
    "template__reminder_policy",
)


def visible_tasks(member: Membership) -> QuerySet[Task]:
    """Tasks the member may see (docs/PLAN-OWNER.md §3.2).

    - Someone else's personal tasks only for an owner, and only while the company's
      `owner_sees_personal_tasks` is on. This comes before every other rule.
    - Their own tasks and the ones they handed out, always.
    - With tasks.view_all: everything in their branch scope (tasks of other branches, and
      tasks without a branch, only with every branch).
    - With tasks.confirm: also work waiting for a check, in their branch scope.
    - Then every filter other apps registered (apps.tasks.visibility), which only narrow it.
    """
    tasks = Task.objects.for_company(member.company_id).select_related(*TASK_RELATIONS)
    others_personal = Q(kind=Task.Kind.PERSONAL) & ~Q(assignee=member)
    role = member.role
    if not (role is not None and role.is_owner and member.company.owner_sees_personal_tasks):
        tasks = tasks.exclude(others_personal)
    own = Q(assignee=member) | Q(created_by=member)
    scope = branch_ids(member)  # None = every branch
    if member.has_perm(Perm.TASKS_VIEW_ALL):
        if scope is not None:
            tasks = tasks.filter(Q(branch_id__in=scope) | own)
    elif member.has_perm(Perm.TASKS_CONFIRM):
        review = Q(status=Task.Status.REVIEW)
        if scope is not None:
            review &= Q(branch_id__in=scope)
        tasks = tasks.filter(own | review)
    else:
        tasks = tasks.filter(own)
    return visibility.apply_filters(tasks, member)


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


def board_tasks(member: Membership, now: datetime) -> QuerySet[Task]:
    """The member's own board: everything still open or being checked, plus today's finished."""
    tz = ZoneInfo(member.company.timezone)
    start_of_today = datetime.combine(timezone.localtime(now, tz).date(), time.min, tzinfo=tz)
    return (
        Task.objects.for_company(member.company_id)
        .select_related(*TASK_RELATIONS)
        .filter(assignee=member)
        .filter(
            Q(status__in=(*Task.OPEN_STATUSES, Task.Status.REVIEW))
            | Q(status=Task.Status.DONE, completed_at__gte=start_of_today)
        )
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
