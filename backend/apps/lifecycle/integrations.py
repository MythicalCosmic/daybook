"""What the people lifecycle calls in payroll (package H), tolerant of its absence
(docs/PLAN-OWNER.md §13.4): payroll lands on its own branch, so until both are in, proposing a
fine answers with a clear `DomainError` and nothing else changes.

    fine = integrations.propose_fine(member, by=hr, amount=Decimal("200000"),
                                     reason="Saqlash sharoiti buzildi", source="discipline")
"""

import logging
from decimal import Decimal

from django.apps import apps as django_apps
from django.core.exceptions import FieldError
from django.db import DatabaseError
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError

logger = logging.getLogger(__name__)


def propose_fine(membership, *, by, amount: Decimal, reason: str, source: str):
    """`payroll.services.propose_fine`: a proposed fine for `membership` (an Adjustment)."""
    if not membership.company.has_feature("payroll"):
        raise DomainError(_("Payroll is off for this company: give the warning without a fine."))
    try:
        from apps.payroll import services as payroll

        propose = payroll.propose_fine
    except (ImportError, AttributeError) as exc:
        raise DomainError(
            _("Fines need payroll, which isn't ready yet: give the warning without a fine.")
        ) from exc
    return propose(membership, by=by, amount=amount, reason=reason, source=source)


def fine_summary(company, fine_id: int | None) -> dict | None:
    """{id, amount, currency, status} of a proposed fine, or None (no fine, or payroll can't
    say). Only for people who may see pay."""
    if not fine_id:
        return None
    try:
        adjustment = django_apps.get_model("payroll", "Adjustment")
    except LookupError:
        return None
    try:
        row = adjustment.objects.filter(company=company, pk=fine_id).first()
        if row is None:
            return None
        return {
            "id": row.pk,
            "amount": f"{row.amount:.2f}",
            "currency": row.currency,
            "status": row.status,
        }
    except FieldError, AttributeError, DatabaseError:
        logger.warning("payroll.Adjustment can't be read for a fine", exc_info=True)
        return None
