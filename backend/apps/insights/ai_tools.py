"""Read-only AI tools of insights (docs/PLAN-OWNER.md §11.5: `insights_open`).

Each wraps a function of `queries.py` and registers with `apps.ai.tools.registry.ai_tool`. The
asker sees only the insights their own permissions and branch scope allow (`access`).
"""

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.insights import access, queries
from apps.members.permissions import Perm


class InsightsOpenInput(BaseModel):
    limit: int = Field(10, ge=1, le=30, description="How many, urgent first.")


@ai_tool(
    "insights_open",
    domain="reports",
    perm=Perm.REPORTS_VIEW,
    label=_("What the checks noticed: open insights with their numbers"),
    input=InsightsOpenInput,
)
def insights_open(ctx: ToolContext, args: InsightsOpenInput) -> ToolResult:
    rows = queries.open_for(
        ctx.company,
        ctx.branch_ids,
        domains=access.domains_for(ctx.membership),
        limit=args.limit,
    )
    return ToolResult(
        rows=[
            {
                "id": row["id"],
                "kind": row["kind"],
                "severity": row["severity"],
                "status": row["status"],
                "branch": row["branch"]["name"] if row["branch"] else None,
                "title": row["title"],
                "explanation": row["explanation"],
                "suggested_action": row["suggested_action"],
                "metrics": row["metrics"],
                "detected_at": row["detected_at"],
            }
            for row in rows
        ],
        currency=ctx.company.base_currency,
    )
