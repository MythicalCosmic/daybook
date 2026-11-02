"""Inbox action handlers of payroll (`apps.inbox.registry.register_action`): one handler per
button, shared by the Telegram buttons and the dashboard. Each calls the service, which checks
permissions and audits, and returns a short sentence for the person who pressed."""

from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.payroll import services
from apps.payroll.models import Adjustment, Advance, Payslip


def _target(model, notification):
    row = model.objects.filter(
        company_id=notification.company_id, pk=notification.target_id
    ).first()
    if row is None:
        raise DomainError(_("This isn't available any more."))
    return row


def approve_adjustment(notification, by, reason):
    services.approve(_target(Adjustment, notification), by=by)
    return _("Approved.")


def reject_adjustment(notification, by, reason):
    services.reject(_target(Adjustment, notification), by=by, reason=reason)
    return _("Rejected.")


def approve_advance(notification, by, reason):
    services.decide_advance(_target(Advance, notification), by=by, approve_it=True)
    return _("Advance approved.")


def reject_advance(notification, by, reason):
    services.decide_advance(_target(Advance, notification), by=by, approve_it=False, note=reason)
    return _("Advance rejected.")


def payslip_received(notification, by, reason):
    services.confirm_received(_target(Payslip, notification), by=by)
    return _("Thank you!")
