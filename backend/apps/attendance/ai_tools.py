"""Read-only AI tools of attendance.

Each wraps a function of `queries.py` and registers with `apps.ai.tools.registry.ai_tool`.
"""

from datetime import date, timedelta

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field, model_validator

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.attendance import clock, queries
from apps.members.models import Membership
from apps.members.permissions import Perm


class AttendanceSummaryInput(BaseModel):
    start: date = Field(description="First day, company-local, YYYY-MM-DD.")
    end: date = Field(description="Last day, inclusive.")

    @model_validator(mode="after")
    def check_span(self):
        if self.end < self.start:
            raise ValueError("end is before start")
        if (self.end - self.start).days > 366:
            raise ValueError("pick at most a year")
        return self


@ai_tool(
    "attendance_summary",
    domain="attendance",
    perm=Perm.ATTENDANCE_VIEW,
    label=_(
        "Attendance between two days: totals (present, late, absent, on-time %, worked hours) "
        "and per person scheduled, attended, absent and late days with worked hours"
    ),
    input=AttendanceSummaryInput,
    feature="attendance",
)
def attendance_summary(ctx: ToolContext, args: AttendanceSummaryInput) -> ToolResult:
    today = clock.today(ctx.company, ctx.now)
    end = min(args.end, today + timedelta(days=31))
    totals = queries.summary(ctx.company, args.start, end, branch_ids=ctx.branch_ids)["totals"]
    people = queries.period_summary(ctx.company, args.start, end, branch_ids=ctx.branch_ids)
    names = dict(
        (member.pk, member.full_name or str(member.user))
        for member in Membership.objects.filter(pk__in=list(people)).select_related("user")
    )
    rows = [
        {
            "id": member_id,
            "name": names.get(member_id, ""),
            "scheduled_days": row.scheduled_days,
            "attended_days": row.attended_days,
            "absent_days": row.absent_days,
            "leave_days": row.leave_days,
            "late_arrivals": row.late_arrivals,
            "late_minutes": row.late_minutes,
            "worked_hours": round(row.worked_minutes / 60, 1),
            "approved_overtime_hours": round(row.approved_overtime_minutes / 60, 1),
        }
        for member_id, row in people.items()
        if row.has_schedule or row.attended_days
    ]
    rows.sort(key=lambda row: (-row["absent_days"], -row["late_arrivals"], row["name"]))
    return ToolResult(
        rows=rows,
        data={"from": args.start.isoformat(), "to": end.isoformat(), **totals},
        as_of=ctx.now,
    )
