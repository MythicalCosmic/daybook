"""Demo data of the tax calendar (v12): the demo's past deadlines are dealt with, the way an owner
keeping up would have done. A deadline whose payment the books hold (the social tax paid with the
salaries) is linked to that payment; one the books don't hold (income tax withheld, which the demo
books inside the salaries) is marked paid with its estimate. So the calendar opens with what is
coming, nothing falsely late. The bank loan and the distributors' terms are in `demo`.
"""

from datetime import date, timedelta
from decimal import Decimal

from apps.finance import taxes
from apps.members.models import Membership

# The order deadlines are matched to payments in: social tax first (it has its own payment row).
FIRST = ("social_tax", "vat", "profit", "turnover", "income_tax")
CATEGORY = {"social_tax": "payroll_taxes", "income_tax": "payroll_taxes"}


def mark_past_taxes(company, by: Membership, today: date) -> int:
    """Mark every deadline before today that is still open; returns how many."""
    calendar = taxes.calendar_view(company, today, months_back=2, months_ahead=0)
    late = [row for row in calendar["deadlines"] if row["status"] == "overdue"]
    late.sort(
        key=lambda row: (FIRST.index(row["rule"]) if row["rule"] in FIRST else 9, row["due_on"])
    )
    made = 0
    for row in late:
        deadline = taxes.find(company, row["rule"], row["period_start"])
        code = CATEGORY.get(row["rule"], "taxes")
        estimate = Decimal(row["estimate"] or 0)
        paid = sorted(
            (
                found
                for found in taxes.candidates(company, deadline)
                if found.occurred_on <= row["due_on"] + timedelta(days=3)
                and (_in(found, code) or (found.debt_id and found.debt.kind == "tax"))
            ),
            key=lambda found: abs(abs(found.base_amount) - estimate),
        )
        done_on = min(row["due_on"] - timedelta(days=2), today)
        if paid:
            payment = paid[0]
            taxes.mark(
                company,
                by=by,
                rule_key=row["rule"],
                period_start=row["period_start"],
                done_on=max(payment.occurred_on, row["period_start"]),
                transaction_row=payment,
            )
        else:
            taxes.mark(
                company,
                by=by,
                rule_key=row["rule"],
                period_start=row["period_start"],
                done_on=done_on,
                amount=row["estimate"] or None,
                note="Ish haqi bilan birga to‘langan" if row["rule"] == "income_tax" else "",
            )
        made += 1
    return made


def _in(row, code: str) -> bool:
    category = row.category
    if category is None:
        return False
    return code in (category.system_code, getattr(category.parent, "system_code", ""))
