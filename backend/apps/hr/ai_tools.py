"""Read-only AI tools of HR records (docs/PLAN-OWNER.md §8.3).

`hr_overview` answers with counts, names and dates only: never an ID, card or document number,
never HR's notes, never pay. The registry scrubs every string on top (phone numbers, long digit
runs, usernames).
"""

from datetime import timedelta

from django.utils import translation
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool
from apps.hr import bot_messages, overview, queries
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


class HRCoverageInput(BaseModel):
    days: int = Field(
        7, ge=1, le=31, description="How many days of the roster to check, from today."
    )
    branch_id: int | None = Field(
        None, description="Only this pharmacy (a branch id); every pharmacy when empty."
    )


@ai_tool(
    "hr_coverage",
    domain="hr",
    perm=Perm.HR_VIEW,
    label=_(
        "Pharmacist coverage: whether a qualified pharmacist is on the roster for every hour each "
        "pharmacy is open in the coming days (the gaps with their times), pharmacies with no "
        "qualified pharmacist checked in right now, tills opened by someone who isn't qualified, "
        "and the pharmacists who don't count today and why"
    ),
    input=HRCoverageInput,
    feature="hr",
)
def hr_coverage(ctx: ToolContext, args: HRCoverageInput) -> ToolResult:
    from apps.hr import coverage

    company = ctx.company
    branch_ids = ctx.branch_ids
    if args.branch_id is not None:
        if branch_ids is not None and args.branch_id not in branch_ids:
            raise ToolNotFound
        branch_ids = [args.branch_id]
    branches = {b.pk: b for b in coverage.pharmacies(company, branch_ids=branch_ids)}
    if args.branch_id is not None and args.branch_id not in branches:
        raise ToolNotFound
    day = queries.today(company, ctx.now)
    state = coverage.state(company)
    found = coverage.plan(company, day, day + timedelta(days=args.days - 1), branch_ids=branch_ids)
    rows = []
    for gap in coverage.upcoming(company, ctx.now, args.days, branch_ids=branch_ids):
        rows.append(
            {
                "id": f"gap:{gap.branch_id}:{gap.start.isoformat()}",
                "type": "roster_gap",
                "branch": branches[gap.branch_id].name,
                "start": gap.start.isoformat(),
                "end": gap.end.isoformat(),
                "hours": round(gap.minutes / 60, 1),
                "qualified_planned": gap.have,
                "needed": gap.need,
            }
        )
    for gap in coverage.live(company, ctx.now):
        if gap.branch_id in branches:
            rows.append(
                {
                    "id": f"now:{gap.branch_id}",
                    "type": "no_pharmacist_now",
                    "branch": branches[gap.branch_id].name,
                    "since": gap.since.isoformat(),
                    "qualified_checked_in": gap.have,
                    "needed": gap.need,
                }
            )
    with translation.override(ctx.language):
        for row in coverage.unqualified_sellers(company, day, branch_ids=branch_ids):
            rows.append(
                {
                    "id": f"till:{row['shift_id']}",
                    "type": "till_opened_by_unqualified",
                    "branch": row["branch"],
                    "cashier": row["cashier"],
                    "opened_at": row["opened_at"].isoformat(),
                    "why": str(bot_messages.reason_text(row["reason"])),
                }
            )
        if state != coverage.SETUP:
            for person in queries.qualified_staff(company, branch_ids=branch_ids, day=day):
                if person["qualified"]:
                    continue
                failing = [d["kind"] for d in person["documents"] if d["status"] != queries.OK]
                rows.append(
                    {
                        "id": f"person:{person['member'].pk}",
                        "type": "pharmacist_not_counted",
                        "member_id": person["member"].pk,
                        "name": str(person["member"]),
                        "position": person["position"],
                        "why": str(bot_messages.reason_text(person["reason"])),
                        "documents": [str(DocumentKind(kind).label) for kind in failing],
                    }
                )
    return ToolResult(
        rows=rows,
        data={
            "state": state,
            "today": day.isoformat(),
            "days": args.days,
            "qualified_needed": found.need,
            "pharmacies": [
                {
                    "id": row.branch.pk,
                    "name": row.branch.name,
                    "open_24h": row.branch.open_24h,
                    "opens_at": _clock(row.branch.opens_at),
                    "closes_at": _clock(row.branch.closes_at),
                    "roster_published_until": row.last_day.isoformat() if row.last_day else None,
                }
                for row in found.branches
            ],
        },
        as_of=ctx.now,
    )


def _clock(value) -> str | None:
    return value.strftime("%H:%M") if value else None


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
