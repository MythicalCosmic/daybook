"""Read-only AI tools over team results (docs/PLAN-OWNER.md §8.3): team performance, task
trends and routine compliance, all from `reports.kpis` in the asker's branch scope. Personal
tasks never count."""

from datetime import date
from typing import Literal

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field, model_validator

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.members.permissions import Perm
from apps.reports import kpis

MAX_DAYS = 366


class RangeInput(BaseModel):
    start: date = Field(description="First day, company-local.")
    end: date = Field(description="Last day, company-local (inclusive).")

    @model_validator(mode="after")
    def check(self):
        if self.end < self.start:
            raise ValueError("end is before start")
        if (self.end - self.start).days + 1 > MAX_DAYS:
            raise ValueError("pick at most a year")
        return self


class TeamPerformanceInput(RangeInput):
    group_by: Literal["member", "position", "routine", "branch", "day"] = "member"


class TaskTrendsInput(RangeInput):
    metric: Literal["on_time_percent", "done", "on_time", "late", "missed", "total"] = (
        "on_time_percent"
    )
    group_by: Literal["day", "week", "month"] = "day"


@ai_tool(
    "reports_team_performance",
    domain="reports",
    perm=Perm.REPORTS_VIEW,
    label=_(
        "Who did their tasks on time over a period, by person, position, routine, branch or day."
    ),
    input=TeamPerformanceInput,
)
def reports_team_performance(ctx: ToolContext, args: TeamPerformanceInput) -> ToolResult:
    rows = kpis.team_grouped(
        ctx.company, args.start, args.end, ctx.now, args.group_by, branch_ids=ctx.branch_ids
    )
    out = [
        {"id": row.key, "name": row.label, **row.score.as_dict(), **row.extra}
        for row in rows
        if row.score.total or row.score.late_now
    ]
    totals = kpis.sum_rows(rows).as_dict()
    return ToolResult(rows=out, data={"totals": totals, "group_by": args.group_by}, as_of=ctx.now)


@ai_tool(
    "reports_task_trends",
    domain="reports",
    perm=Perm.REPORTS_VIEW,
    label=_("How the team's on-time rate or finished tasks changed per day, week or month."),
    input=TaskTrendsInput,
)
def reports_task_trends(ctx: ToolContext, args: TaskTrendsInput) -> ToolResult:
    series = kpis.trend(
        ctx.company, args.metric, args.start, args.end, args.group_by, branch_ids=ctx.branch_ids
    )
    rows = [{"id": point["date"].isoformat(), **point} for point in series]
    return ToolResult(
        rows=rows, data={"metric": args.metric, "group_by": args.group_by}, as_of=ctx.now
    )


@ai_tool(
    "reports_routine_compliance",
    domain="reports",
    perm=Perm.REPORTS_VIEW,
    label=_(
        "Each daily routine: tasks made, done on time, late and missed, and routines nobody does."
    ),
    input=RangeInput,
)
def reports_routine_compliance(ctx: ToolContext, args: RangeInput) -> ToolResult:
    rows = kpis.routine_compliance(ctx.company, args.start, args.end, branch_ids=ctx.branch_ids)
    return ToolResult(rows=rows, as_of=ctx.now)
