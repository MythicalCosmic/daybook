"""Read-only AI tool about time off and holidays (docs/PLAN-OWNER.md §8.3)."""

from datetime import date, timedelta

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.members.permissions import Perm
from apps.timeoff import queries

MAX_DAYS = 366


class OverviewInput(BaseModel):
    start: date = Field(description="First day, company time.")
    end: date = Field(description="Last day (inclusive).")


@ai_tool(
    "timeoff_overview",
    domain="people",
    perm=Perm.TIME_OFF_APPROVE,
    label=_("Time off and holidays in a period: who is off when, and requests still waiting"),
    input=OverviewInput,
)
def timeoff_overview(ctx: ToolContext, args: OverviewInput) -> ToolResult:
    start, end = sorted((args.start, args.end))
    end = min(end, start + timedelta(days=MAX_DAYS - 1))  # a year at most per question
    people = queries.calendar(ctx.company, start, end, branch_ids=ctx.branch_ids)
    rows = [
        {
            "id": item["id"],
            "member_id": row["member"]["id"],
            "name": row["member"]["name"],
            "first_day": item["first_day"],
            "last_day": item["last_day"],
            "days": item["days"],
            "status": item["status"],
            "recorded_by_manager": item["recorded"],
        }
        for row in people
        for item in row["items"]
    ]
    holidays = [
        {"date": holiday.date.isoformat(), "name": holiday.name}
        for holiday in queries.holidays_between(ctx.company, start, end)
    ]
    return ToolResult(
        rows=rows,
        data={
            "holidays": holidays,
            "pending": sum(1 for row in rows if row["status"] == "pending"),
        },
        as_of=ctx.now,
    )
