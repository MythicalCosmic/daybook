"""Inbox action handlers of attendance (`apps.inbox.registry.register_action`): one handler
per button, shared by the Telegram buttons and the dashboard. Each calls the service, which
checks permissions and audits, and returns a short sentence for the person who pressed."""

from django.utils.translation import gettext as _

from apps.attendance import services
from apps.attendance.models import AttendanceCorrection, AttendanceRecord, ShiftSwap, WorkShift
from apps.core.exceptions import DomainError


def _target(model, notification):
    row = model.objects.filter(
        company_id=notification.company_id, pk=notification.target_id
    ).first()
    if row is None:
        raise DomainError(_("This isn't available any more."))
    return row


def approve_correction(notification, by, reason):
    services.decide_correction(_target(AttendanceCorrection, notification), by=by, approve=True)
    return _("Correction approved.")


def reject_correction(notification, by, reason):
    services.decide_correction(
        _target(AttendanceCorrection, notification), by=by, approve=False, reason=reason
    )
    return _("Correction rejected.")


def approve_overtime(notification, by, reason):
    services.decide_overtime(_target(AttendanceRecord, notification), by=by, approve=True)
    return _("Overtime approved.")


def reject_overtime(notification, by, reason):
    services.decide_overtime(
        _target(AttendanceRecord, notification), by=by, approve=False, reason=reason
    )
    return _("Overtime rejected.")


def approve_swap(notification, by, reason):
    services.decide_swap(_target(ShiftSwap, notification), by=by, approve=True)
    return _("Swap approved.")


def reject_swap(notification, by, reason):
    services.decide_swap(_target(ShiftSwap, notification), by=by, approve=False, reason=reason)
    return _("Swap rejected.")


def accept_cover(notification, by, reason):
    swap = services.accept_swap(_target(ShiftSwap, notification), by=by)
    if swap.status == ShiftSwap.Status.APPROVED:
        return _("Done, the shift is yours.")
    return _("Thanks! A manager will confirm.")


def decline_cover(notification, by, reason):
    services.decline_swap(_target(ShiftSwap, notification), by=by)
    return _("Declined.")


def claim_shift(notification, by, reason):
    swap = services.claim_open_shift(_target(WorkShift, notification), by=by)
    if swap.status == ShiftSwap.Status.APPROVED:
        return _("Done, the shift is yours.")
    return _("Asked! A manager will confirm.")
