"""Time off in the bot: requests for approvers and decisions for the person who asked."""

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.utils.translation import gettext as _

from apps.members.bot_messages import BotMessage
from apps.timeoff.callbacks import TimeOffAction, TimeOffDecision
from apps.timeoff.models import TimeOff


def request(time_off: TimeOff) -> BotMessage:
    """What approvers see. Once decided, it shows the outcome instead of buttons."""
    lines = [
        _("<b>Time off request</b> · %(name)s") % {"name": html.quote(str(time_off.membership))},
        _("Dates: %(dates)s · days: %(count)d")
        % {"dates": dates(time_off), "count": time_off.days},
    ]
    if time_off.reason:
        lines.append(_("Reason: %(reason)s") % {"reason": html.quote(time_off.reason)})
    if time_off.status != TimeOff.Status.PENDING:
        return "\n".join([*lines, "", _outcome(time_off)]), None
    buttons = [
        InlineKeyboardButton(
            text=_("Approve"),
            callback_data=TimeOffDecision(
                action=TimeOffAction.APPROVE, time_off_id=time_off.pk
            ).pack(),
        ),
        InlineKeyboardButton(
            text=_("Reject"),
            callback_data=TimeOffDecision(
                action=TimeOffAction.REJECT, time_off_id=time_off.pk
            ).pack(),
        ),
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[buttons])


def decision(time_off: TimeOff) -> BotMessage | None:
    values = {"dates": dates(time_off)}
    if time_off.status == TimeOff.Status.APPROVED:
        text = _(
            "Your time off is approved: %(dates)s. "
            "No tasks or reminders from me on those days. Have a good rest!"
        )
        return text % values, None
    if time_off.status == TimeOff.Status.REJECTED:
        return _("Your time off request for %(dates)s was declined.") % values, None
    return None


def dates(time_off: TimeOff) -> str:
    first, last = time_off.first_day, time_off.last_day
    return f"{first:%d.%m}" if first == last else f"{first:%d.%m} – {last:%d.%m}"


def _outcome(time_off: TimeOff) -> str:
    if time_off.status == TimeOff.Status.CANCELLED:
        return _("Cancelled by %(name)s") % {"name": html.quote(str(time_off.membership))}
    name = html.quote(time_off.decided_by.get_full_name() if time_off.decided_by else "—")
    if time_off.status == TimeOff.Status.APPROVED:
        return _("Approved by %(name)s") % {"name": name}
    return _("Rejected by %(name)s") % {"name": name}


# Inbox notifications (plain text: the inbox escapes it) ---------------------------------


def request_title(time_off: TimeOff) -> str:
    return _("Time off request · %(name)s") % {"name": time_off.membership}


def request_body(time_off: TimeOff) -> str:
    lines = [
        _("Dates: %(dates)s · days: %(count)d") % {"dates": dates(time_off), "count": time_off.days}
    ]
    if time_off.reason:
        lines.append(_("Reason: %(reason)s") % {"reason": time_off.reason})
    return "\n".join(lines)


def decision_title(time_off: TimeOff) -> str:
    if time_off.status == TimeOff.Status.APPROVED:
        return _("Your time off is approved")
    return _("Your time off request was declined")


def decision_body(time_off: TimeOff) -> str:
    values = {"dates": dates(time_off)}
    if time_off.status == TimeOff.Status.APPROVED:
        return (
            _("%(dates)s. No tasks or reminders from me on those days. Have a good rest!") % values
        )
    return _("%(dates)s. Talk to your manager if you need these days.") % values


def recorded_title(time_off: TimeOff) -> str:
    return _("Time off recorded for you")


def recorded_body(time_off: TimeOff) -> str:
    by = time_off.recorded_by
    lines = [
        _("%(dates)s, recorded by %(name)s.")
        % {"dates": dates(time_off), "name": by if by is not None else "—"}
    ]
    if time_off.reason:
        lines.append(_("Reason: %(reason)s") % {"reason": time_off.reason})
    return "\n".join(lines)


def revoked_title(time_off: TimeOff) -> str:
    if time_off.status == TimeOff.Status.CANCELLED:
        return _("Your time off was cancelled")
    return _("Your time off was shortened")


def revoked_body(time_off: TimeOff) -> str:
    who = time_off.revoked_by.get_full_name() if time_off.revoked_by else "—"
    if time_off.status == TimeOff.Status.CANCELLED:
        text = _("%(name)s cancelled your time off %(dates)s.") % {
            "name": who,
            "dates": dates(time_off),
        }
    else:
        text = _("%(name)s changed your time off: it now ends on %(date)s.") % {
            "name": who,
            "date": f"{time_off.last_day:%d.%m}",
        }
    if time_off.revoke_reason:
        text += "\n" + _("Reason: %(reason)s") % {"reason": time_off.revoke_reason}
    return text
