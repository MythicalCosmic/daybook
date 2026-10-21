"""Read-only AI tools of the finance ledger (docs/PLAN-OWNER.md §8.3).

Each wraps `queries.py`, applies the asker's branch scope (`ctx.branch_ids`) and needs
`finance.view`, the finance module and the `share_finance` data switch. Per-person salary
detail (salaries, advances, reimbursements) is shown only when the asker holds `payroll.view`
and the company shares salaries with the AI (`share_salaries`); otherwise those rows keep their
amount and category and lose the person and the description.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.finance import access, queries
from apps.finance.models import Debt
from apps.members.permissions import Perm

MAX_DAYS = 400


def _today(ctx: ToolContext) -> date:
    return queries.local_today(ctx.company, ctx.now)


def _salary_detail(ctx: ToolContext) -> bool:
    return access.sees_salary_detail(ctx.membership) and "share_salaries" in ctx.switches


def _range(ctx: ToolContext, start: date | None, end: date | None) -> tuple[date, date]:
    today = _today(ctx)
    end = min(end or today, today)
    start = start or end.replace(day=1)
    if start > end:
        start, end = end, start
    return max(start, end - timedelta(days=MAX_DAYS)), end


class FinanceSummaryInput(BaseModel):
    start: date | None = Field(None, description="First day (company-local). Default: this month.")
    end: date | None = Field(None, description="Last day. Default: today.")


@ai_tool(
    "finance_summary",
    domain="finance",
    perm=Perm.FINANCE_VIEW,
    label=_("Income, expenses, profit, cash now and money owed, for a period"),
    input=FinanceSummaryInput,
    feature="finance",
    switch="share_finance",
)
def finance_summary(ctx: ToolContext, args: FinanceSummaryInput) -> ToolResult:
    start, end = _range(ctx, args.start, args.end)
    today = _today(ctx)
    pnl = queries.totals(ctx.company, start, end, branch_ids=ctx.branch_ids)
    cash = queries.cash_position(ctx.company, None, branch_ids=ctx.branch_ids, today=today)
    owed = queries.debt_totals(ctx.company, branch_ids=ctx.branch_ids, today=today)
    top = queries.pnl(ctx.company, start, end, "month", branch_ids=ctx.branch_ids)["expense"][
        "nodes"
    ][:5]
    return ToolResult(
        data={
            "from": start.isoformat(),
            "to": end.isoformat(),
            "income": pnl["income"],
            "expenses": pnl["expense"],
            "profit": pnl["profit"],
            "cash_now": cash["total"],
            "cash_rate_stale": cash["rate"]["stale"],
            "owed_to_us": owed[Debt.Direction.RECEIVABLE]["total"],
            "owed_to_us_overdue": owed[Debt.Direction.RECEIVABLE]["overdue"],
            "we_owe": owed[Debt.Direction.PAYABLE]["total"],
            "we_owe_overdue": owed[Debt.Direction.PAYABLE]["overdue"],
            "top_expense_categories": [
                {"category": node["name"], "amount": node["total"]} for node in top
            ],
        },
        currency=ctx.company.base_currency,
    )


class FinanceTransactionsInput(BaseModel):
    start: date | None = None
    end: date | None = None
    kind: Literal["income", "expense", "transfer", "owner", "debt_payment"] | None = None
    text: str | None = Field(
        None, max_length=60, description="Words in the description, party or category."
    )
    min_amount: Decimal | None = Field(
        None, ge=0, description="Smallest amount in the base currency."
    )
    limit: int = Field(30, ge=1, le=50)


@ai_tool(
    "finance_transactions",
    domain="finance",
    perm=Perm.FINANCE_VIEW,
    label=_("Ledger entries: income, expenses and other money movements"),
    input=FinanceTransactionsInput,
    feature="finance",
    switch="share_finance",
)
def finance_transactions(ctx: ToolContext, args: FinanceTransactionsInput) -> ToolResult:
    start, end = _range(ctx, args.start, args.end)
    detail = _salary_detail(ctx)
    filters = {
        "from": start,
        "to": end,
        "status": ["posted"],
        "kind": [args.kind] if args.kind else [],
        "q": args.text or "",
        "min": args.min_amount,
        "mask_sensitive": not detail,
    }
    rows = queries.transactions(ctx.company, filters, args.limit, branch_ids=ctx.branch_ids)
    out = []
    for row in rows:
        hidden = access.is_sensitive_row(row) and not detail
        out.append(
            {
                "id": row.pk,
                "date": row.occurred_on.isoformat(),
                "kind": row.kind,
                "amount": row.amount,
                "currency": row.currency,
                "base_amount": row.base_amount,
                "category": row.category.name if row.category_id else None,
                "account": row.account.name if row.account_id else None,
                "counterparty": None
                if hidden or not row.counterparty_id
                else row.counterparty.name,
                "person": None if hidden or not row.membership_id else str(row.membership),
                "description": "" if hidden else row.description,
                "link": f"[#{row.pk}](txn:{row.pk})",
            }
        )
    return ToolResult(rows=out, currency=ctx.company.base_currency)


class FinanceCashPositionInput(BaseModel):
    on: date | None = Field(None, description="End of this day. Default: now.")


@ai_tool(
    "finance_cash_position",
    domain="finance",
    perm=Perm.FINANCE_VIEW,
    label=_("Money on every account (cash desks, bank, cards, safes) and the total"),
    input=FinanceCashPositionInput,
    feature="finance",
    switch="share_finance",
)
def finance_cash_position(ctx: ToolContext, args: FinanceCashPositionInput) -> ToolResult:
    today = _today(ctx)
    on = min(args.on, today) if args.on else None
    position = queries.cash_position(ctx.company, on, branch_ids=ctx.branch_ids, today=today)
    return ToolResult(
        rows=[
            {
                "id": account["id"],
                "account": account["name"],
                "kind": account["kind"],
                "currency": account["currency"],
                "balance": account["balance"],
                "base": account["base"],
            }
            for account in position["accounts"]
        ],
        data={
            "on": position["on"].isoformat(),
            "total": position["total"],
            "rate": position["rate"]["rate"],
            "rate_stale": position["rate"]["stale"],
        },
        currency=ctx.company.base_currency,
    )


class FinanceDebtsInput(BaseModel):
    direction: Literal["receivable", "payable"] | None = Field(
        None, description="receivable: owed to us; payable: we owe."
    )
    overdue_only: bool = False


@ai_tool(
    "finance_debts",
    domain="finance",
    perm=Perm.FINANCE_VIEW,
    label=_("Open debts (nasiya): who owes us, whom we owe, due dates and overdue days"),
    input=FinanceDebtsInput,
    feature="finance",
    switch="share_finance",
)
def finance_debts(ctx: ToolContext, args: FinanceDebtsInput) -> ToolResult:
    today = _today(ctx)
    detail = _salary_detail(ctx)
    debts = queries.debts(
        ctx.company,
        args.direction,
        branch_ids=ctx.branch_ids,
        overdue_only=args.overdue_only,
        today=today,
    ).select_related("counterparty", "membership", "company")
    rows = []
    for debt in debts[:200]:
        hidden = debt.kind in Debt.SENSITIVE_KINDS and not detail
        rows.append(
            {
                "id": debt.pk,
                "direction": debt.direction,
                "kind": debt.kind,
                "party": None if hidden else str(debt.counterparty or debt.membership),
                "currency": debt.currency,
                "outstanding": debt.amount - debt.paid,
                "base_outstanding": queries.book_value(debt, debt.amount - debt.paid),
                "issued_on": debt.issued_on.isoformat(),
                "due_on": debt.due_on.isoformat() if debt.due_on else None,
                "days_overdue": queries.days_overdue(debt, today),
            }
        )
    return ToolResult(rows=rows, total=debts.count(), currency=ctx.company.base_currency)
