from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.members.scope import allows, branch_ids
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
    "project",
    "branch",
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
    return confirmers(task)


def search(
    company,
    *,
    viewer: Membership,
    branch_ids: list[int] | None,
    status=None,
    kind=None,
    assignee_id: int | None = None,
    position_id: int | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    overdue: bool | None = None,
    q: str | None = None,
    limit: int = 50,
) -> tuple[list[Task], int]:
    """Tasks `viewer` may see, filtered; (up to `limit` tasks, how many match). `branch_ids`
    narrows to those branches (None: no narrowing beyond the viewer's own scope); `status` and
    `kind` take one value or several; days are the company's own."""
    filters = TaskFilters(
        status=_as_list(status),
        kind=_as_list(kind),
        assignee=[assignee_id] if assignee_id else [],
        position=[position_id] if position_id else [],
        due_from=due_from,
        due_to=due_to,
        overdue=overdue,
        q=q or "",
    )
    tasks = filtered(company, viewer=viewer, filters=filters, branch_ids=branch_ids)
    return list(tasks[:limit]), tasks.count()


def detail(task_id: int, *, viewer: Membership) -> Task | None:
    """One task `viewer` may see, with its checklist, comments and reminder log; else None."""
    return visible_tasks(viewer).prefetch_related("checklist").filter(pk=task_id).first()


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, list | tuple | set) else [value]


@dataclass
class TaskFilters:
    """The owner list's filters (docs/PLAN-OWNER.md §4.5)."""

    status: list[str] = field(default_factory=list)
    kind: list[str] = field(default_factory=list)
    assignee: list[int] = field(default_factory=list)
    position: list[int] = field(default_factory=list)
    branch: list[int] = field(default_factory=list)
    created_by: list[int] = field(default_factory=list)
    priority: list[str] = field(default_factory=list)
    routine: list[int] = field(default_factory=list)
    due_from: date | None = None
    due_to: date | None = None
    overdue: bool | None = None
    has_proof: bool | None = None
    needs_confirmation: bool | None = None
    q: str = ""


def filtered(
    company, *, viewer: Membership, filters: TaskFilters, branch_ids: list[int] | None
) -> QuerySet[Task]:
    """`visible_tasks(viewer)` with the owner list's filters applied."""
    tasks = visible_tasks(viewer)
    if branch_ids is not None:
        tasks = tasks.filter(
            Q(branch_id__in=branch_ids) | Q(assignee=viewer) | Q(created_by=viewer)
        )
    if filters.status:
        tasks = tasks.filter(status__in=filters.status)
    if filters.kind:
        tasks = tasks.filter(kind__in=filters.kind)
    if filters.assignee:
        tasks = tasks.filter(assignee_id__in=filters.assignee)
    if filters.position:
        tasks = tasks.filter(assignee__position_id__in=filters.position)
    if filters.branch:
        tasks = tasks.filter(branch_id__in=filters.branch)
    if filters.created_by:
        tasks = tasks.filter(created_by_id__in=filters.created_by)
    if filters.priority:
        tasks = tasks.filter(priority__in=filters.priority)
    if filters.routine:
        tasks = tasks.filter(template_id__in=filters.routine)
    tz = ZoneInfo(company.timezone)
    if filters.due_from:
        tasks = tasks.filter(due_at__gte=datetime.combine(filters.due_from, time.min, tzinfo=tz))
    if filters.due_to:
        end = datetime.combine(filters.due_to + timedelta(days=1), time.min, tzinfo=tz)
        tasks = tasks.filter(due_at__lt=end)
    if filters.overdue is not None:
        late = Q(status__in=Task.OPEN_STATUSES, due_at__lt=timezone.now())
        tasks = tasks.filter(late) if filters.overdue else tasks.exclude(late)
    if filters.has_proof is not None:
        proof = ~Q(proof_photo="") | ~Q(proof_text="")
        tasks = tasks.filter(proof) if filters.has_proof else tasks.exclude(proof)
    if filters.needs_confirmation is not None:
        tasks = tasks.filter(needs_confirmation=filters.needs_confirmation)
    if q := filters.q.strip():
        tasks = tasks.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(assignee__first_name__icontains=q)
            | Q(assignee__last_name__icontains=q)
        )
    return tasks


def late_now(member: Membership) -> QuerySet[Task]:
    """Open shared work past its deadline that `member` may see (personal tasks never count)."""
    return (
        visible_tasks(member)
        .exclude(kind=Task.Kind.PERSONAL)
        .filter(status__in=Task.OPEN_STATUSES, due_at__lt=timezone.now())
    )


def late_now_count(member: Membership) -> int:
    return late_now(member).count()


def review_count(member: Membership) -> int:
    return awaiting_review_by(member).count()


def day_bounds(company, day: date) -> tuple[datetime, datetime]:
    """The company-local day as two moments, [start, end)."""
    tz = ZoneInfo(company.timezone)
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def company_today(company, now: datetime | None = None) -> date:
    return timezone.localtime(now or timezone.now(), ZoneInfo(company.timezone)).date()


def confirmers(task: Task) -> list[Membership]:
    """Everyone who may confirm `task`: approved holders of tasks.confirm, the assignee left
    out, whose branch scope covers the task's branch (docs/PLAN-OWNER.md §2.6), so nobody is
    sent work, or its proof photo, they can't open."""
    candidates = (
        members_with_perm(task.company, Perm.TASKS_CONFIRM)
        .exclude(pk=task.assignee_id)
        .select_related("user", "role", "company")
        .prefetch_related("branches")
    )
    return [member for member in candidates if allows(branch_ids(member), task.branch_id)]
