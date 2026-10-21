"""Read functions of projects, for other apps, the dashboard, the mini app and the AI tools.

Who sees what (docs/PLAN-OWNER.md §13.3, §2.6):

- A project's members and its lead always see it.
- `projects.view_all` holders see every project in their branch scope (a project without a
  branch only with every branch, unless it is open to the whole company).
- A project with `visibility=company` is seen by everyone whose branches include its branch
  (or by everyone when it has no branch).
- Everyone else sees nothing of it, and none of its tasks (the task visibility filter).

Who may change what: `projects.manage` holders who see the project, and its lead, manage it;
members (not viewers) also add and move cards and post updates; an assignee always moves their
own card. Money on a project is shown to `finance.view` holders and to those who manage it;
labour cost (it reveals pay rates) only to `payroll.view` holders.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, Max, Prefetch, Q, QuerySet, Sum
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.core.money import quantize
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.scope import branch_ids
from apps.payroll import contracts as payroll_contracts
from apps.projects import conf
from apps.projects.models import (
    Health,
    Milestone,
    Project,
    ProjectList,
    ProjectMember,
    ProjectUpdate,
    RunningTimer,
    TaskLabel,
    TimeEntry,
)
from apps.tasks.models import Task

Role = ProjectMember.Role
EDITING_ROLES = (Role.LEAD, Role.MEMBER)
# Cards the board shows: everything but cancelled work.
BOARD_STATUSES = (*Task.OPEN_STATUSES, Task.Status.REVIEW, Task.Status.DONE)


# Access ---------------------------------------------------------------------------------


def _mine(member: Membership) -> Q:
    joined = ProjectMember.objects.filter(membership=member).values("project_id")
    return Q(pk__in=joined) | Q(lead=member)


def visible_projects(member: Membership, *, archived: bool = False) -> QuerySet[Project]:
    """Projects `member` may open (archived ones only with `archived=True`)."""
    projects = Project.objects.for_company(member.company_id)
    if not archived:
        projects = projects.filter(archived_at__isnull=True)
    if member.status != Membership.Status.APPROVED:
        return projects.none()
    mine = _mine(member)
    scope = branch_ids(member)
    company_wide = Q(visibility=Project.Visibility.COMPANY)
    if member.has_perm(Perm.PROJECTS_VIEW_ALL):
        if scope is None:
            return projects
        return projects.filter(
            mine | Q(branch_id__in=scope) | (company_wide & Q(branch__isnull=True))
        )
    if scope is None:
        return projects.filter(mine | company_wide)
    return projects.filter(
        mine | (company_wide & (Q(branch__isnull=True) | Q(branch_id__in=scope)))
    )


def get_visible(member: Membership, pk, *, archived: bool = True) -> Project:
    """The project `pk` if `member` may open it; `Project.DoesNotExist` otherwise (a 404, like
    another company's id)."""
    project = (
        visible_projects(member, archived=archived)
        .select_related("company", "lead__user", "branch", "client", "created_by__user")
        .get(pk=pk)
    )
    project._visible_for = member.pk
    return project


def prime_access(projects: list[Project], member: Membership) -> None:
    """Remember `member`'s role on each of `projects` (one query) and that they may see them,
    so `role_of`, `can_view`, `can_manage` and `sees_money` cost nothing per row. Only for
    projects that came from `visible_projects(member)` (or `my_projects`)."""
    if not projects:
        return
    roles = dict(
        ProjectMember.objects.filter(
            project_id__in=[p.pk for p in projects], membership=member
        ).values_list("project_id", "role")
    )
    for project in projects:
        project._role_cache = {member.pk: roles.get(project.pk)}
        project._visible_for = member.pk


def role_of(project: Project, member: Membership) -> str | None:
    """`lead`, `member`, `viewer` or None. The project's lead is always `lead`."""
    if project.lead_id == member.pk:
        return Role.LEAD
    cached = getattr(project, "_role_cache", None)
    if cached is not None and member.pk in cached:
        return cached[member.pk]
    return (
        ProjectMember.objects.filter(project=project, membership=member)
        .values_list("role", flat=True)
        .first()
    )


def can_view(project: Project, member: Membership) -> bool:
    if project.company_id != member.company_id:
        return False
    if getattr(project, "_visible_for", None) == member.pk:
        return True
    return visible_projects(member, archived=True).filter(pk=project.pk).exists()


def can_manage(project: Project, member: Membership) -> bool:
    """Edit the project, its lists, milestones, labels and members."""
    if project.company_id != member.company_id or member.status != Membership.Status.APPROVED:
        return False
    if role_of(project, member) == Role.LEAD:
        return True
    return member.has_perm(Perm.PROJECTS_MANAGE) and can_view(project, member)


def managed_projects(member: Membership) -> QuerySet[Project]:
    """Projects `member` manages: every visible one with `projects.manage`, else the ones they
    lead."""
    if member.has_perm(Perm.PROJECTS_MANAGE):
        return visible_projects(member, archived=True)
    leading = ProjectMember.objects.filter(membership=member, role=Role.LEAD).values("project_id")
    return Project.objects.for_company(member.company_id).filter(Q(lead=member) | Q(pk__in=leading))


def can_edit_cards(project: Project, member: Membership) -> bool:
    """Add cards, move any card, label and plan them."""
    return can_manage(project, member) or role_of(project, member) in EDITING_ROLES


def can_post_update(project: Project, member: Membership) -> bool:
    return can_edit_cards(project, member)


def can_move_card(task: Task, member: Membership) -> bool:
    """Anyone who edits the project's cards, and the assignee for their own card."""
    if task.project_id is None:
        return False
    if task.assignee_id == member.pk:
        return True
    return can_edit_cards(task.project, member)


def sees_money(project: Project, member: Membership) -> bool:
    return member.has_perm(Perm.FINANCE_VIEW) or can_manage(project, member)


def sees_labour(member: Membership) -> bool:
    return member.has_perm(Perm.PAYROLL_VIEW)


def sees_all_time(member: Membership) -> bool:
    return member.has_perm(Perm.PROJECTS_TIME_VIEW)


def sees_time_of_others(project: Project, member: Membership) -> bool:
    """Everyone's time on this project: `projects.time_view` holders and its managers (the
    same rule as `time_entries`)."""
    return sees_all_time(member) or can_manage(project, member)


def capabilities(project: Project, member: Membership) -> dict:
    """What the client may offer `member` on this project."""
    manage = can_manage(project, member)
    edit = manage or role_of(project, member) in EDITING_ROLES
    return {
        "manage": manage,
        "edit_cards": edit,
        "post_update": edit,
        "see_money": member.has_perm(Perm.FINANCE_VIEW) or manage,
        "add_expense": member.has_perm(Perm.FINANCE_RECORD) and project.archived_at is None,
        "see_labour": sees_labour(member),
        "see_all_time": sees_all_time(member) or manage,
    }


# Progress, money, health ----------------------------------------------------------------


def local_today(company, now: datetime | None = None) -> date:
    return timezone.localtime(now or timezone.now(), ZoneInfo(company.timezone)).date()


def progress_many(project_ids: list[int], *, now: datetime | None = None) -> dict[int, dict]:
    """{project id: {"done", "total", "overdue", "percent"}} over the cards that aren't
    cancelled."""
    now = now or timezone.now()
    rows = (
        Task.objects.filter(project_id__in=project_ids)
        .exclude(status=Task.Status.CANCELLED)
        .values("project_id")
        .annotate(
            total=Count("pk"),
            done=Count("pk", filter=Q(status=Task.Status.DONE)),
            overdue=Count("pk", filter=Q(status__in=Task.OPEN_STATUSES, due_at__lt=now)),
        )
    )
    found = {pid: {"done": 0, "total": 0, "overdue": 0, "percent": 0} for pid in project_ids}
    for row in rows:
        total = row["total"]
        found[row["project_id"]] = {
            "done": row["done"],
            "total": total,
            "overdue": row["overdue"],
            "percent": round(row["done"] * 100 / total) if total else 0,
        }
    return found


def progress(project: Project, *, now: datetime | None = None) -> dict:
    """Done/total overall and per milestone, plus the overdue count (§13.3)."""
    now = now or timezone.now()
    overall = progress_many([project.pk], now=now)[project.pk]
    per_milestone = {
        row["milestone_id"]: row
        for row in Task.objects.filter(project=project, milestone__isnull=False)
        .exclude(status=Task.Status.CANCELLED)
        .values("milestone_id")
        .annotate(total=Count("pk"), done=Count("pk", filter=Q(status=Task.Status.DONE)))
    }
    milestones = []
    for milestone in project.milestones.all():
        row = per_milestone.get(milestone.pk, {"total": 0, "done": 0})
        milestones.append(
            {
                "id": milestone.pk,
                "done": row["done"],
                "total": row["total"],
                "percent": round(row["done"] * 100 / row["total"]) if row["total"] else 0,
            }
        )
    return overall | {"milestones": milestones}


@dataclass
class Money:
    spent: Decimal
    income: Decimal


def money_many(project_ids: list[int]) -> dict[int, Money]:
    """Posted income and expenses on each project, in the company's base currency. Spent is
    positive (expenses are stored negative; a refund of an expense lowers it)."""
    from apps.finance.models import Transaction

    found = {pid: Money(Decimal("0"), Decimal("0")) for pid in project_ids}
    rows = (
        Transaction.objects.filter(
            project_id__in=project_ids,
            status=Transaction.Status.POSTED,
            kind__in=(Transaction.Kind.EXPENSE, Transaction.Kind.INCOME),
        )
        .values("project_id", "kind")
        .annotate(total=Sum("base_amount"))
    )
    for row in rows:
        money = found[row["project_id"]]
        if row["kind"] == Transaction.Kind.EXPENSE:
            money.spent = -(row["total"] or Decimal("0"))
        else:
            money.income = row["total"] or Decimal("0")
    return found


def budget_in_base(project: Project, *, today: date | None = None) -> Decimal | None:
    """The budget in the company's base currency (None without a budget or a rate)."""
    if project.budget is None:
        return None
    base = project.company.base_currency
    if project.budget_currency == base:
        return project.budget
    from apps.finance import services as finance

    try:
        quote = finance.rate_for(
            project.company, project.budget_currency, today or local_today(project.company)
        )
        return quantize(finance.convert(project.budget, project.budget_currency, base, quote.rate))
    except DomainError:
        return None


def burn_percent(spent: Decimal, budget: Decimal | None) -> int | None:
    if not budget:
        return None
    return round(spent * 100 / budget)


def health(
    project: Project,
    *,
    today: date,
    percent: int,
    spent: Decimal,
    budget: Decimal | None,
    overdue_milestones: int,
    settings=None,
) -> str | None:
    """`off_track` when a milestone or the project itself is overdue or more than the budget is
    spent; `at_risk` when the due date is close and too little is done; else `on_track`.
    Finished and cancelled projects have no health. `settings`: the company's
    `ProjectSettings`, looked up when not given."""
    if project.status not in Project.LIVE_STATUSES:
        return None
    settings = settings or conf.get_settings(project.company)
    if overdue_milestones or (budget is not None and spent > budget):
        return Health.OFF_TRACK
    if project.due_on is not None and project.due_on < today:
        return Health.OFF_TRACK
    if (
        project.due_on is not None
        and project.due_on <= today + timedelta(days=settings.at_risk_days)
        and percent < settings.at_risk_percent
    ):
        return Health.AT_RISK
    return Health.ON_TRACK


def overdue_milestones_many(project_ids: list[int], today: date) -> dict[int, int]:
    rows = (
        Milestone.objects.filter(
            project_id__in=project_ids, status=Milestone.Status.OPEN, due_on__lt=today
        )
        .values("project_id")
        .annotate(n=Count("pk"))
    )
    found = dict.fromkeys(project_ids, 0)
    for row in rows:
        found[row["project_id"]] = row["n"]
    return found


def health_of(project: Project, *, now: datetime | None = None) -> str | None:
    """`health()` with everything it needs looked up (for one project)."""
    today = local_today(project.company, now)
    return health(
        project,
        today=today,
        percent=progress_many([project.pk], now=now)[project.pk]["percent"],
        spent=money_many([project.pk])[project.pk].spent,
        budget=budget_in_base(project, today=today),
        overdue_milestones=overdue_milestones_many([project.pk], today)[project.pk],
    )


def summaries(projects: list[Project], *, now: datetime | None = None) -> dict[int, dict]:
    """Index-card numbers for many projects at once: progress, spent, burn, health, the last
    reported health, members and the open card count."""
    if not projects:
        return {}
    now = now or timezone.now()
    ids = [p.pk for p in projects]
    company = projects[0].company
    today = local_today(company, now)
    prog = progress_many(ids, now=now)
    money = money_many(ids)
    late = overdue_milestones_many(ids, today)
    settings = conf.get_settings(company)
    reported: dict[int, ProjectUpdate] = {}
    for update in (
        ProjectUpdate.objects.filter(project_id__in=ids)
        .select_related("author__user")
        .order_by("project_id", "-created_at", "-pk")
        .distinct("project_id")
    ):
        reported[update.project_id] = update
    members: dict[int, list[Membership]] = defaultdict(list)
    for row in ProjectMember.objects.filter(project_id__in=ids).select_related("membership__user"):
        members[row.project_id].append(row.membership)
    next_milestone: dict[int, Milestone] = {}
    for milestone in (
        Milestone.objects.filter(project_id__in=ids, status=Milestone.Status.OPEN)
        .exclude(due_on__isnull=True)
        .order_by("project_id", "due_on", "pk")
        .distinct("project_id")
    ):
        next_milestone[milestone.project_id] = milestone
    out = {}
    for project in projects:
        budget = budget_in_base(project, today=today)
        spent = money[project.pk].spent
        out[project.pk] = {
            "progress": prog[project.pk],
            "spent": spent,
            "income": money[project.pk].income,
            "budget_base": budget,
            "burn": burn_percent(spent, budget),
            "health": health(
                project,
                today=today,
                percent=prog[project.pk]["percent"],
                spent=spent,
                budget=budget,
                overdue_milestones=late[project.pk],
                settings=settings,
            ),
            "overdue_milestones": late[project.pk],
            "reported": reported.get(project.pk),
            "members": members[project.pk],
            "next_milestone": next_milestone.get(project.pk),
        }
    return out


def labour_cost(project: Project) -> Decimal | None:
    """Minutes times `payroll.contracts.cost_rate`, per person and day, unknown rates skipped.
    None when no rate at all is known (payroll not set up yet)."""
    rows = (
        TimeEntry.objects.filter(project=project)
        .values("membership_id", "day")
        .annotate(minutes=Sum("minutes"))
    )
    people = {
        m.pk: m for m in Membership.objects.filter(pk__in={row["membership_id"] for row in rows})
    }
    total = Decimal("0")
    known = False
    for row in rows:
        rate = payroll_contracts.cost_rate(people[row["membership_id"]], row["day"])
        if rate is None:
            continue
        known = True
        total += Decimal(row["minutes"]) / 60 * rate
    return quantize(total) if known else None


def financials(project: Project, *, viewer: Membership) -> dict:
    """Budget, spent, income, open receivables, labour cost and margin (§13.3), in the base
    currency, plus spend by category and by month and the latest linked transactions. Labour
    cost (and the margin after it) only for `payroll.view` holders."""
    from apps.finance.models import Debt, Transaction

    today = local_today(project.company)
    money = money_many([project.pk])[project.pk]
    budget = budget_in_base(project, today=today)
    from apps.finance.rates import convert

    base = project.company.base_currency
    receivable = Decimal("0")
    for debt in Debt.objects.filter(
        project=project, direction=Debt.Direction.RECEIVABLE, status=Debt.Status.OPEN
    ):
        receivable += convert(debt.amount - debt.paid, debt.currency, base, debt.rate)
    show_labour = sees_labour(viewer)
    labour = labour_cost(project) if show_labour else None
    margin = money.income - money.spent - (labour or Decimal("0"))
    posted = Transaction.objects.filter(project=project, status=Transaction.Status.POSTED)
    by_category = [
        {
            "category_id": row["category_id"],
            "name": row["category__name"] or "",
            "color": row["category__color"] or "",
            "amount": -(row["total"] or Decimal("0")),
        }
        for row in posted.filter(kind=Transaction.Kind.EXPENSE)
        .values("category_id", "category__name", "category__color")
        .annotate(total=Sum("base_amount"))
        .order_by("total")
    ]
    by_month: dict[str, dict] = {}
    for row in posted.filter(kind__in=(Transaction.Kind.EXPENSE, Transaction.Kind.INCOME)).values(
        "occurred_on", "kind", "base_amount"
    ):
        month = row["occurred_on"].strftime("%Y-%m-01")
        bucket = by_month.setdefault(
            month, {"month": month, "spent": Decimal("0"), "income": Decimal("0")}
        )
        if row["kind"] == Transaction.Kind.EXPENSE:
            bucket["spent"] -= row["base_amount"]
        else:
            bucket["income"] += row["base_amount"]
    payroll_view = viewer.has_perm(Perm.PAYROLL_VIEW)
    transactions = []
    for txn in (
        Transaction.objects.filter(project=project)
        .exclude(status=Transaction.Status.REJECTED)
        .select_related("category", "account", "counterparty", "created_by")
        .order_by("-occurred_on", "-pk")[:50]
    ):
        sensitive = txn.category is not None and txn.category.is_sensitive and not payroll_view
        transactions.append(
            {
                "id": txn.pk,
                "occurred_on": txn.occurred_on,
                "kind": txn.kind,
                "status": txn.status,
                "amount": txn.amount,
                "currency": txn.currency,
                "base_amount": txn.base_amount,
                "category": txn.category.name if txn.category else "",
                "account": txn.account.name if txn.account else "",
                "counterparty": txn.counterparty.name if txn.counterparty and not sensitive else "",
                "description": "" if sensitive else txn.description,
                "hidden": sensitive,
            }
        )
    result = {
        "currency": project.company.base_currency,
        "budget": budget,
        "budget_original": project.budget,
        "budget_currency": project.budget_currency,
        "spent": money.spent,
        "income": money.income,
        "receivable": receivable,
        "margin": margin,
        "margin_includes_labour": labour is not None,
        "burn": burn_percent(money.spent, budget),
        "remaining": (budget - money.spent) if budget is not None else None,
        "by_category": by_category,
        "by_month": sorted(by_month.values(), key=lambda b: b["month"]),
        "transactions": transactions,
    }
    if show_labour:
        result["labour_cost"] = labour
    return result


# Board ----------------------------------------------------------------------------------


def board_cards(project: Project, member: Membership) -> QuerySet[Task]:
    """The project's cards a member of it sees: everything but cancelled work and other people's
    personal tasks (unless the owner may see those)."""
    tasks = Task.objects.filter(project=project, status__in=BOARD_STATUSES)
    role = member.role
    if not (role is not None and role.is_owner and member.company.owner_sees_personal_tasks):
        tasks = tasks.exclude(Q(kind=Task.Kind.PERSONAL) & ~Q(assignee=member))
    return (
        tasks.select_related("assignee__user", "card", "milestone", "project_list")
        .prefetch_related(
            Prefetch("label_links", queryset=TaskLabel.objects.only("task_id", "label_id"))
        )
        .annotate(
            checklist_total=Count("checklist", distinct=True),
            checklist_done=Count("checklist", filter=Q(checklist__is_done=True), distinct=True),
            comment_count=Count("comments", distinct=True),
        )
        .order_by("list_position", "pk")
    )


def logged_minutes(task_ids: list[int]) -> dict[int, int]:
    return {
        row["task_id"]: row["total"]
        for row in TimeEntry.objects.filter(task_id__in=task_ids)
        .values("task_id")
        .annotate(total=Sum("minutes"))
    }


def first_list(project: Project) -> ProjectList | None:
    return project.lists.filter(is_done=False).order_by("position", "pk").first()


def done_list(project: Project) -> ProjectList | None:
    return project.lists.filter(is_done=True).first()


def review_list(project: Project) -> ProjectList | None:
    """Where a card waiting for a check goes: the last list before Done."""
    return project.lists.filter(is_done=False).order_by("-position", "-pk").first()


def end_position(project_list: ProjectList) -> float:
    last = Task.objects.filter(project_list=project_list).aggregate(top=Max("list_position"))["top"]
    return (last or 0) + 1024


def card_key(project: Project, task: Task) -> str:
    card = getattr(task, "card", None)
    return f"{project.key}-{card.number}" if card is not None else f"{project.key}-{task.pk}"


# Members and load -----------------------------------------------------------------------


def members_with_load(project: Project, *, now: datetime | None = None) -> list[dict]:
    """Members with their open and overdue cards here, and hours logged this week."""
    now = now or timezone.now()
    today = local_today(project.company, now)
    week_start = today - timedelta(days=today.weekday())
    rows = list(
        ProjectMember.objects.filter(project=project).select_related(
            "membership__user", "membership__position"
        )
    )
    if project.lead_id and not any(r.membership_id == project.lead_id for r in rows):
        rows.insert(0, ProjectMember(project=project, membership=project.lead, role=Role.LEAD))
    ids = [r.membership_id for r in rows]
    cards = {
        row["assignee_id"]: row
        for row in Task.objects.filter(project=project, assignee_id__in=ids)
        .values("assignee_id")
        .annotate(
            open=Count("pk", filter=Q(status__in=Task.OPEN_STATUSES)),
            review=Count("pk", filter=Q(status=Task.Status.REVIEW)),
            done=Count("pk", filter=Q(status=Task.Status.DONE)),
            overdue=Count("pk", filter=Q(status__in=Task.OPEN_STATUSES, due_at__lt=now)),
        )
    }
    minutes = {
        row["membership_id"]: row["total"]
        for row in TimeEntry.objects.filter(
            project=project, membership_id__in=ids, day__gte=week_start
        )
        .values("membership_id")
        .annotate(total=Sum("minutes"))
    }
    out = []
    for row in rows:
        mid = row.membership_id
        counts = cards.get(mid, {})
        role = Role.LEAD if mid == project.lead_id else row.role
        out.append(
            {
                "id": row.pk,
                "membership": row.membership,
                "role": role,
                "open": counts.get("open", 0),
                "review": counts.get("review", 0),
                "done": counts.get("done", 0),
                "overdue": counts.get("overdue", 0),
                "week_minutes": minutes.get(mid, 0),
            }
        )
    order = {Role.LEAD: 0, Role.MEMBER: 1, Role.VIEWER: 2}
    out.sort(key=lambda r: (order.get(r["role"], 3), str(r["membership"]).lower()))
    return out


def my_projects(member: Membership) -> QuerySet[Project]:
    """Projects the person works on (member or lead), live ones first."""
    return (
        Project.objects.for_company(member.company_id)
        .filter(archived_at__isnull=True)
        .filter(_mine(member))
        .select_related("lead__user", "company")
    )


# Time -----------------------------------------------------------------------------------


def week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def time_entries(
    member: Membership,
    *,
    start: date,
    end: date,
    project: Project | None = None,
    person_ids: list[int] | None = None,
) -> QuerySet[TimeEntry]:
    """Time entries `member` may see between two days: their own, everyone's on projects they
    manage, and with `projects.time_view` everyone's on projects they see (plus time outside
    projects of people in their branch scope)."""
    entries = TimeEntry.objects.for_company(member.company_id).filter(day__range=(start, end))
    if project is not None:
        entries = entries.filter(project=project)
    if person_ids:
        entries = entries.filter(membership_id__in=person_ids)
    own = Q(membership=member)
    if sees_all_time(member):
        visible = visible_projects(member, archived=True).values("pk")
        scope = branch_ids(member)
        outside = Q(project__isnull=True)
        if scope is not None:
            outside &= Q(membership__branches__in=scope)
        entries = entries.filter(own | Q(project__in=visible) | outside)
    else:
        entries = entries.filter(own | Q(project__in=managed_projects(member).values("pk")))
    return entries.select_related("membership__user", "project", "task", "task__card").distinct()


def running_timers(member: Membership, *, project: Project | None = None) -> QuerySet[RunningTimer]:
    timers = RunningTimer.objects.for_company(member.company_id).select_related(
        "membership__user", "task__card", "project", "task__project"
    )
    if project is not None:
        timers = timers.filter(Q(project=project) | Q(task__project=project))
    if sees_all_time(member):
        return timers.filter(
            Q(membership=member)
            | Q(project__in=visible_projects(member, archived=True).values("pk"))
            | Q(task__project__in=visible_projects(member, archived=True).values("pk"))
            | (Q(project__isnull=True) & Q(task__project__isnull=True))
        )
    managed = managed_projects(member).values("pk")
    return timers.filter(
        Q(membership=member) | Q(project__in=managed) | Q(task__project__in=managed)
    )


# Timeline and roadmap -------------------------------------------------------------------


def card_dates(task: Task, tz: ZoneInfo) -> tuple[date, date]:
    """A card's bar: from its planned start (else when it was made) to its deadline."""
    card = getattr(task, "card", None)
    created = timezone.localtime(task.created_at, tz).date()
    due = timezone.localtime(task.due_at, tz).date() if task.due_at else None
    start = (card.start_on if card is not None and card.start_on else None) or created
    end = due or start
    if end < start:
        start = end
    return start, end


def project_dates(project: Project, *, today: date) -> tuple[date, date]:
    """A project's roadmap bar; without dates it spans a month from when it was made."""
    tz = ZoneInfo(project.company.timezone)
    start = project.start_on or timezone.localtime(project.created_at, tz).date()
    end = project.due_on or max(start + timedelta(days=30), today)
    if end < start:
        end = start
    return start, end
