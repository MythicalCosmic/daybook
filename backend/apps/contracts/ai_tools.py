"""Read-only AI tools of business contracts (docs/PLAN-OWNER.md §8.3).

`contracts_overview` answers what the business has signed and what it costs: the contracts in
the caller's branch scope with who with, their dates (the end, the notice deadline of an
auto-renewing one), the money per period and a month, what needs a look soon, and the month's
total in the base currency. Rent and payments are finance, so the tool needs finance.view and
the "share finance" switch. It never returns file links or notes.
"""

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.contracts import conf, queries, services
from apps.contracts.models import BusinessContract
from apps.members.permissions import Perm


class ContractsOverviewInput(BaseModel):
    kind: str | None = Field(
        None,
        description="Only this kind: lease, supply, service, licence, insurance or other.",
    )
    ended: bool = Field(False, description="Include contracts that ended or were terminated.")


@ai_tool(
    "contracts_overview",
    domain="finance",
    perm=Perm.FINANCE_VIEW,
    label=_(
        "Business contracts: leases, suppliers, services, licences and insurance, who with, "
        "until when, the notice deadlines of those that renew by themselves, what they cost a "
        "month, and which end soon"
    ),
    input=ContractsOverviewInput,
    switch="share_finance",
)
def contracts_overview(ctx: ToolContext, args: ContractsOverviewInput) -> ToolResult:
    company = ctx.company
    today = services.local_today(company)
    settings = conf.get_settings(company)
    rows = queries.scoped(company, branch_ids=ctx.branch_ids).select_related(
        "branch", "counterparty"
    )
    if args.kind in BusinessContract.Kind.values:
        rows = rows.filter(kind=args.kind)
    if not args.ended:
        rows = rows.exclude(
            status__in=(BusinessContract.Status.ENDED, BusinessContract.Status.TERMINATED)
        )
    found = []
    for contract in rows.order_by("ends_on", "title", "pk")[:200]:
        found.append(
            {
                "id": contract.pk,
                "title": contract.title,
                "kind": contract.kind,
                "party": contract.counterparty.name if contract.counterparty_id else None,
                "branch": contract.branch.name if contract.branch_id else None,
                "status": contract.status,
                "starts_on": contract.starts_on.isoformat() if contract.starts_on else None,
                "ends_on": contract.ends_on.isoformat() if contract.ends_on else None,
                "renews_by_itself": contract.auto_renews,
                "notice_deadline": contract.notice_deadline.isoformat()
                if contract.notice_deadline
                else None,
                "amount": str(contract.amount) if contract.amount is not None else None,
                "currency": contract.currency,
                "period": contract.period,
                "needs_a_look": services.needs_attention(contract, today, settings),
                "in_cash_forecast": contract.in_forecast,
            }
        )
    summary = queries.summary(company, branch_ids=ctx.branch_ids, today=today)
    return ToolResult(
        rows=found,
        data={
            "today": today.isoformat(),
            "in_force": summary["in_force"],
            "ending_soon": summary["ending_soon"],
            "renewals_to_decide": summary["notice_due"],
            "monthly_cost": str(summary["monthly_cost"]),
            "warning_days": settings.remind_days,
        },
        currency=company.base_currency,
        as_of=ctx.now,
    )
