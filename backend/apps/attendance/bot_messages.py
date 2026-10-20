"""What the bots say about attendance: the check-in conversation, nudges and group posts.

Every function renders in the active language (callers wrap them in the recipient's
`translation.override`) and returns `(text, markup)` or plain text. Texts are short and
friendly; buttons beat typing.
"""

from aiogram import html
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from django.conf import settings
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from apps.attendance import clock
from apps.attendance.callbacks import AttendanceAction, AttendanceButton
from apps.attendance.models import AttendanceRecord, ShiftSwap, WorkShift
from apps.members.bot_messages import main_menu, miniapp_url
from apps.members.models import Membership

# The main-menu button (apps.members.bot_menu); "📍 Keldim / Ketdim" in Uzbek.
MENU_CHECK = gettext_noop("📍 Check in / out")
SEND_LOCATION = gettext_noop("📍 Send my location")
CANCEL = gettext_noop("✖️ Cancel")
# The mini app screen the button and the nudges open.
APP_SCREEN = "attendance"


def duration(minutes: int) -> str:
    hours, rest = divmod(max(0, int(minutes)), 60)
    if hours and rest:
        return _("%(h)s h %(m)s min") % {"h": hours, "m": rest}
    if hours:
        return _("%(h)s h") % {"h": hours}
    return _("%(m)s min") % {"m": rest}


def distance(meters: int | None) -> str:
    if meters is None:
        return ""
    if meters >= 1000:
        return _("%(km)s km") % {"km": f"{meters / 1000:.1f}"}
    return _("%(m)s m") % {"m": meters}


def hours(shift: WorkShift) -> str:
    company = shift.company
    return f"{clock.hhmm(company, shift.starts_at)}–{clock.hhmm(company, shift.ends_at)}"


def shift_line(shift: WorkShift) -> str:
    """A shift on one line: weekday, date, hours and branch."""
    weekday = WEEKDAYS[shift.date.weekday()]
    parts = [f"{_(weekday)} {clock.day_month(shift.date)}", hours(shift)]
    if shift.branch_id:
        parts.append(html.quote(shift.branch.name))
    return " · ".join(parts)


WEEKDAYS = (
    gettext_noop("Mon"),
    gettext_noop("Tue"),
    gettext_noop("Wed"),
    gettext_noop("Thu"),
    gettext_noop("Fri"),
    gettext_noop("Sat"),
    gettext_noop("Sun"),
)


def _app_url(screen: str = APP_SCREEN) -> str | None:
    url = settings.EMPLOYEE_MINIAPP_URL
    if not url or not url.startswith("https://"):
        return None
    return miniapp_url(screen)


def app_button(text: str, screen: str = APP_SCREEN) -> InlineKeyboardButton | None:
    url = _app_url(screen)
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url)) if url else None


# The check-in conversation --------------------------------------------------------------


def module_off() -> str:
    return _("Attendance isn't switched on in your company.")


