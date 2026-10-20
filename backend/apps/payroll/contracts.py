"""What payroll promises other apps (docs/PLAN-OWNER.md §13.3).

Projects (package T) price logged time with `cost_rate`; package H fills it from the
member's compensation. Until then no rate is known, and labour cost is left out.
"""

from datetime import date
from decimal import Decimal


def cost_rate(membership, day: date) -> Decimal | None:
    """What one hour of the member's time costs the company on `day`, in the company's base
    currency; None when unknown (no compensation, or a pay type without an hourly cost).
    A time entry's labour cost is `minutes / 60 * cost_rate`."""
    return None
