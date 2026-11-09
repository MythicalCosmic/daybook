"""`/today` and `/me` in words (sync: handlers call them through `sync_to_async`).

`/today` is the attendance board of the person's branches (`queries.day_board`): who is in the
building now, who came late and by how much, who isn't in yet, who is absent and who is on
leave. `/me` is the person's own day (`queries.my_day`) and month so far (`analytics.person`,
the same figures as the Reports page).
"""

from datetime import datetime

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.utils import timezone, translation
from django.utils.dates import MONTHS_ALT
from django.utils.text import capfirst
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.attendance import analytics, clock, queries
from apps.attendance.bot_messages import duration
from apps.companies.models import Branch
from apps.members import scope
from apps.members.models import Membership
from davomat_bot import bot_messages
from davomat_bot.bot_messages import BotMessage
from davomat_bot.callbacks import MeView, TodayView

# Names shown per list before "and N more".
LIST_LIMIT = 12
# Branch buttons under /today, when the person sees several branches.
BRANCH_BUTTONS = 6


def _names(rows: list[str]) -> list[str]:
    shown = [f"    {line}" for line in rows[:LIST_LIMIT]]
    if len(rows) > LIST_LIMIT:
        shown.append("    " + _("and %(count)d more") % {"count": len(rows) - LIST_LIMIT})
    return shown


def _time(value: str | None) -> str:
    """ "09:25" from a local ISO moment."""
    return value[11:16] if value else ""


def _person(row: dict) -> str:
    return html.quote(row["member"]["name"])


def today(
    member: Membership, *, branch_id: int = 0, now: datetime | None = None, language: str = "uz"
) -> BotMessage:
    with translation.override(language):
        return _today(member, branch_id=branch_id, now=now)


def _today(member: Membership, *, branch_id: int, now: datetime | None) -> BotMessage:
    if not member.company.has_feature("attendance"):
        return bot_messages.module_off(), None
    if not bot_messages.sees_attendance(member):
        return bot_messages.not_for_you(), None
    now = now or timezone.now()
    company = member.company
    allowed = scope.branch_ids(member)
    visible = Branch.objects.filter(company=company, is_active=True).order_by("order", "name")
    if allowed is not None:
        visible = visible.filter(pk__in=allowed)
    visible = list(visible)
    picked = next((branch for branch in visible if branch.pk == branch_id), None)
    branch_ids = [picked.pk] if picked else allowed
    day = clock.today(company, now)
    board = queries.day_board(company, day, branch_ids=branch_ids, now=now)
    totals = board["totals"]
    local = clock.local(company, now)

    title = html.quote(company.name) + (f" · {html.quote(picked.name)}" if picked else "")
    lines = [f"<b>{title}</b> · {local:%d.%m.%Y %H:%M}", ""]
    came = totals[queries.IN] + totals[queries.LATE]
    lines.append(_("In the building now: %(count)d") % {"count": totals["present"]})
    if totals["rostered"]:
        lines.append(
            _("Came today: %(came)d of %(rostered)d")
            % {"came": came, "rostered": totals["rostered"]}
        )
    else:
        lines.append(_("Came today: %(came)d") % {"came": came})

    rows = board["people"]
    late = [
        _("%(name)s · %(minutes)s late, at %(time)s")
        % {
            "name": _person(row),
            "minutes": duration(row["record"]["late_minutes"]),
            "time": _time(row["record"]["check_in_at"]),
        }
        for row in rows
        if row["state"] == queries.LATE
    ]
    waiting = [
        _("%(name)s · shift from %(time)s") % {"name": _person(row), "time": row["shift"]["start"]}
        for row in rows
        if row["state"] == queries.NOT_YET and row["shift"]
    ]
    absent = [_person(row) for row in rows if row["state"] == queries.ABSENT]
    away = [
        _person(row)
        for row in rows
        if row["state"] == queries.OFF and row["reason"] in ("leave", "excused")
    ]
    for heading, items in (
        (_("Late"), late),
        (_("Not in yet"), waiting),
        (_("Absent"), absent),
        (_("On leave"), away),
    ):
        if items:
            lines += ["", f"<b>{html.quote(heading)}</b>", *_names(items)]
    if not rows or (not came and not totals["rostered"]):
        lines += ["", _("Nobody is expected and nobody has come in yet today.")]

    if not picked and len(board["branches"]) > 1:
        busy = [card for card in board["branches"] if card["rostered"] or card["checked_in"]]
        if busy:
            lines += ["", f"<b>{html.quote(_('Branches'))}</b>"]
        for card in busy:
            count = (
                _("%(came)d of %(rostered)d")
                % {"came": card["checked_in"], "rostered": card["rostered"]}
                if card["rostered"]
                else str(card["checked_in"])
            )
            lines.append(f"    {html.quote(card['name'])} — {count}")
    return "\n".join(lines), _today_keyboard(member, visible, picked)