def location_keyboard() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=_(SEND_LOCATION), request_location=True)]]
    url = _app_url()
    if url:
        rows.append([KeyboardButton(text=_("📱 Check in in the app"), web_app=WebAppInfo(url=url))])
    rows.append([KeyboardButton(text=_(CANCEL))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def prompt_check_in(day: dict) -> tuple[str, ReplyKeyboardMarkup]:
    """Before a check-in: today's shift (if any) and the location button."""
    shift = day.get("shift")
    if shift:
        where = f" · {html.quote(shift['branch']['name'])}" if shift.get("branch") else ""
        head = _("📍 <b>Check in</b>\nYour shift: %(start)s–%(end)s%(where)s") % {
            "start": shift["start"],
            "end": shift["end"],
            "where": where,
        }
    else:
        head = _(
            "📍 <b>Check in</b>\nNo shift is planned for you today; "
            "it will be marked as an extra day."
        )
    return f"{head}\n\n{_('Send your location with the button below.')}", location_keyboard()


def prompt_check_out(record: AttendanceRecord) -> tuple[str, ReplyKeyboardMarkup]:
    company = record.company
    since = clock.hhmm(company, record.check_in_at)
    text = _("👋 <b>Check out</b>\nYou're in since %(time)s. Send your location to check out.") % {
        "time": since
    }
    return text, location_keyboard()


def selfie_prompt() -> str:
    return _("📸 Now a quick selfie to finish checking in.")


def checked_in(record: AttendanceRecord, membership: Membership) -> tuple[str, ReplyKeyboardMarkup]:
    company = record.company
    lines = [
        _("✅ Checked in at %(time)s") % {"time": clock.hhmm(company, record.check_in_at)}
        + (f" · {html.quote(record.branch.name)}" if record.branch_id else "")
    ]
    if record.is_late:
        lines.append(
            _("⏰ %(late)s late. Next time a little earlier!")
            % {"late": duration(record.late_minutes)}
        )
    if AttendanceRecord.Flag.OUTSIDE_GEOFENCE in record.flags:
        lines.append(
            _("📌 You were %(distance)s from the branch, so this check-in is marked.")
            % {"distance": distance(record.in_distance_m)}
        )
    if AttendanceRecord.Flag.UNSCHEDULED in record.flags:
        lines.append(_("No shift was planned, so it's recorded as an extra day."))
    lines.append(_("Have a good shift!"))
    return "\n".join(lines), main_menu(membership)


def checked_out(
    record: AttendanceRecord, membership: Membership
) -> tuple[str, ReplyKeyboardMarkup]:
    company = record.company
    text = _("👋 Checked out at %(time)s. You worked %(worked)s today. Thank you!") % {
        "time": clock.hhmm(company, record.check_out_at),
        "worked": duration(record.worked_minutes),
    }
    if record.overtime_minutes:
        text += "\n" + _("⏱ %(extra)s of overtime is waiting for approval.") % {
            "extra": duration(record.overtime_minutes)
        }
    return text, main_menu(membership)


def cancelled(membership: Membership) -> tuple[str, ReplyKeyboardMarkup]:
    return _("Okay, nothing changed."), main_menu(membership)


def refused(message: str, membership: Membership) -> tuple[str, ReplyKeyboardMarkup]:
    return f"⚠️ {html.quote(message)}", main_menu(membership)


# Nudges ---------------------------------------------------------------------------------


def _check_in_button() -> InlineKeyboardButton:
    return app_button(_("📍 Check in")) or InlineKeyboardButton(
        text=_("📍 Check in"),
        callback_data=AttendanceButton(action=AttendanceAction.CHECK_IN).pack(),
    )


def pre_shift(shift: WorkShift) -> tuple[str, InlineKeyboardMarkup]:
    where = f" · {html.quote(shift.branch.name)}" if shift.branch_id else ""
    text = _("🔔 Your shift starts at %(time)s%(where)s.") % {
        "time": clock.hhmm(shift.company, shift.starts_at),
        "where": where,
    }
    return text, InlineKeyboardMarkup(inline_keyboard=[[_check_in_button()]])


def late_nudge(shift: WorkShift) -> tuple[str, InlineKeyboardMarkup]:
    where = f" · {html.quote(shift.branch.name)}" if shift.branch_id else ""
    text = _("⏰ Your shift started at %(time)s%(where)s. Check in when you arrive.") % {
        "time": clock.hhmm(shift.company, shift.starts_at),
        "where": where,
    }
    off = InlineKeyboardButton(
        text=_("🏠 I'm off today"),
        callback_data=AttendanceButton(action=AttendanceAction.OFF_TODAY, ref=shift.pk).pack(),
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[[_check_in_button()], [off]])


def still_working(record: AttendanceRecord) -> tuple[str, InlineKeyboardMarkup]:
    shift = record.shift
    text = _("🕕 Your shift ended at %(time)s. Still working?") % {
        "time": clock.hhmm(record.company, shift.ends_at if shift else record.check_in_at)
    }
    buttons = [
        InlineKeyboardButton(
            text=_("✅ I'm done now"),
            callback_data=AttendanceButton(action=AttendanceAction.DONE_NOW, ref=record.pk).pack(),
        ),
        InlineKeyboardButton(
            text=_("💼 Still here"),
            callback_data=AttendanceButton(
                action=AttendanceAction.STILL_HERE, ref=record.pk
            ).pack(),
        ),
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=[buttons])


def off_today_ack() -> str:
    return _("Got it. Your manager will see that you're off today.")


def still_here_ack() -> str:
    return _("Okay! Don't forget to check out when you leave.")


def done_now(record: AttendanceRecord) -> str:
    return _("👋 Checked out at %(time)s. Thank you for today!") % {
        "time": clock.hhmm(record.company, record.check_out_at)
    }


# Group posts (GroupEvent.ATTENDANCE and SHIFTS) -------------------------------------------


def late_post(record: AttendanceRecord) -> str:
    shift = record.shift
    return _("⏰ <b>%(name)s</b> came %(late)s late (shift %(time)s, %(branch)s).") % {
        "name": html.quote(str(record.membership)),
        "late": duration(record.late_minutes),
        "time": clock.hhmm(record.company, shift.starts_at) if shift else "—",
        "branch": html.quote(record.branch.name) if record.branch_id else "—",
    }


def morning_post(
    branch, present: list[str], late: list[str], missing: list[str], rostered: int
) -> str:
    lines = [
        _("☀️ <b>Who's in · %(branch)s</b>") % {"branch": html.quote(branch.name)},
        _("%(present)s of %(rostered)s on shift are here.")
        % {"present": len(present) + len(late), "rostered": rostered},
    ]
    if present:
        lines.append("✅ " + ", ".join(html.quote(name) for name in present))
    if late:
        lines.append("⏰ " + ", ".join(html.quote(name) for name in late))
    if missing:
        lines.append(
            _("Not here yet: %(names)s") % {"names": ", ".join(html.quote(n) for n in missing)}
        )
    return "\n".join(lines)


def swap_post(swap: ShiftSwap) -> str:
    shift = swap.shift
    return _("🔁 <b>%(to)s</b> takes the shift %(shift)s%(from)s.") % {
        "to": html.quote(str(swap.accepted_by)),
        "shift": shift_line(shift),
        "from": (" " + _("instead of %(name)s") % {"name": html.quote(str(swap.requested_by))})
        if swap.kind != ShiftSwap.Kind.CLAIM
        else "",
    }
