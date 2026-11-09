"""The buttons of attendance's shift nudges (`AttendanceButton`), which in this edition come
through this bot: "I'm off today" on a missed start, "I'm done now" and "Still here" after a
shift, as the employee bot handles them.

People check in at the terminals here, so "Check in" and "Check out" only say so.
"""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.attendance import bot_messages as attendance_messages
from apps.attendance import services
from apps.attendance.callbacks import AttendanceAction, AttendanceButton
from apps.attendance.models import AttendanceRecord, WorkShift
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from davomat_bot import bot_messages
from davomat_bot.middlewares.person import Person

router = Router(name="nudges")
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


@router.callback_query(AttendanceButton.filter())
async def nudge_button(
    query: CallbackQuery, callback_data: AttendanceButton, person: Person
) -> None:
    if person.member is None:
        await query.answer(bot_messages.not_linked()[:200], show_alert=True)
        return
    action = callback_data.action
    if action in (AttendanceAction.CHECK_IN, AttendanceAction.CHECK_OUT):
        await query.answer(at_the_terminal(), show_alert=True)
        return
    if action == AttendanceAction.OFF_TODAY:
        await query.answer(await _off_today(person.member, callback_data.ref))
        await _drop_buttons(query)
        return
    if action == AttendanceAction.DONE_NOW:
        text, ok = await _done_now(person.member, callback_data.ref)
        await query.answer("" if ok else text, show_alert=not ok)
        if ok and query.message is not None:
            await query.message.edit_text(text, reply_markup=None)
        return
    if action == AttendanceAction.STILL_HERE:
        await query.answer(attendance_messages.still_here_ack())
        await _drop_buttons(query)
        return
    await query.answer()


def at_the_terminal() -> str:
    return _("Here you check in and out at the terminal: it records you when it sees your face.")


async def _drop_buttons(query: CallbackQuery) -> None:
    if query.message is not None:
        await query.message.edit_reply_markup(reply_markup=None)


@sync_to_async
def _off_today(member: Membership, shift_id: int) -> str:
    shift = WorkShift.objects.filter(pk=shift_id, membership=member).first()
    if shift is None:
        return _("This shift isn't yours any more.")
    services.say_off_today(member, shift)
    return attendance_messages.off_today_ack()


@sync_to_async
def _done_now(member: Membership, record_id: int) -> tuple[str, bool]:
    record = AttendanceRecord.objects.filter(pk=record_id, membership=member).first()
    if record is None or record.status != AttendanceRecord.Status.OPEN:
        return _("You're already checked out."), False
    try:
        result = services.check_out_now(member)
    except DomainError as exc:
        return str(exc), False
    return attendance_messages.done_now(result.record), True
