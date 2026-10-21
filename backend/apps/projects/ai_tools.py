"""Read-only AI tools of projects.

Each wraps a function of `queries.py` and registers with `apps.ai.tools.registry.ai_tool`.
They see exactly the projects the asker may open (`queries.visible_projects`, which carries the
branch scope); money only for people who see the project's money and with the `share_finance`
data switch, labour cost only for `payroll.view` holders with `share_salaries`.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool
from apps.members.permissions import Perm
from apps.projects import queries
from apps.projects.models import Milestone, Project
from apps.tasks.models import Task


class ProjectsOverviewInput(BaseModel):
    status: list[str] = Field(
        default_factory=list,
        description="Only these statuses: planning, active, on_hold, completed, cancelled.",
    )
    health: list[str] = Field(
        default_factory=list, description="Only these: on_track, at_risk, off_track."
    )


def _money_allowed(ctx: ToolContext, project: Project) -> bool:
    return "share_finance" in ctx.switches and queries.sees_money(project, ctx.membership)


@ai_tool(
    "projects_overview",
    domain="projects",
    perm=Perm.DASHBOARD_ACCESS,
    label=_(
        "Projects: every project the asker sees, with progress, health, due date, lead and "
        "budget burn."
    ),
    input=ProjectsOverviewInput,
)
def projects_overview(ctx: ToolContext, args: ProjectsOverviewInput) -> ToolResult:
    projects = queries.visible_projects(ctx.membership).select_related("company", "lead", "branch")
    if args.status:
        projects = projects.filter(status__in=args.status)
    projects = list(projects.order_by("due_on", "name"))
    facts = queries.summaries(projects, now=ctx.now)
    rows = []
    for project in projects:
        fact = facts[project.pk]
        if args.health and fact["health"] not in args.health:
            continue
        row = {
            "id": project.pk,
            "key": project.key,
            "name": project.name,
            "status": project.status,
            "health": fact["health"],
            "lead": str(project.lead) if project.lead else None,
            "branch": project.branch.name if project.branch else None,
            "start_on": project.start_on,
            "due_on": project.due_on,
            "cards_done": fact["progress"]["done"],
            "cards_total": fact["progress"]["total"],
            "cards_overdue": fact["progress"]["overdue"],
            "percent_done": fact["progress"]["percent"],
            "milestones_overdue": fact["overdue_milestones"],
        }
        if _money_allowed(ctx, project):
            row |= {
                "budget": fact["budget_base"],
                "spent": fact["spent"],
                "budget_burn_percent": fact["burn"],
            }
        rows.append(row)
    return ToolResult(rows=rows, currency=ctx.company.base_currency, as_of=ctx.now)


class ProjectDetailInput(BaseModel):
    project_id: int | None = Field(default=None, description="The project's id.")
    key: str | None = Field(default=None, description="Or its key, e.g. RENO.")


@ai_tool(
    "projects_detail",
    domain="projects",
    perm=Perm.DASHBOARD_ACCESS,
    label=_(
        "One project in detail: milestones with progress, overdue cards, the people on it, "
        "the latest update, and its money when the asker may see it."
    ),
    input=ProjectDetailInput,
)
def project_detail(ctx: ToolContext, args: ProjectDetailInput) -> ToolResult:
    projects = queries.visible_projects(ctx.membership, archived=True).select_related(
        "company", "lead"
    )
    if args.project_id is not None:
        project = projects.filter(pk=args.project_id).first()
    elif args.key:
        project = projects.filter(key=args.key.strip().upper()).first()
    else:
        project = None
    if project is None:
        raise ToolNotFound
    fact = queries.summaries([project], now=ctx.now)[project.pk]
    progress = queries.progress(project, now=ctx.now)
    counts = {row["id"]: row for row in progress["milestones"]}
    overdue = (
        Task.objects.filter(project=project, status__in=Task.OPEN_STATUSES, due_at__lt=ctx.now)
        .select_related("assignee", "card")
        .order_by("due_at")[:20]
    )
    data = {
        "id": project.pk,
        "key": project.key,
        "name": project.name,
        "status": project.status,
        "health": fact["health"],
        "reported_health": fact["reported"].health if fact["reported"] else None,
        "latest_update": fact["reported"].text[:500] if fact["reported"] else None,
        "lead": str(project.lead) if project.lead else None,
        "start_on": project.start_on,
        "due_on": project.due_on,
        "progress": progress | {"milestones": None},
        "milestones": [
            {
                "id": m.pk,
                "name": m.name,
                "due_on": m.due_on,
                "status": m.status,
                "cards_done": counts.get(m.pk, {}).get("done", 0),
                "cards_total": counts.get(m.pk, {}).get("total", 0),
            }
            for m in project.milestones.all()
        ],
        "overdue_cards": [
            {
                "id": task.pk,
                "key": queries.card_key(project, task),
                "title": task.title if "share_task_text" in ctx.switches else None,
                "assignee": str(task.assignee),
                "due_at": task.due_at,
            }
            for task in overdue
        ],
        "people": [str(m) for m in fact["members"]],
        "open_milestones": sum(
            1 for m in project.milestones.all() if m.status == Milestone.Status.OPEN
        ),
    }
    if _money_allowed(ctx, project):
        money = queries.financials(project, viewer=ctx.membership)
        data["money"] = {
            "budget": money["budget"],
            "spent": money["spent"],
            "income": money["income"],
            "receivable": money["receivable"],
            "burn_percent": money["burn"],
            "margin": money["margin"],
        }
        if "share_salaries" in ctx.switches and "labour_cost" in money:
            data["money"]["labour_cost"] = money["labour_cost"]
    return ToolResult(data=data, currency=ctx.company.base_currency, as_of=ctx.now)
