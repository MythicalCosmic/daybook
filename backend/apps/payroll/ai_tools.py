"""Read-only AI tools of payroll.

Each wraps a function of `queries.py` and registers with `apps.ai.tools.registry.ai_tool`.
Salaries reach the assistant only for people who hold `payroll.view` and only while the owner
lets it read them (the `share_salaries` data switch, off by default).
"""

import re
from datetime import date

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field, field_validator

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.members.permissions import Perm
from apps.payroll import periods, queries
from apps.payroll.models import Payslip

MONTH = re.compile(r"^\d{4}-\d{2}$")


class PayrollSummaryInput(BaseModel):
    month: str | None = Field(
        default=None,
        description="The month as YYYY-MM; the last finished month when left out.",
    )

    @field_validator("month")
    @classmethod
    def check_month(cls, value):
        if value is not None and not MONTH.match(value):
            raise ValueError("write the month as YYYY-MM")
        return value


def _text(value) -> str:
    return f"{value:.2f}"


@ai_tool(
    "payroll_summary",
    domain="payroll",
    perm=Perm.PAYROLL_VIEW,
    label=_(
        "Payroll of a month: status, how many people, gross, deductions and net pay, bonuses, "
        "fines and advances repaid, and each person's gross and net (people you see only); "
        "this month's projection when the month has no run yet"
    ),
    input=PayrollSummaryInput,
    feature="payroll",
    switch="share_salaries",
)
def payroll_summary(ctx: ToolContext, args: PayrollSummaryInput) -> ToolResult:
    today = periods.today(ctx.company, ctx.now)
    if args.month:
        period = date(int(args.month[:4]), int(args.month[5:7]), 1)
    else:
        period = periods.previous_period(today)
    summary = queries.run_summary(ctx.company, period, branch_ids=ctx.branch_ids)
    if summary is None:
        projected = queries.projected_cost(ctx.company, period, branch_ids=ctx.branch_ids)
        return ToolResult(
            rows=[],
            data={
                "month": f"{period:%Y-%m}",
                "status": "no_run",
                "projection": {
                    "people": projected["people"],
                    "gross": _text(projected["gross"]),
                    "net": _text(projected["net"]),
                },
            },
            currency=projected["currency"],
            as_of=ctx.now,
        )
    payslips = queries.people_scope(
        Payslip.objects.filter(run_id=summary["run"]).select_related(
            "membership__user", "membership__position"
        ),
        ctx.branch_ids,
    ).order_by("-net", "pk")
    rows = [
        {
            "id": payslip.membership_id,
            "name": payslip.membership.full_name or str(payslip.membership.user),
            "position": payslip.membership.position.name if payslip.membership.position_id else "",
            "gross": _text(payslip.gross),
            "deductions": _text(payslip.deductions),
            "net": _text(payslip.net),
            "status": payslip.status,
        }
        for payslip in payslips
    ]
    return ToolResult(
        rows=rows,
        data={
            "month": f"{period:%Y-%m}",
            "status": summary["status"],
            "people": summary["people"],
            "gross": _text(summary["gross"]),
            "deductions": _text(summary["deductions"]),
            "net": _text(summary["net"]),
            "bonuses": _text(summary["bonuses"]),
            "fines": _text(summary["fines"]),
            "advances_repaid": _text(summary["advances"]),
            "paid_payslips": summary["paid"],
        },
        currency=summary["currency"],
        as_of=ctx.now,
    )
