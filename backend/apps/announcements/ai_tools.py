"""Read-only AI tool about announcements (docs/PLAN-OWNER.md §8.3)."""

from datetime import date, timedelta

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.announcements import queries
from apps.members.permissions import Perm

MAX_DAYS = 366


class StatsInput(BaseModel):
    start: date = Field(description="First day, company time.")
    end: date = Field(description="Last day (inclusive).")


@ai_tool(
    "announcements_stats",
    domain="communication",
    perm=Perm.ANNOUNCE,
    label=_("Announcements sent in a period with how many people read each"),
    input=StatsInput,
)
def announcements_stats(ctx: ToolContext, args: StatsInput) -> ToolResult:
    start, end = sorted((args.start, args.end))
    end = min(end, start + timedelta(days=MAX_DAYS - 1))  # a year at most per question
    visible = set(queries.for_console(ctx.membership).values_list("pk", flat=True))
    rows = [row for row in queries.read_rates(ctx.company, start, end) if row["id"] in visible]
    return ToolResult(rows=rows, as_of=ctx.now)
