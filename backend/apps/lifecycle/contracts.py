"""What the people-lifecycle app promises other apps (docs/PLAN-OWNER.md §13.4).

Payroll (package H) prorates pay with `unpaid_days`; package S fills it from unpaid
suspensions. Until then nobody has unpaid suspension days.
"""

from datetime import date


def unpaid_days(membership, start: date, end: date) -> int:
    """Days from `start` to `end` (inclusive) the member spent on unpaid suspension."""
    return 0
