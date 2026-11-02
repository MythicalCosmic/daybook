"""What HR promises other apps about contracts (docs/PLAN-OWNER.md §13.4; fixed signatures).

The people lifecycle (terminations, job changes) and payroll call these instead of touching
`apps.hr.models.Contract`. `by=None` is the system (a scheduled job): no permission check.
"""

from datetime import date

from apps.hr import services
from apps.hr.models import Contract


def active_contract(membership) -> Contract | None:
    """The person's contract in force, or None."""
    return (
        Contract.objects.filter(membership=membership, status=Contract.Status.ACTIVE)
        .select_related("position", "template")
        .first()
    )


def amend(contract, *, by, effective_on: date, changes: dict, reason) -> Contract:
    """Change a contract in force: `changes` may hold kind, ends_on, probation_until,
    weekly_hours and position (a Position of the company)."""
    return services.amend_contract(
        contract, by=by, effective_on=effective_on, changes=changes, reason=reason
    )


def end(contract, *, by, ended_on: date, reason) -> Contract:
    """A contract in force ends on `ended_on` (today or before)."""
    return services.end_contract(contract, by=by, ended_on=ended_on, reason=reason)
