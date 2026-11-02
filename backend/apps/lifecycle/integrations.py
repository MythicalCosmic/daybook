"""What the people lifecycle calls in payroll (docs/PLAN-OWNER.md §13.4): a disciplinary
record's fine is a proposed payroll Adjustment; a company without the payroll module gets a clear
`DomainError` and nothing else changes. Payroll is imported inside the functions because it reads
the lifecycle's unpaid days.

    fine = integrations.propose_fine(member, by=hr, amount=Decimal("200000"),
                                     reason="Saqlash sharoiti buzildi", source="discipline")
"""

from decimal import Decimal

from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError


def propose_fine(membership, *, by, amount: Decimal, reason: str, source: str):
    """`payroll.services.propose_fine`: a proposed fine for `membership` (an Adjustment)."""
    if not membership.company.has_feature("payroll"):
        raise DomainError(_("Payroll is off for this company: give the warning without a fine."))
    from apps.payroll import services as payroll

    return payroll.propose_fine(membership, by=by, amount=amount, reason=reason, source=source)


def fine_summary(company, fine_id: int | None) -> dict | None:
    """{id, amount, currency, status} of a proposed fine, or None (no fine, or payroll can't
    say). Only for people who may see pay."""
    if not fine_id:
        return None
    from apps.payroll.models import Adjustment

    row = Adjustment.objects.filter(company=company, pk=fine_id).first()
    if row is None:
        return None
    return {
        "id": row.pk,
        "amount": f"{row.amount:.2f}",
        "currency": row.currency,
        "status": row.status,
    }
