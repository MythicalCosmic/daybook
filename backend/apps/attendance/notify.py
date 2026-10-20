"""Messages attendance sends once a change has committed: inbox notifications (the dashboard,
the mini app inbox and both bots), the employee bot's own nudges and group posts.

Services and jobs call these from `transaction.on_commit`, by id, so a message never goes out
for a change that was rolled back. Each loads what it needs and renders in the recipient's
language. Nothing here writes attendance rows (only notification and job-mark rows).
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.attendance import bot_messages, clock, queries
from apps.attendance.models import (
    AttendanceCorrection,
    AttendanceRecord,
    JobMark,
    ShiftSwap,
    WorkShift,
)
from apps.groups import services as groups
from apps.groups.models import GroupEvent
from apps.inbox import services as inbox
from apps.inbox.services import NotificationAction
from apps.members.models import Membership
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup

logger = logging.getLogger(__name__)

APPROVE = NotificationAction("approve", gettext_lazy("Approve"), "primary")
REJECT = NotificationAction("reject", gettext_lazy("Reject"), "danger", needs_reason=True)


def _name(member: Membership | None) -> str:
    if member is None:
        return "—"
    return member.full_name or str(member.user)


def _url(company_id: int, path: str = "") -> str:
    return f"/c/{company_id}/attendance{path}"


def mark_once(company_id: int, key: str) -> bool:
    """True the first time `key` is marked for the company (jobs that run often act once)."""
    try:
        with transaction.atomic():
            JobMark.objects.create(company_id=company_id, key=key[:100])
    except IntegrityError:
        return False
    return True


def send_direct(member: Membership, render) -> bool:
    """A message from the employee bot to `member` (approved, with Telegram), rendered in
    their language by `render() -> (text, markup)`."""
    user = member.user
    if member.status != Membership.Status.APPROVED or not user.telegram_id:
        return False
    with translation.override(user.language):
        text, markup = render()
    send_telegram_message.delay(BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup))
    return True


def _with_users(members):
    ids = [member.pk for member in members]
    return list(Membership.objects.filter(pk__in=ids).select_related("user", "company"))


# Manager approvals (queue kinds: the Telegram copy carries the buttons) -------------------


def correction_waiting(correction_id: int) -> None:
    correction = (
        AttendanceCorrection.objects.select_related(
            "company", "membership__user", "membership__home_branch", "record__branch"
        )
        .filter(pk=correction_id, status=AttendanceCorrection.Status.PENDING)
        .first()
    )
    if correction is None:
        return
    company = correction.company
    member = correction.membership
    branch_id = (
        correction.record.branch_id
        if correction.record_id and correction.record.branch_id
        else member.home_branch_id
    )
    recipients = _with_users(queries.managers_for(company, branch_id, exclude=member.pk))

    def title(_person):
        return _("%(name)s asks to correct %(date)s") % {
            "name": _name(member),
            "date": clock.day_month(correction.date),
        }

    def body(_person):
        parts = []
        if correction.check_in_at:
            parts.append(_("Came %(time)s") % {"time": clock.hhmm(company, correction.check_in_at)})
        if correction.check_out_at:
            parts.append(
                _("Left %(time)s") % {"time": clock.hhmm(company, correction.check_out_at)}
            )
        return " · ".join(parts) + f"\n«{correction.reason}»"

    inbox.notify(
        recipients,
        "attendance.correction",
        title=title,
        body=body,
        url=_url(company.pk, "/corrections"),
        app_screen="",
        target=correction,
        actor=member,
        actions=[APPROVE, REJECT],
    )


def overtime_waiting(record_id: int) -> None:
    record = (
        AttendanceRecord.objects.select_related("company", "membership__user", "shift", "branch")
        .filter(pk=record_id, overtime_status=AttendanceRecord.Overtime.PENDING)
        .first()
    )
    if record is None:
        return
    company = record.company
    recipients = _with_users(
        queries.managers_for(company, record.branch_id, exclude=record.membership_id)
    )

    def title(_person):
        return _("%(name)s worked %(extra)s extra on %(date)s") % {
            "name": _name(record.membership),
            "extra": bot_messages.duration(record.overtime_minutes),
            "date": clock.day_month(record.date),
        }

    def body(_person):
        return _("Checked in %(start)s, out %(end)s") % {
            "start": clock.hhmm(company, record.check_in_at),
            "end": clock.hhmm(company, record.check_out_at),
        }

    inbox.notify(
        recipients,
        "attendance.overtime",
        title=title,
        body=body,
        url=_url(company.pk, "/corrections?tab=overtime"),
        target=record,
        actor=record.membership,
        actions=[APPROVE, REJECT],
    )


def swap_waiting(swap_id: int) -> None:
    swap = _swap(swap_id)
    if swap is None or swap.status != ShiftSwap.Status.ACCEPTED:
        return
    company = swap.company
    recipients = _with_users(
        queries.managers_for(company, swap.shift.branch_id, exclude=swap.accepted_by_id)
    )

    def title(_person):
        if swap.kind == ShiftSwap.Kind.CLAIM:
            return _("%(name)s wants the open shift %(shift)s") % {
                "name": _name(swap.accepted_by),
                "shift": bot_messages.shift_line(swap.shift),
            }
        if swap.kind == ShiftSwap.Kind.SWAP:
            return _("%(a)s and %(b)s want to swap shifts") % {
                "a": _name(swap.requested_by),
                "b": _name(swap.accepted_by),
            }
        return _("%(b)s will cover %(a)s: %(shift)s") % {
            "a": _name(swap.requested_by),
            "b": _name(swap.accepted_by),
            "shift": bot_messages.shift_line(swap.shift),
        }

    inbox.notify(
        recipients,
        "attendance.swap",
        title=title,
        body=lambda _p: swap.note,
        url=_url(company.pk, "/swaps"),
        target=swap,
        actor=swap.accepted_by,
        actions=[APPROVE, REJECT],
    )


# Results for the employee ---------------------------------------------------------------


def correction_decided(correction_id: int) -> None:
    correction = (
        AttendanceCorrection.objects.select_related("company", "membership__user")
        .filter(pk=correction_id)
        .first()
    )
    if correction is None:
        return
    approved = correction.status == AttendanceCorrection.Status.APPROVED

    def title(_person):
        if approved:
            return _("Your correction for %(date)s was approved") % {
                "date": clock.day_month(correction.date)
            }
        return _("Your correction for %(date)s was rejected") % {
            "date": clock.day_month(correction.date)
        }

    inbox.notify(
        [correction.membership],
        "attendance.decision",
        title=title,
        body=lambda _p: correction.decision_note,
        app_screen="attendance",
        target=correction,
        severity="info" if approved else "warning",
    )


def overtime_decided(record_id: int, reason: str = "") -> None:
    record = (
        AttendanceRecord.objects.select_related("company", "membership__user")
        .filter(pk=record_id)
        .first()
    )
    if record is None:
        return
    approved = record.overtime_status == AttendanceRecord.Overtime.APPROVED

    def title(_person):
        values = {
            "extra": bot_messages.duration(record.overtime_minutes),
            "date": clock.day_month(record.date),
        }
        if approved:
            return _("Your %(extra)s of overtime on %(date)s was approved") % values
        return _("Your %(extra)s of overtime on %(date)s was not approved") % values

    inbox.notify(
        [record.membership],
        "attendance.decision",
        title=title,
        body=reason,
        app_screen="attendance",
        target=record,
        dedupe_key=f"overtime:{record.pk}:{record.overtime_status}",
    )


def roster_published(by_member: dict[int, list[int]]) -> None:
    """One message per person listing their newly published shifts."""
    for member_id, shift_ids in by_member.items():
        member = Membership.objects.select_related("user", "company").filter(pk=member_id).first()
        if member is None:
            continue
        shifts = list(
            WorkShift.objects.filter(pk__in=shift_ids)
            .select_related("branch", "company")
            .order_by("starts_at")
        )
        if not shifts:
            continue

        def title(_person, rows=shifts):
            return _("New shifts for you (%(count)s)") % {"count": len(rows)}

        def body(_person, rows=shifts):
            return "\n".join(bot_messages.shift_line(shift) for shift in rows[:14])

        inbox.notify(
            [member],
            "attendance.roster",
            title=title,
            body=body,
            app_screen="attendance.shifts",
            target=shifts[0],
        )


def shift_changed(shift_id: int, member_ids: list[int]) -> None:
    shift = (
        WorkShift.objects.select_related("branch", "company", "membership")
        .filter(pk=shift_id)
        .first()
    )
    if shift is None:
        return
    for member in Membership.objects.filter(pk__in=member_ids).select_related("user", "company"):
        mine = shift.membership_id == member.pk

        def title(_person, mine=mine):
            if mine:
                return _("Your shift changed: %(shift)s") % {
                    "shift": bot_messages.shift_line(shift)
                }
            return _("You no longer work %(shift)s") % {"shift": bot_messages.shift_line(shift)}

        inbox.notify(
            [member],
            "attendance.roster",
            title=title,
            app_screen="attendance.shifts",
            target=shift,
        )


def shift_removed(shift_id: int, member_id: int) -> None:
    shifts_removed({member_id: [shift_id]})


def shifts_removed(by_member: dict[int, list[int]]) -> None:
    for member_id, shift_ids in by_member.items():
        member = Membership.objects.select_related("user", "company").filter(pk=member_id).first()
        shifts = list(
            WorkShift.objects.filter(pk__in=shift_ids)
            .select_related("branch", "company")
            .order_by("starts_at")
        )
        if member is None or not shifts:
            continue

        def title(_person, rows=shifts):
            if len(rows) == 1:
                return _("Your shift was removed: %(shift)s") % {
                    "shift": bot_messages.shift_line(rows[0])
                }
            return _("%(count)s of your shifts were removed") % {"count": len(rows)}

        def body(_person, rows=shifts):
            return (
                "\n".join(bot_messages.shift_line(shift) for shift in rows) if len(rows) > 1 else ""
            )

        inbox.notify(
            [member],
            "attendance.roster",
            title=title,
            body=body,
            app_screen="attendance.shifts",
            target=shifts[0],
        )


def auto_closed(record_id: int) -> None:
    record = (
        AttendanceRecord.objects.select_related("company", "membership__user", "shift")
        .filter(pk=record_id)
        .first()
    )
    if record is None:
        return

    def title(_person):
        if record.shift_id:
            return _("We closed your shift at %(time)s because you didn't check out") % {
                "time": clock.hhmm(record.company, record.check_out_at)
            }
        return _("We closed your check-in of %(date)s because you didn't check out") % {
            "date": clock.day_month(record.date)
        }

    inbox.notify(
        [record.membership],
        "attendance.auto_closed",
        title=title,
        body=gettext_lazy("If you left at another time, send a correction in the app."),
        app_screen=f"attendance.correct:{record.pk}",
        target=record,
        severity="warning",
        dedupe_key=f"auto_closed:{record.pk}",
    )


# Swaps between colleagues --------------------------------------------------------------


def _swap(swap_id: int) -> ShiftSwap | None:
    return (
        ShiftSwap.objects.select_related(
            "company",
            "shift__branch",
            "shift__company",
            "shift__membership",
            "other_shift__branch",
            "other_shift__company",
            "requested_by__user",
            "accepted_by__user",
            "target__user",
        )
        .filter(pk=swap_id)
        .first()
    )


def swap_offered(swap_id: int) -> None:
    """The colleague named (or everyone eligible) gets the request with Accept/Decline."""
    swap = _swap(swap_id)
    if swap is None or swap.status != ShiftSwap.Status.REQUESTED:
        return
    if swap.target_id:
        recipients = [swap.target]
    else:
        recipients = list(queries.eligible_for(swap.shift).select_related("user", "company"))
    if not recipients:
        return

    def title(_person):
        if swap.kind == ShiftSwap.Kind.SWAP:
            return _("%(name)s offers a swap: your %(theirs)s for their %(mine)s") % {
                "name": _name(swap.requested_by),
                "theirs": bot_messages.shift_line(swap.other_shift),
                "mine": bot_messages.shift_line(swap.shift),
            }
        return _("%(name)s asks you to cover %(shift)s") % {
            "name": _name(swap.requested_by),
            "shift": bot_messages.shift_line(swap.shift),
        }

    actions = [NotificationAction("accept", gettext_lazy("Accept"), "primary")]
    if swap.target_id:
        actions.append(NotificationAction("decline", gettext_lazy("Decline"), "default"))
    inbox.notify(
        recipients,
        "attendance.cover_request",
        title=title,
        body=lambda _p: swap.note,
        app_screen="attendance.swaps",
        target=swap,
        actor=swap.requested_by,
        actions=actions,
    )


def open_shifts_posted(shift_ids: list[int]) -> None:
    """People who may claim a newly published open shift get it with a Claim button."""
    for shift in WorkShift.objects.filter(
        pk__in=shift_ids, status=WorkShift.Status.OPEN
    ).select_related("branch", "company", "position"):
        recipients = list(queries.eligible_for(shift).select_related("user", "company"))
        if not recipients:
            continue

        def title(_person, shift=shift):
            return _("Open shift: %(shift)s") % {"shift": bot_messages.shift_line(shift)}

        inbox.notify(
            recipients,
            "attendance.open_shift",
            title=title,
            body=lambda _p, shift=shift: shift.note,
            app_screen="attendance.swaps",
            target=shift,
            actions=[NotificationAction("claim", gettext_lazy("Claim"), "primary")],
        )


def swap_approved(swap_id: int, closed_ids: list[int] = ()) -> None:
    swap = _swap(swap_id)
    if swap is None:
        return
    people = [m for m in (swap.requested_by, swap.accepted_by) if m is not None]
    for member in _with_users(people):
        taker = member.pk == swap.accepted_by_id

        def title(_person, taker=taker):
            if swap.kind == ShiftSwap.Kind.CLAIM:
                return _("The shift %(shift)s is yours") % {
                    "shift": bot_messages.shift_line(swap.shift)
                }
            if swap.kind == ShiftSwap.Kind.SWAP:
                return _("Your swap with %(name)s is done") % {
                    "name": _name(swap.requested_by if taker else swap.accepted_by)
                }
            if taker:
                return _("You now work %(shift)s instead of %(name)s") % {
                    "shift": bot_messages.shift_line(swap.shift),
                    "name": _name(swap.requested_by),
                }
            return _("%(name)s covers your shift %(shift)s") % {
                "name": _name(swap.accepted_by),
                "shift": bot_messages.shift_line(swap.shift),
            }

        inbox.notify(
            [member],
            "attendance.decision",
            title=title,
            app_screen="attendance.shifts",
            target=swap,
            dedupe_key=f"swap:{swap.pk}:approved",
        )
    for pk in closed_ids:
        swap_closed(pk)
    groups.broadcast(
        swap.company_id,
        GroupEvent.SHIFTS,
        _render_group(swap.company, lambda: bot_messages.swap_post(swap)),
        branch_id=swap.shift.branch_id,
    )


def swap_closed(swap_id: int) -> None:
    """A request that ended without moving the shift: tell the person who asked (and the
    colleague who had accepted)."""
    swap = _swap(swap_id)
    if swap is None or swap.is_open or swap.status == ShiftSwap.Status.APPROVED:
        return
    people = [swap.requested_by]
    if swap.accepted_by_id and swap.accepted_by_id != swap.requested_by_id:
        people.append(swap.accepted_by)
    # Whoever closed it themselves (the asker cancelling) doesn't need to hear about it.
    if swap.decided_by_id is not None:
        people = [member for member in people if member.user_id != swap.decided_by_id]
    if not people:
        return
    for member in _with_users(people):

        def title(_person):
            values = {"shift": bot_messages.shift_line(swap.shift)}
            if swap.status == ShiftSwap.Status.EXPIRED:
                return _("Nobody took %(shift)s in time") % values
            if swap.status == ShiftSwap.Status.CANCELLED:
                return _("The request about %(shift)s was cancelled") % values
            return _("The request about %(shift)s was declined") % values

        inbox.notify(
            [member],
            "attendance.decision",
            title=title,
            body=swap.decision_note,
            app_screen="attendance.swaps",
            target=swap,
            dedupe_key=f"swap:{swap.pk}:{swap.status}",
        )


# Alerts for managers --------------------------------------------------------------------


def no_show(shift_id: int, said_off: bool) -> None:
    shift = (
        WorkShift.objects.select_related("company", "membership__user", "branch")
        .filter(pk=shift_id)
        .first()
    )
    if shift is None or shift.membership is None:
        return
    company = shift.company
    recipients = _with_users(
        queries.managers_for(company, shift.branch_id, exclude=shift.membership_id)
    )

    def title(_person):
        values = {
            "name": _name(shift.membership),
            "time": clock.hhmm(company, shift.starts_at),
            "branch": shift.branch.name if shift.branch_id else "",
        }
        if said_off:
            return _("%(name)s says they're off today (shift %(time)s, %(branch)s)") % values
        return _("%(name)s hasn't checked in (shift %(time)s, %(branch)s)") % values

    inbox.notify(
        recipients,
        "attendance.no_show",
        title=title,
        url=_url(company.pk, f"?date={shift.date.isoformat()}"),
        target=shift,
        actor=shift.membership,
        dedupe_key=f"no_show:{shift.pk}",
    )


def outside_check_in(record_id: int) -> None:
    record = (
        AttendanceRecord.objects.select_related("company", "membership__user", "branch")
        .filter(pk=record_id)
        .first()
    )
    if record is None or record.branch_id is None:
        return
    company = record.company
    recipients = _with_users(
        queries.managers_for(company, record.branch_id, exclude=record.membership_id)
    )

    def title(_person):
        return _("%(name)s checked in %(distance)s from %(branch)s") % {
            "name": _name(record.membership),
            "distance": bot_messages.distance(record.in_distance_m),
            "branch": record.branch.name,
        }

    inbox.notify(
        recipients,
        "attendance.outside",
        title=title,
        url=_url(company.pk, f"?date={record.date.isoformat()}&record={record.pk}"),
        target=record,
        actor=record.membership,
        dedupe_key=f"outside:{record.pk}",
    )


# Group posts ----------------------------------------------------------------------------


def _render_group(company, render) -> str:
    with translation.override(company.default_language):
        return render()


def late_arrival(record_id: int) -> None:
    record = (
        AttendanceRecord.objects.select_related("company", "membership__user", "shift", "branch")
        .filter(pk=record_id)
        .first()
    )
    if record is None or not record.is_late:
        return
    groups.broadcast(
        record.company_id,
        GroupEvent.ATTENDANCE,
        _render_group(record.company, lambda: bot_messages.late_post(record)),
        position_ids=[record.membership.position_id] if record.membership.position_id else (),
        branch_id=record.branch_id,
    )


def morning_post(company, branch, board_rows: list[dict], rostered: int) -> int:
    present = [row["member"]["name"] for row in board_rows if row["state"] == queries.IN]
    late = [row["member"]["name"] for row in board_rows if row["state"] == queries.LATE]
    missing = [
        row["member"]["name"]
        for row in board_rows
        if row["state"] in (queries.NOT_YET, queries.ABSENT) and row["shift"]
    ]
    text = _render_group(
        company, lambda: bot_messages.morning_post(branch, present, late, missing, rostered)
    )
    return groups.broadcast(company.pk, GroupEvent.ATTENDANCE, text, branch_id=branch.pk)


# Employee-bot nudges --------------------------------------------------------------------


def nudge_pre_shift(shift: WorkShift) -> bool:
    return send_direct(shift.membership, lambda: bot_messages.pre_shift(shift))


def nudge_late(shift: WorkShift) -> bool:
    return send_direct(shift.membership, lambda: bot_messages.late_nudge(shift))


def ask_still_working(record: AttendanceRecord) -> bool:
    return send_direct(record.membership, lambda: bot_messages.still_working(record))
