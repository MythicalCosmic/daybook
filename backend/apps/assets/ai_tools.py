"""Read-only AI tools of fixed assets (docs/PLAN-OWNER.md §8.3).

`assets_overview` answers what the company owns and what it costs a month, what needs upkeep and
what to plan for: counts, names, dates and amounts in the base currency. Values are finance, so
the tool needs finance.view and the "share finance" switch; never a serial or an inventory
person's details beyond the name the register shows.
"""

from datetime import timedelta

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.assets import posting, queries
from apps.members.permissions import Perm


class AssetsOverviewInput(BaseModel):
    days: int = Field(
        60,
        ge=1,
        le=365,
        description="How many days ahead to look for services, instrument checks, warranties "
        "and insurance.",
    )


@ai_tool(
    "assets_overview",
    domain="assets",
    perm=Perm.FINANCE_VIEW,
    label=_(
        "Fixed assets at a glance: how many, their cost and book value, this month's and this "
        "year's depreciation by category, upkeep coming up or overdue, replacements due in the "
        "next three years, repairs that approach a new one's price, money sitting idle"
    ),
    input=AssetsOverviewInput,
    feature="assets",
    switch="share_finance",
)
def assets_overview(ctx: ToolContext, args: AssetsOverviewInput) -> ToolResult:
    company = ctx.company
    today = posting.local_today(company)
    summary = queries.summary(company, branch_ids=ctx.branch_ids, today=today)
    report = queries.depreciation_report(company, branch_ids=ctx.branch_ids, year=today.year)
    plan = queries.planning(company, branch_ids=ctx.branch_ids, today=today)
    until = today + timedelta(days=args.days)
    rows = [
        {
            "id": item["asset"].pk,
            "type": item["what"],
            "name": f"{item['asset'].number} {item['asset'].name}",
            "branch": item["asset"].branch.name if item["asset"].branch_id else None,
            "date": item["day"].isoformat(),
            "days_left": (item["day"] - today).days,
            "overdue": item["overdue"],
        }
        for item in plan["upkeep"]
        if item["day"] <= until
    ]
    return ToolResult(
        rows=rows,
        data={
            "today": today.isoformat(),
            "assets": summary["count"],
            "cost": str(summary["cost"]),
            "book_value": str(summary["book"]),
            "depreciation_this_month": str(summary["this_month"]),
            "depreciation_this_year": str(report["total"]),
            "this_year_by_group": [
                {"name": group["name"], "total": str(group["total"])} for group in report["groups"]
            ],
            "fully_depreciated": summary["fully_depreciated"],
            "replacements_next_3_years": plan["quarters"],
            "replacement_total": str(plan["replacement_total"]),
            "repair_or_replace": [
                {
                    "id": item["asset"].pk,
                    "name": f"{item['asset'].number} {item['asset'].name}",
                    "repairs_12_months": str(item["repairs"]),
                    "new_one": str(item["replacement"]),
                    "share_percent": str(item["share"]),
                }
                for item in plan["repairs"]
            ],
            "idle_value": str(plan["idle_value"]),
        },
        currency=company.base_currency,
        as_of=ctx.now,
    )
