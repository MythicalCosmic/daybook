"""Read-only AI tools over tasks (docs/PLAN-OWNER.md §8.3): `tasks_search`, `tasks_get` and
`tasks_readings` (storage readings, §14.10).

They act as the person asking (visibility and branch scope through `queries`), never show a
personal task (personal tasks are never sent to the AI, §0), and give free text (descriptions,
comments, proof reports, reading notes) only when the owner switched `share_task_text` on."""

from datetime import date, timedelta
from typing import Literal

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool
from apps.members.permissions import Perm
from apps.tasks import queries
from apps.tasks.models import Task

TEXT_SWITCH = "share_task_text"
SHARED = [Task.Kind.DAILY, Task.Kind.ASSIGNED]


class TasksSearchInput(BaseModel):
    status: list[Literal["todo", "in_progress", "review", "returned", "done", "cancelled"]] = Field(
        default_factory=list, description="Only these statuses (empty: all)."
    )
    kind: Literal["daily", "assigned"] | None = Field(
        None, description="Daily routine work or tasks given by someone."
    )
    assignee_id: int | None = Field(None, description="A person's id (from another tool).")
    position_id: int | None = None
    due_from: date | None = Field(None, description="First due day, company-local.")
    due_to: date | None = Field(None, description="Last due day, company-local (inclusive).")
    overdue: bool | None = Field(None, description="True: open and past the deadline now.")
    q: str | None = Field(None, max_length=100, description="Words in the title.")
    limit: int = Field(25, ge=1, le=50)


class TasksGetInput(BaseModel):
    task_id: int


def _row(task: Task, ctx: ToolContext) -> dict:
    row = {
        "id": task.pk,
        "title": task.title,
        "status": task.status,
        "kind": task.kind,
        "priority": task.priority,
        "assignee": str(task.assignee),
        "assignee_id": task.assignee_id,
        "position": task.assignee.position.name if task.assignee.position_id else None,
        "branch": task.branch.name if task.branch_id else None,
        "routine": task.template.title if task.template_id and not task.template.personal else None,
        "due_at": task.due_at,
        "completed_at": task.completed_at,
        "overdue": task.is_overdue(ctx.now),
        "needs_confirmation": task.needs_confirmation,
        "reward": task.reward,
    }
    if TEXT_SWITCH in ctx.switches:
        row["description"] = task.description[:300]
    return row


@ai_tool(
    "tasks_search",
    domain="tasks",
    perm=Perm.TASKS_VIEW_ALL,
    label=_("Find tasks by status, person, position, due dates or words in the title."),
    input=TasksSearchInput,
)
def tasks_search(ctx: ToolContext, args: TasksSearchInput) -> ToolResult:
    kinds = [args.kind] if args.kind else SHARED
    tasks, total = queries.search(
        ctx.company,
        viewer=ctx.membership,
        branch_ids=ctx.branch_ids,
        status=args.status or None,
        kind=kinds,
        assignee_id=args.assignee_id,
        position_id=args.position_id,
        due_from=args.due_from,
        due_to=args.due_to,
        overdue=args.overdue,
        q=args.q,
        limit=args.limit,
    )
    return ToolResult(rows=[_row(task, ctx) for task in tasks], total=total, as_of=ctx.now)


@ai_tool(
    "tasks_get",
    domain="tasks",
    perm=Perm.TASKS_VIEW_ALL,
    label=_("One task in detail: checklist progress, reminders sent, latest comments."),
    input=TasksGetInput,
)
def tasks_get(ctx: ToolContext, args: TasksGetInput) -> ToolResult:
    task = queries.detail(args.task_id, viewer=ctx.membership)
    if task is None or task.kind == Task.Kind.PERSONAL:
        raise ToolNotFound
    if (
        ctx.branch_ids is not None
        and task.branch_id not in ctx.branch_ids
        and task.assignee_id != ctx.membership.pk
    ):
        raise ToolNotFound
    items = list(task.checklist.all())
    data = _row(task, ctx) | {
        "checklist": {"done": sum(item.is_done for item in items), "total": len(items)},
        "reminders_sent": task.reminders_sent,
        "escalated_at": task.escalated_at,
        "has_proof_photo": bool(task.proof_photo),
        "confirmed_at": task.confirmed_at,
        "given_by": str(task.created_by) if task.created_by_id else None,
    }
    if TEXT_SWITCH in ctx.switches:
        data["proof_text"] = task.proof_text[:300]
        data["comments"] = [
            {
                "author": str(comment.author) if comment.author_id else None,
                "at": comment.created_at,
                "text": comment.text[:300],
            }
            for comment in task.comments.select_related("author__user").order_by("-created_at")[:10]
        ]
    return ToolResult(data=data, as_of=ctx.now)


class TasksReadingsInput(BaseModel):
    days: int = Field(7, ge=1, le=62, description="How many days back, today included.")
    branch_id: int | None = Field(None, description="One branch's id (from another tool).")


@ai_tool(
    "tasks_readings",
    domain="tasks",
    perm=Perm.TASKS_VIEW_ALL,
    label=_(
        "Storage readings (fridge and room temperature, humidity): values out of range and "
        "missed readings per routine and branch."
    ),
    input=TasksReadingsInput,
)
def tasks_readings(ctx: ToolContext, args: TasksReadingsInput) -> ToolResult:
    """Per readings routine: how many values were taken, the ones out of range (and whether a
    recheck brought them back) and the days nobody took them. Notes are free text: only with
    the owner's `share_task_text` switch."""
    from apps.tasks import journal

    scope = ctx.branch_ids
    if args.branch_id is not None:
        if scope is not None and args.branch_id not in scope:
            raise ToolNotFound
        scope = [args.branch_id]
    end = queries.company_today(ctx.company, ctx.now)
    start = end - timedelta(days=args.days - 1)
    rows = queries.readings_journal(ctx.company, start, end, branch_ids=scope)
    by_routine: dict[int, list[dict]] = {}
    for row in rows:
        if row["routine"] is not None:
            by_routine.setdefault(row["routine"]["id"], []).append(row)
    routines = journal.reading_routines(ctx.company.pk, scope).select_related("branch")
    found = []
    for routine in routines.order_by("branch__name", "due_time", "title"):
        taken = by_routine.get(routine.pk, [])
        if not routine.is_active and not taken:
            continue
        excursions = []
        for row in taken:
            if row["in_range"] or row["is_recheck"]:
                continue
            back = any(
                later["is_recheck"] and later["key"] == row["key"] and later["in_range"]
                for later in taken
                if later["task_id"] == row["task_id"]
            )
            item = {
                "day": row["day"],
                "time": row["time"],
                "label": row["label"],
                "value": row["value"],
                "unit": row["unit"],
                "min": row["min"],
                "max": row["max"],
                "back_in_range": back,
            }
            if TEXT_SWITCH in ctx.switches:
                item["note"] = row["note"][:300]
            excursions.append(item)
        found.append(
            {
                "id": routine.pk,
                "routine": routine.title,
                "branch": routine.branch.name if routine.branch_id else None,
                "due_time": routine.due_time.strftime("%H:%M"),
                "active": routine.is_active,
                "readings_taken": sum(1 for row in taken if not row["is_recheck"]),
                "out_of_range": excursions,
                "missed_days": journal.missed_days(routine, start, end, ctx.now),
            }
        )
    return ToolResult(rows=found, total=len(found), as_of=ctx.now)
