"""Read-only AI tools of the people lifecycle (docs/PLAN-OWNER.md §8.3, §13.4).

`lifecycle_overview` answers with counts, names, kinds, categories and dates: never what a
record says, the person's explanation, the evidence, or a fine's amount.
"""

from django.utils import translation
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.hr import queries as hr_queries
from apps.lifecycle import queries
from apps.lifecycle.models import DisciplinaryRecord
from apps.members.permissions import Perm


class LifecycleOverviewInput(BaseModel):
    days: int = Field(
        180, ge=1, le=730, description="How many days back to count warnings and reprimands."
    )


@ai_tool(
    "lifecycle_overview",
    domain="hr",
    perm=Perm.HR_VIEW,
    label=_(
        "Discipline at a glance: warnings and reprimands given in a period by kind and "
        "category, those still counting, unacknowledged ones, and who is suspended until when"
    ),
    input=LifecycleOverviewInput,
    feature="hr",
)
def lifecycle_overview(ctx: ToolContext, args: LifecycleOverviewInput) -> ToolResult:
    day = hr_queries.today(ctx.company, ctx.now)
    facts = queries.overview(ctx.company, branch_ids=ctx.branch_ids, day=day, days=args.days)
    with translation.override(ctx.language):
        rows = [
            {
                "id": record.pk,
                "type": "record",
                "member_id": record.membership_id,
                "name": str(record.membership),
                "kind": str(DisciplinaryRecord.Kind(record.kind).label),
                "category": str(DisciplinaryRecord.Category(record.category).label),
                "issued_on": record.issued_on.isoformat(),
                "counts_until": record.expires_on.isoformat() if record.expires_on else None,
                "acknowledged": record.acknowledged_at is not None,
                "explained": bool(record.employee_response),
                "fine_proposed": bool(record.fine_id),
            }
            for record in facts["recent"]
        ]
    rows += [
        {
            "id": row["member"].pk,
            "type": "suspension",
            "member_id": row["member"].pk,
            "name": str(row["member"]),
            "since": row["since"].date().isoformat() if row["since"] else None,
            "until": row["until"].isoformat() if row["until"] else None,
        }
        for row in facts["suspended"]
    ]
    return ToolResult(
        rows=rows,
        data={
            "today": day.isoformat(),
            "looked_back_days": args.days,
            "given": len(facts["recent"]),
            "by_kind": facts["by_kind"],
            "by_category": facts["by_category"],
            "still_counting": facts["active"],
            "not_acknowledged": facts["unacknowledged"],
            "explained": facts["explained"],
            "with_fine": facts["with_fine"],
            "suspended_now": len(facts["suspended"]),
        },
        as_of=ctx.now,
    )
