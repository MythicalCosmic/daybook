"""Notification buttons of sales and cash (`apps.inbox.registry.register_action`).

One handler serves the Telegram button and the dashboard button alike
(`apps.inbox.services.run_action`). Each looks its record up in the presser's own company, checks
what the presser may do and calls the service, which checks the business rules and audits.
"""

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.members import scope
from apps.members.permissions import Perm
from apps.sales import services
from apps.sales.models import CashMovement, CashShift


def _movement(notification, by) -> CashMovement:
    movement = CashMovement.objects.filter(
        pk=notification.target_id, company_id=by.company_id
    ).first()
    if movement is None:
        raise DomainError(_("This handover no longer exists."))
    return movement


def received(notification, by, reason: str) -> str:
    services.confirm_handover(_movement(notification, by), by=by)
    return _("Marked as received. Thank you!")


def not_received(notification, by, reason: str) -> str:
    services.decline_handover(_movement(notification, by), by=by, reason=reason)
    return _("Noted: the owners were told the cash didn't arrive.")


def verify(notification, by, reason: str) -> str:
    shift = CashShift.objects.filter(pk=notification.target_id, company_id=by.company_id).first()
    if shift is None:
        raise DomainError(_("This shift no longer exists."))
    if not by.has_perm(Perm.SALES_MANAGE) or not scope.allows(
        scope.branch_ids(by), shift.branch_id
    ):
        raise PermissionDenied(_("You don't have permission to do this."))
    services.verify_shift(shift, by=by)
    return _("Verified.")
