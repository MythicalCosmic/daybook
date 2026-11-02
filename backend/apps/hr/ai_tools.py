"""Read-only AI tools of HR records (docs/PLAN-OWNER.md §8.3).

`hr_overview` answers with counts, names and dates only: never an ID, card or document number,
never HR's notes, never pay. The registry scrubs every string on top (phone numbers, long digit
runs, usernames).
"""

from django.utils import translation
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.hr import overview, queries
from apps.hr.models import DocumentKind
from apps.members.permissions import Perm


class HROverviewInput(BaseModel):
    days: int = Field(
        30,
        ge=1,
        le=180,
        description="How many days ahead to look for documents, contracts and probation that end.",
    )


@ai_tool(
    "hr_overview",
    domain="hr",
    perm=Perm.HR_VIEW,
    label=_(
        "HR at a glance: headcount and its trend, documents that expire or have expired, "
        "contracts and probation that end, missing required documents, birthdays and work "
        "anniversaries of the coming week"
    ),
    input=HROverviewInput,
    feature="hr",
)
def hr_overview(ctx: ToolContext, args: HROverviewInput) -> ToolResult:
    company = ctx.company
    day = queries.today(company, ctx.now)
    facts = overview.build(company, ctx.membership, branch_ids=ctx.branch_ids, day=day)
    rows = []
    with translation.override(ctx.language):
        documents = queries.expiring_documents(
            company, branch_ids=ctx.branch_ids, day=day, within=args.days
        )
        for document in documents:
            rows.append(
                {
                    "id": document.pk,
                    "type": "document",
                    "member_id": document.membership_id,
                    "name": str(document.membership),
                    "what": str(DocumentKind(document.kind).label),
                    "date": document.expires_on.isoformat(),
                    "days_left": (document.expires_on - day).days,
                }
            )
    for contract in queries.ending_contracts(
        company, branch_ids=ctx.branch_ids, day=day, within=args.days
    ):
        rows.append(_contract_row(contract, "contract_end", contract.ends_on, day))
    for contract in queries.probation_endings(
        company, branch_ids=ctx.branch_ids, day=day, within=args.days
    ):
        rows.append(_contract_row(contract, "probation_end", contract.probation_until, day))
    rows.sort(key=lambda row: (row["date"], row["type"], row["name"]))
    week = {
        "birthdays": [
            {"member_id": row["member"].pk, "name": str(row["member"]), "date": row["date"]}
            for row in facts["birthdays"]
        ],
        "anniversaries": [
            {
                "member_id": row["member"].pk,
                "name": str(row["member"]),
                "date": row["date"],
                "years": row["years"],
            }
            for row in facts["anniversaries"]
        ],
    }
    return ToolResult(
        rows=rows,
        data={
            "today": day.isoformat(),
            "looked_ahead_days": args.days,
            "headcount": facts["headcount"],
            "headcount_by_month": [
                {"month": point["month"], "headcount": point["headcount"]}
                for point in facts["trend"]
            ],
            "documents": facts["documents"],
            "contracts": facts["contracts"],
            "this_week": _iso(week),
        },
        as_of=ctx.now,
    )


def _contract_row(contract, kind: str, when, day) -> dict:
    return {
        "id": contract.pk,
        "type": kind,
        "member_id": contract.membership_id,
        "name": str(contract.membership),
        "what": contract.kind,
        "date": when.isoformat(),
        "days_left": (when - day).days,
    }


def _iso(value):
    if isinstance(value, dict):
        return {key: _iso(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_iso(item) for item in value]
    return value.isoformat() if hasattr(value, "isoformat") else value
