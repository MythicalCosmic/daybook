"""Read-only AI tools over tasks (docs/PLAN-OWNER.md §8.3): `tasks_search` and `tasks_get`.

They act as the person asking (visibility and branch scope through `queries`), never show a
personal task (personal tasks are never sent to the AI, §0), and give free text (descriptions,
comments, proof reports) only when the owner switched `share_task_text` on."""

from datetime import date
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
