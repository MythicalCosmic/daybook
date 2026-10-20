"""Read-only AI tools of the company calendar.

Each wraps a function of `queries.py` and registers with `apps.ai.tools.registry.ai_tool`.
"""

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.agenda import queries
from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.members.permissions import Perm


class UpcomingInput(BaseModel):
    days: int = Field(default=7, ge=1, le=31, description="How many days ahead to look.")


@ai_tool(
    "agenda_upcoming",
    domain="calendar",
    perm=Perm.DASHBOARD_ACCESS,
    label=_("Company events (meetings, trainings, inventories) in the next days"),
    input=UpcomingInput,
)
def agenda_upcoming(ctx: ToolContext, args: UpcomingInput) -> ToolResult:
    zone = queries.tz_of(ctx.company)
    rows = []
    for occurrence in queries.upcoming(ctx.membership, now=ctx.now, days=args.days):
        event = occurrence.event
        rows.append(
            {
                "id": occurrence.key,
                "title": event.title,
                "kind": event.kind,
                "all_day": event.all_day,
                "start": timezone.localtime(occurrence.start, zone).isoformat(),
                "end": timezone.localtime(occurrence.end, zone).isoformat()
                if occurrence.end
                else None,
                "place": event.place,
                "attendees": event.invites.count(),
            }
        )
    return ToolResult(rows=rows, as_of=ctx.now)
