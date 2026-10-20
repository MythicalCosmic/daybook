"""Employee bot, Package F. Attendance: `/checkin` and the "📍 Keldim / Ketdim" button
(a location share as the fallback), shift-start nudges, "still working?", swap and cover
requests.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20). The location and selfie
handlers are bound to this router's own states, so they never take a task's proof photo.
Cover requests and open shifts arrive as inbox notifications; their buttons are the inbox's
generic ones (apps.attendance.actions).
"""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.utils.translation import gettext as _

from apps.attendance import bot_messages, queries, services
from apps.attendance.callbacks import AttendanceAction, AttendanceButton
from apps.attendance.models import AttendanceRecord, WorkShift
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from bot.filters.membership import IsRegistered
from bot.filters.menu import MenuButton

router = Router(name="feature_attendance")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())
# The handlers live in a child router: the feature router's own filters still gate them,
# and anything registered on the feature router itself (the shared dispatcher tests plug
# temporary handlers in there) is offered the update first.
flow = Router(name="attendance_check_in")
router.include_router(flow)


class CheckFlow(StatesGroup):
    location = State()  # waiting for the location share (data: mode "in" or "out")
    selfie = State()  # waiting for the selfie (data: the location already shared)


# Starting ------------------------------------------------------------------------------


@flow.message(Command("checkin"))
@flow.message(MenuButton(bot_messages.MENU_CHECK))
async def start(message: Message, membership: Membership, state: FSMContext) -> None:
    await _prompt(message, membership, state)


@flow.callback_query(
    AttendanceButton.filter(F.action.in_({AttendanceAction.CHECK_IN, AttendanceAction.CHECK_OUT}))
)
async def start_from_button(
    query: CallbackQuery, membership: Membership, state: FSMContext
) -> None:
    await query.answer()
    await _prompt(query.message, membership, state)


async def _prompt(message: Message, membership: Membership, state: FSMContext) -> None:
    text, markup, mode = await _prompt_for(membership)
    if mode is None:
        await state.clear()
    else:
        await state.set_state(CheckFlow.location)
        await state.update_data(mode=mode)
    await message.answer(text, reply_markup=markup)


@sync_to_async
def _prompt_for(membership: Membership):
    if not membership.company.has_feature("attendance"):
        return bot_messages.module_off(), None, None
    record = queries.open_record(membership)
    if record is not None:
        text, markup = bot_messages.prompt_check_out(record)
        return text, markup, "out"
    text, markup = bot_messages.prompt_check_in(queries.my_day(membership))
    return text, markup, "in"


# The location, then the selfie when the company asks for one ----------------------------


@flow.message(CheckFlow.location, F.location)
async def got_location(message: Message, membership: Membership, state: FSMContext) -> None:
    data = await state.get_data()
    location = message.location
    point = {
        "lat": location.latitude,
        "lng": location.longitude,
        "accuracy": location.horizontal_accuracy,
    }
    if data.get("mode") == "in" and await _needs_selfie(membership):
        await state.set_state(CheckFlow.selfie)
        await state.update_data(**point)
        await message.answer(bot_messages.selfie_prompt())
        return
    await state.clear()
    text, markup = await _check(membership, data.get("mode", "in"), point, photo=None)
    await message.answer(text, reply_markup=markup)


@flow.message(CheckFlow.selfie, F.photo)
async def got_selfie(message: Message, bot: Bot, membership: Membership, state: FSMContext) -> None:
    data = await state.get_data()
    downloaded = await bot.download(message.photo[-1])
    photo = ContentFile(downloaded.getvalue(), name="selfie.jpg")
    await state.clear()
    point = {key: data.get(key) for key in ("lat", "lng", "accuracy")}
    text, markup = await _check(membership, "in", point, photo=photo)
    await message.answer(text, reply_markup=markup)


@flow.message(CheckFlow.location, MenuButton(bot_messages.CANCEL))
@flow.message(CheckFlow.selfie, MenuButton(bot_messages.CANCEL))
async def cancel(message: Message, membership: Membership, state: FSMContext) -> None:
    await state.clear()
    text, markup = await sync_to_async(bot_messages.cancelled)(membership)
    await message.answer(text, reply_markup=markup)


@flow.message(CheckFlow.location)
async def not_a_location(message: Message) -> None:
    await message.answer(
        _("Tap «%(button)s» below to share where you are.")
        % {"button": _(bot_messages.SEND_LOCATION)}
    )


@flow.message(CheckFlow.selfie)
async def not_a_selfie(message: Message) -> None:
    await message.answer(bot_messages.selfie_prompt())


@sync_to_async
def _needs_selfie(membership: Membership) -> bool:
    from apps.attendance import conf

    return conf.get_settings(membership.company).require_photo


@sync_to_async
def _check(membership: Membership, mode: str, point: dict, *, photo):
    source = AttendanceRecord.Source.BOT
    try:
        if mode == "out":
            result = services.check_out(membership, source=source, **point)
            return bot_messages.checked_out(result.record, membership)
        result = services.check_in(membership, source=source, photo=photo, **point)
        return bot_messages.checked_in(result.record, membership)
    except DomainError as exc:
        return bot_messages.refused(str(exc), membership)


# Nudge buttons -------------------------------------------------------------------------


@flow.callback_query(AttendanceButton.filter(F.action == AttendanceAction.OFF_TODAY))
async def off_today(
    query: CallbackQuery, callback_data: AttendanceButton, membership: Membership
) -> None:
    answer = await _off_today(membership, callback_data.ref)
    await query.answer(answer, show_alert=False)
    if query.message is not None:
        await query.message.edit_reply_markup(reply_markup=None)


@sync_to_async
def _off_today(membership: Membership, shift_id: int) -> str:
    shift = WorkShift.objects.filter(pk=shift_id, membership=membership).first()
    if shift is None:
        return _("This shift isn't yours any more.")
    services.say_off_today(membership, shift)
    return bot_messages.off_today_ack()


@flow.callback_query(AttendanceButton.filter(F.action == AttendanceAction.DONE_NOW))
async def done_now(
    query: CallbackQuery, callback_data: AttendanceButton, membership: Membership
) -> None:
    text, ok = await _done_now(membership, callback_data.ref)
    await query.answer(text if not ok else "", show_alert=not ok)
    if ok and query.message is not None:
        await query.message.edit_text(text, reply_markup=None)


@sync_to_async
def _done_now(membership: Membership, record_id: int) -> tuple[str, bool]:
    record = AttendanceRecord.objects.filter(pk=record_id, membership=membership).first()
    if record is None or record.status != AttendanceRecord.Status.OPEN:
        return _("You're already checked out."), False
    try:
        result = services.check_out_now(membership)
    except DomainError as exc:
        return str(exc), False
    return bot_messages.done_now(result.record), True


@flow.callback_query(AttendanceButton.filter(F.action == AttendanceAction.STILL_HERE))
async def still_here(query: CallbackQuery) -> None:
    await query.answer(bot_messages.still_here_ack())
    if query.message is not None:
        await query.message.edit_reply_markup(reply_markup=None)
