"""Read-only AI tools of briefings: the advisor's own two (apps.ai.agents.advisor).

Each wraps a function of `queries.py` and registers with `apps.ai.tools.registry.ai_tool`.
Their domain is "advisor": "Ask the advisor" offers them beside the finance, sales, stock and
people tools (the registry names tools after their app: `briefings_…`).

    briefings_advisor_facts      the latest business review of the asker's own scope: its words
                                 and its facts (what it would say now when none is written yet)
    briefings_advisor_scenario   what if a monthly cost or income changes from a date: the cash
                                 forecast's lowest point and how long the money lasts, before
                                 and after (apps.briefings.scenario)
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.agents.advisor import for_prompt
from apps.ai.tools.registry import ToolContext, ToolResult, ai_tool
from apps.briefings import facts, periods, queries, scenario, scope
from apps.companies.models import Feature
from apps.finance.queries import local_today
from apps.members.permissions import Perm

DOMAIN = "advisor"
# Sections and signals that are money: left out when the owner keeps money from the AI
# (the "share finance" switch of the AI settings off).
MONEY_SECTIONS = ("finance", "sales", "stock")
MONEY_SIGNALS = (
    "revenue",
    "gross_margin",
    "profit",
    "payroll_share",
    "branch:",
    "expense:",
    "cash:",
    "debts:",
    "sales:",
    "stock:",
)


class FactsInput(BaseModel):
    kind: Literal["weekly", "monthly"] = Field(
        "weekly", description="The weekly review (default) or the monthly one."
    )


def _without_money(found: dict) -> dict:
    kept = {key: value for key, value in found.items() if key not in MONEY_SECTIONS}
    kept["signals"] = [
        signal for signal in found.get("signals", []) if not signal["key"].startswith(MONEY_SIGNALS)
    ]
    return kept


@ai_tool(
    "briefings_advisor_facts",
    domain=DOMAIN,
    perm=Perm.REPORTS_VIEW,
    label=_(
        "The latest business review the advisor wrote for the asker: its numbers (revenue, "
        "margins and profit per pharmacy against the period before and the usual level, cash "
        "and the forecast's lowest point, expenses that jumped, overdue debts, slow stock, "
        "lateness), what went well and wrong, and its suggestions"
    ),
    input=FactsInput,
)
def briefings_advisor_facts(ctx: ToolContext, args: FactsInput) -> ToolResult:
    member = ctx.membership
    briefing = queries.latest(member, args.kind)
    if briefing is not None:
        found, review = briefing.facts or {}, queries.review_lines(briefing)
    else:
        reader = scope.of(member)
        if not reader.has_data:
            return ToolResult(data={"review": None, "facts": None}, as_of=ctx.now)
        today = local_today(ctx.company, ctx.now)
        found = facts.build(ctx.company, periods.latest(args.kind, today), reader, today=today)
        review = None
    money = "share_finance" in ctx.switches
    if not money:
        found, review = _without_money(found), None
    return ToolResult(
        data={"review": review, "facts": for_prompt(found), "written": briefing is not None},
        currency=ctx.company.base_currency if money else None,
        as_of=ctx.now,
    )


class ScenarioInput(BaseModel):
    monthly_change: float = Field(
        ...,
        ge=-1e13,
        le=1e13,
        description=(
            "Money per month in the company's currency: negative for a new monthly cost (the "
            "rent and salaries of a second pharmacy), positive for new monthly income."
        ),
    )
    start: date | None = Field(
        None, description="The first day of the change, YYYY-MM-DD. Default: today."
    )
    one_off: float = Field(
        0,
        ge=-1e13,
        le=1e13,
        description=(
            "A one-time amount on the start day: negative for an outlay (fit-out, a deposit), "
            "positive for money coming in."
        ),
    )
    days: int = Field(90, ge=30, le=120, description="How far ahead to look, in days.")
    label: str = Field("", max_length=80, description="What the change is, in a few words.")


@ai_tool(
    "briefings_advisor_scenario",
    domain=DOMAIN,
    perm=Perm.FINANCE_VIEW,
    label=_(
        "What if: the cash forecast with a monthly cost or income added from a date (and a "
        "one-time outlay): the lowest balance, the first day below zero and how many days the "
        "money lasts, before and after"
    ),
    input=ScenarioInput,
    feature=Feature.FINANCE,
    switch="share_finance",
)
def briefings_advisor_scenario(ctx: ToolContext, args: ScenarioInput) -> ToolResult:
    today = local_today(ctx.company, ctx.now)
    result = scenario.what_if(
        ctx.company,
        branch_ids=ctx.branch_ids,
        today=today,
        monthly=Decimal(str(round(args.monthly_change, 2))),
        start=args.start,
        one_off=Decimal(str(round(args.one_off, 2))),
        days=args.days,
    )
    if args.label:
        result["label"] = args.label
    return ToolResult(data=result, currency=result["currency"], as_of=ctx.now)