def _today_keyboard(member, visible, picked) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=_("Refresh"),
                callback_data=TodayView(branch=picked.pk if picked else 0).pack(),
            )
        ]
    ]
    if len(visible) > 1:
        choices = [(0, _("All branches")), *[(b.pk, b.name) for b in visible[:BRANCH_BUTTONS]]]
        buttons = [
            InlineKeyboardButton(
                text=label,
                callback_data=TodayView(branch=pk).pack(),
                style="success" if (picked.pk if picked else 0) == pk else None,
            )
            for pk, label in choices
        ]
        rows += [buttons[index : index + 3] for index in range(0, len(buttons), 3)]
    if bot_messages.uses_dashboard(member):
        button = bot_messages.open_button(_("Open in Davomat"), f"c/{member.company_id}/attendance")
        if button is not None:
            rows.append([button])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# /me ------------------------------------------------------------------------------------


def me(member: Membership, *, now: datetime | None = None, language: str = "uz") -> BotMessage:
    with translation.override(language):
        return _me(member, now=now)


def _me(member: Membership, *, now: datetime | None) -> BotMessage:
    company = member.company
    if not company.has_feature("attendance"):
        return bot_messages.module_off(), None
    now = now or timezone.now()
    local = clock.local(company, now)
    name = analytics.name(member)
    lines = [f"<b>{html.quote(name)}</b> · {html.quote(company.name)}", ""]
    lines += [f"<b>{html.quote(_('Today'))}</b>, {local:%d.%m}", *_day_lines(member, now)]

    start = local.date().replace(day=1)
    month = analytics.person(member, start, local.date(), now=now)
    lines += ["", f"<b>{html.quote(capfirst(str(MONTHS_ALT[start.month])))}</b>"]
    if month.days_scheduled:
        lines.append(
            "    "
            + _("Days at work: %(present)d of %(scheduled)d")
            % {"present": month.expected_present, "scheduled": month.days_scheduled}
        )
        extra = month.days_present - month.expected_present
        if extra:
            lines.append("    " + _("Days without a shift: %(count)d") % {"count": extra})
    else:
        lines.append("    " + _("Days at work: %(count)d") % {"count": month.days_present})
    lines.append("    " + _("Hours worked: %(time)s") % {"time": duration(month.worked_minutes)})
    if month.late_count:
        lines.append(
            "    "
            + ngettext(
                "Late: %(count)d time, %(time)s in all",
                "Late: %(count)d times, %(time)s in all",
                month.late_count,
            )
            % {"count": month.late_count, "time": duration(month.late_minutes)}
        )
    if month.early_leave_count:
        lines.append(
            "    "
            + ngettext(
                "Left early: %(count)d time", "Left early: %(count)d times", month.early_leave_count
            )
            % {"count": month.early_leave_count}
        )
    if month.days_absent:
        lines.append(
            "    "
            + ngettext("Absent: %(count)d day", "Absent: %(count)d days", month.days_absent)
            % {"count": month.days_absent}
        )
    if month.days_leave:
        lines.append(
            "    "
            + ngettext("On leave: %(count)d day", "On leave: %(count)d days", month.days_leave)
            % {"count": month.days_leave}
        )
    if month.overtime_minutes:
        lines.append("    " + _("Overtime: %(time)s") % {"time": duration(month.overtime_minutes)})
    if month.punctuality_percent is not None:
        lines.append(
            "    " + _("On time: %(percent)s%%") % {"percent": _number(month.punctuality_percent)}
        )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_("Refresh"), callback_data=MeView().pack())]]
    )
    return "\n".join(lines), markup


def _number(value: float) -> str:
    text = f"{value:g}"
    return text if (translation.get_language() or "uz") == "en" else text.replace(".", ",")


def _day_lines(member: Membership, now: datetime) -> list[str]:
    """Today's shift, check-in and check-out, or why there is none."""
    company = member.company
    day = queries.my_day(member, now)
    shift, record, state = day["shift"], day["record"], day["state"]
    lines = []
    if shift and shift["date"] == day["date"]:
        where = f" · {html.quote(shift['branch']['name'])}" if shift.get("branch") else ""
        lines.append(
            _("Shift: %(start)s–%(end)s") % {"start": shift["start"], "end": shift["end"]} + where
        )
    if record and record["check_in_at"] and record["date"] == day["date"]:
        came = _("In: %(time)s") % {"time": _time(record["check_in_at"])}
        if record["is_late"]:
            came += " · " + _("%(time)s late") % {"time": duration(record["late_minutes"])}
        lines.append(came)
        if record["status"] == "open":
            lines.append(_("Still here"))
        elif record["check_out_at"]:
            lines.append(
                _("Out: %(time)s · %(worked)s")
                % {
                    "time": _time(record["check_out_at"]),
                    "worked": duration(record["worked_minutes"]),
                }
            )
    elif state in ("upcoming", "due"):
        pass  # the shift line says when
    elif state == "late":
        lines.append(_("Not in yet"))
    elif queries.on_leave(member, clock.today(company, now)) is not None:
        lines.append(_("On leave"))
    elif not lines:
        lines.append(_("No shift today"))
    return [f"    {line}" for line in lines]
