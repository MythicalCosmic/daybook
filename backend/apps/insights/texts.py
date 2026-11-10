"""The words of an insight: its title, a plain explanation with the numbers behind it, and what
to do, rendered from its kind and metrics in the active language (the reader's, or the
company's when the jobs store them). Plain sentences, no emoji: they go to Telegram as well.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.insights import display
from apps.insights.models import Insight

Kind = Insight.Kind


@dataclass(frozen=True)
class Texts:
    title: str
    explanation: str
    action: str


def render(kind: str, metrics: dict, *, branch: str = "", subject: str = "") -> Texts:
    """The texts of an insight of `kind`; an unknown kind gets a neutral title."""
    writer = WRITERS.get(kind)
    if writer is None:
        return Texts(title=subject or kind, explanation="", action="")
    return writer(metrics or {}, branch, subject)


def of(insight: Insight) -> Texts:
    return render(
        insight.kind,
        insight.metrics,
        branch=insight.branch.name if insight.branch_id else "",
        subject=insight.subject_label,
    )


def _money(metrics: dict, key: str) -> str:
    return display.money(metrics.get(key) or 0, metrics.get("currency") or "UZS")


def _causes(metrics: dict) -> str:
    causes = metrics.get("causes") or []
    parts = [
        _("%(title)s %(amount)s (%(date)s)")
        % {
            "title": cause["title"],
            "amount": display.money(cause["amount"], metrics.get("currency") or "UZS"),
            "date": display.day(cause["date"]),
        }
        for cause in causes[:3]
    ]
    if not parts:
        return ""
    return _("Biggest payments before it: %(list)s.") % {"list": "; ".join(parts)}


def _cash_low(metrics: dict, branch: str, subject: str) -> Texts:
    low = Decimal(metrics.get("value") or 0)
    below = metrics.get("below_zero_on")
    values = {
        "date": display.day(metrics.get("low_date") or metrics.get("to") or ""),
        "amount": _money(metrics, "value"),
        "buffer": _money(metrics, "threshold"),
        "short": _money(metrics, "short_by"),
        "now": _money(metrics, "baseline"),
    }
    if below:
        title = _("Cash runs out on %(date)s") % {"date": display.day(below)}
        first = _(
            "The forecast goes below zero on %(zero)s and reaches %(amount)s on %(date)s. "
            "Cash now: %(now)s."
        ) % {**values, "zero": display.day(below)}
    else:
        title = _("Cash drops to %(amount)s on %(date)s") % values
        first = (
            _(
                "On %(date)s the accounts hold %(amount)s, %(short)s less than your buffer of "
                "%(buffer)s. Cash now: %(now)s."
            )
            % values
        )
    causes = _causes(metrics)
    explanation = f"{first} {causes}".strip()
    if low < 0 or below:
        action = _(
            "Move a supplier payment to a later date, collect what customers owe, or put money "
            "in before %(date)s."
        ) % {"date": display.day(below or metrics.get("low_date"))}
    else:
        action = (
            _(
                "Plan the payments of that week: move one if you can, or collect what customers "
                "owe before %(date)s."
            )
            % values
        )
    return Texts(title, explanation, action)


def _branch_margin(metrics: dict, branch: str, subject: str) -> Texts:
    profit = Decimal(metrics.get("profit") or 0)
    values = {
        "branch": branch or subject,
        "margin": display.percent(metrics.get("value") or 0),
        "previous": display.percent(metrics.get("baseline") or 0),
        "profit": _money(metrics, "profit"),
        "profit_previous": _money(metrics, "profit_previous"),
        "revenue": _money(metrics, "revenue"),
        "revenue_previous": _money(metrics, "revenue_previous"),
    }
    if profit < 0:
        title = _("%(branch)s is losing money") % values
    else:
        title = _("%(branch)s: margin fell to %(margin)s%%") % values
    if metrics.get("period") == "last_month":
        first = (
            _(
                "Last month: profit %(profit)s, margin %(margin)s%%. The month before: profit "
                "%(profit_previous)s, margin %(previous)s%%. Revenue: %(revenue)s, was "
                "%(revenue_previous)s."
            )
            % values
        )
    else:
        first = (
            _(
                "This month so far: profit %(profit)s, margin %(margin)s%%. The same days last "
                "month: profit %(profit_previous)s, margin %(previous)s%%. Revenue: %(revenue)s, "
                "was %(revenue_previous)s."
            )
            % values
        )
    change = Decimal(metrics.get("revenue_change") or 0)
    if change <= -1:
        first = f"{first} " + _("Revenue fell by %(change)s%%.") % {
            "change": display.percent(abs(change))
        }
    grew = metrics.get("costs_up") or []
    if grew:
        parts = [
            _("%(name)s %(share)s%% (was %(previous)s%%)")
            % {
                "name": cost["name"],
                "share": display.percent(cost["share"]),
                "previous": display.percent(cost["share_previous"]),
            }
            for cost in grew[:2]
        ]
        first = f"{first} " + _("Costs that took a bigger share of revenue: %(list)s.") % {
            "list": "; ".join(parts)
        }
    action = _("Open the P&L of %(branch)s and check its sales and biggest costs.") % values
    return Texts(title, first, action)


def _expense_spike(metrics: dict, branch: str, subject: str) -> Texts:
    values = {
        "category": subject,
        "amount": _money(metrics, "value"),
        "average": _money(metrics, "baseline"),
        "ratio": display.ratio(metrics.get("ratio") or 0),
    }
    title = _("%(category)s: %(amount)s in 7 days") % values
    explanation = (
        _(
            "The last 7 days: %(amount)s. A usual week (the average of the 8 weeks before): "
            "%(average)s. That is %(ratio)s times as much."
        )
        % values
    )
    action = _("Check the %(category)s entries of the last week and who made them.") % values
    return Texts(title, explanation, action)


def _parties(metrics: dict) -> str:
    parties = metrics.get("parties") or []
    parts = [
        ngettext(
            "%(name)s %(amount)s, %(days)s day late",
            "%(name)s %(amount)s, %(days)s days late",
            party["days"],
        )
        % {
            "name": party["name"],
            "amount": display.money(party["amount"], metrics.get("currency") or "UZS"),
            "days": party["days"],
        }
        for party in parties[:3]
    ]
    return "; ".join(parts)


def _overdue_receivables(metrics: dict, branch: str, subject: str) -> Texts:
    values = {
        "amount": _money(metrics, "value"),
        "count": metrics.get("count") or 0,
        "days": metrics.get("oldest_days") or 0,
        "parties": _parties(metrics),
    }
    title = _("Customers are late with %(amount)s") % values
    explanation = (
        ngettext(
            "Overdue debts to you: %(count)s, the oldest %(days)s day late. Biggest: %(parties)s.",
            "Overdue debts to you: %(count)s, the oldest %(days)s days late. Biggest: %(parties)s.",
            values["days"],
        )
        % values
    )
    action = _("Call the customers who are late and agree on a date to pay.")
    return Texts(title, explanation, action)


def _overdue_payables(metrics: dict, branch: str, subject: str) -> Texts:
    values = {
        "amount": _money(metrics, "value"),
        "count": metrics.get("count") or 0,
        "days": metrics.get("oldest_days") or 0,
        "parties": _parties(metrics),
    }
    title = _("Supplier bills overdue: %(amount)s") % values
    explanation = (
        ngettext(
            "Overdue bills: %(count)s, the oldest %(days)s day late. Biggest: %(parties)s.",
            "Overdue bills: %(count)s, the oldest %(days)s days late. Biggest: %(parties)s.",
            values["days"],
        )
        % values
    )
    action = _("Pay them or agree on new dates with the suppliers before deliveries stop.")
    return Texts(title, explanation, action)


def _stock_build(metrics: dict, branch: str, subject: str) -> Texts:
    values = {
        "branch": branch,
        "stock": display.percent(metrics.get("stock_change") or 0),
        "sales": display.percent(abs(Decimal(metrics.get("sales_change") or 0))),
        "now": _money(metrics, "value"),
        "before": _money(metrics, "baseline"),
        "sales_now": _money(metrics, "sales"),
        "sales_before": _money(metrics, "sales_previous"),
    }
    if branch:
        title = _("%(branch)s: stock up %(stock)s%%, sales down %(sales)s%%") % values
    else:
        title = _("Stock up %(stock)s%%, sales down %(sales)s%%") % values
    explanation = (
        _(
            "Stock at cost: %(now)s, four weeks ago %(before)s. Sales of the last four weeks: "
            "%(sales_now)s, the four weeks before: %(sales_before)s."
        )
        % values
    )
    action = _("Order less of what sells slowly and check the slow movers and expiry dates.")
    return Texts(title, explanation, action)


def _staff_cost(metrics: dict, branch: str, subject: str) -> Texts:
    values = {
        "share": display.percent(metrics.get("value") or 0),
        "baseline": display.percent(metrics.get("baseline") or 0),
        "cost": _money(metrics, "staff_cost"),
        "revenue": _money(metrics, "revenue"),
        "month": metrics.get("month_label") or metrics.get("month") or "",
    }
    title = _("Staff costs: %(share)s%% of revenue") % values
    explanation = (
        _(
            "%(month)s: salaries and payroll taxes %(cost)s, revenue %(revenue)s. That is "
            "%(share)s%%, against %(baseline)s%% on average in the months before."
        )
        % values
    )
    action = _("Compare hours and shifts with sales, and look at overtime and new hires.")
    return Texts(title, explanation, action)


WRITERS = {
    Kind.CASH_LOW: _cash_low,
    Kind.BRANCH_MARGIN: _branch_margin,
    Kind.EXPENSE_SPIKE: _expense_spike,
    Kind.OVERDUE_RECEIVABLES: _overdue_receivables,
    Kind.OVERDUE_PAYABLES: _overdue_payables,
    Kind.STOCK_BUILD: _stock_build,
    Kind.STAFF_COST: _staff_cost,
}
