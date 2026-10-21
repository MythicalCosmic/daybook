"""Read-only AI tools of sales and cash.

Each wraps a function of `queries.py` and registers with `apps.ai.tools.registry.ai_tool`. Every
query runs in `ctx.company` and `ctx.branch_ids` (§2.6), never with ids from the model alone;
money stays a string and the runner scrubs every text.
"""

from datetime import date, timedelta
from typing import Literal

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field, model_validator

from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool
from apps.members.permissions import Perm
from apps.sales import queries

MAX_DAYS = 366


class RangeInput(BaseModel):
    start: date = Field(description="First business day, YYYY-MM-DD (inclusive).")
    end: date = Field(description="Last business day, YYYY-MM-DD (inclusive).")
    branch_id: int | None = Field(default=None, description="One branch only (optional).")

    @model_validator(mode="after")
    def check_range(self):
        if self.end < self.start:
            raise ValueError("end is before start")
        if (self.end - self.start).days >= MAX_DAYS:
            raise ValueError("at most one year")
        return self


class SummaryInput(RangeInput):
    group_by: Literal[
        "day", "week", "month", "branch", "cashier", "method", "hour", "weekday_hour"
    ] = Field(
        default="day",
        description="day/week/month: totals over time; branch/cashier/method: a breakdown; "
        "hour/weekday_hour: when sales happen.",
    )
    compare_previous: bool = Field(
        default=False, description="Also give the same number of days just before."
    )


def _branches(ctx: ToolContext, branch_id: int | None) -> list[int] | None:
    if branch_id is None:
        return ctx.branch_ids
    if ctx.branch_ids is not None and branch_id not in ctx.branch_ids:
        raise ToolNotFound
    from apps.companies.models import Branch

    if not Branch.objects.filter(company=ctx.company, pk=branch_id).exists():
        raise ToolNotFound
    return [branch_id]


@ai_tool(
    "sales_summary",
    domain="sales",
    perm=Perm.SALES_VIEW,
    label=_(
        "Sales for a range of days: net sales, receipts, average check and cash share, with a "
        "series over time or a breakdown by branch, cashier, payment method or hour."
    ),
    input=SummaryInput,
    feature="sales",
    switch="share_finance",
)
def sales_summary(ctx: ToolContext, args: SummaryInput) -> ToolResult:
    branch_ids = _branches(ctx, args.branch_id)
    compare = None
    if args.compare_previous:
        span = args.end - args.start + timedelta(days=1)
        compare = (args.start - span, args.end - span)
    data = queries.summary(
        ctx.company, args.start, args.end, args.group_by, branch_ids=branch_ids, compare=compare
    )
    rows = []
    for index, point in enumerate(data["series"] if not data["breakdown"] else data["breakdown"]):
        row = dict(point)
        row.setdefault("id", row.get("key") or row.get("date") or index)
        row.pop("methods", None)
        rows.append(row)
    summary = {key: data[key] for key in ("range", "compare", "totals", "previous")}
    return ToolResult(rows=rows, data=summary, currency=data["currency"], as_of=ctx.now)


@ai_tool(
    "sales_cashier_scorecard",
    domain="sales",
    perm=Perm.SALES_VIEW,
    label=_(
        "Each cashier's shifts, sales, average check, how often their cash count matched, "
        "shortages and surpluses, late openings and verification for a range of days."
    ),
    input=RangeInput,
    feature="sales",
    switch="share_finance",
)
def sales_cashier_scorecard(ctx: ToolContext, args: RangeInput) -> ToolResult:
    branch_ids = _branches(ctx, args.branch_id)
    rows = []
    for row in queries.cashier_scorecard(ctx.company, args.start, args.end, branch_ids=branch_ids):
        member = row.pop("member")
        rows.append({"id": member["id"], "name": member["name"], **row})
    return ToolResult(rows=rows, currency=ctx.company.base_currency, as_of=ctx.now)
