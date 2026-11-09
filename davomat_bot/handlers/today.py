"""`/today` (managers: the attendance board of their branches) and `/me` (anyone linked: their
own day and month), each with a Refresh button that redraws the message in place."""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from davomat_bot import bot_messages, views
from davomat_bot.callbacks import MeView, TodayView
from davomat_bot.middlewares.person import Person

router = Router(name="today")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


def _unlinked(person: Person) -> str | None:
    """Why there is nothing to show this person, or None."""
    if person.company is None:
        return bot_messages.home(None, None, "")[0]
    if person.member is None:
        return bot_messages.not_linked()
    return None


@router.message(Command("today"))
async def cmd_today(message: Message, person: Person, state: FSMContext) -> None:
    await state.clear()
    if reason := _unlinked(person):
        await message.answer(reason)
        return
    text, markup = await sync_to_async(views.today)(person.member, language=person.language)
    await message.answer(text, reply_markup=markup)


@router.callback_query(TodayView.filter())
async def today_again(callback: CallbackQuery, callback_data: TodayView, person: Person) -> None:
    if reason := _unlinked(person):
        await callback.answer(reason[:200], show_alert=True)
        return
    text, markup = await sync_to_async(views.today)(
        person.member, branch_id=callback_data.branch, language=person.language
    )
    await _redraw(callback, text, markup)


@router.message(Command("me"))
async def cmd_me(message: Message, person: Person, state: FSMContext) -> None:
    await state.clear()
    if reason := _unlinked(person):
        await message.answer(reason)
        return
    text, markup = await sync_to_async(views.me)(person.member, language=person.language)
    await message.answer(text, reply_markup=markup)


@router.callback_query(MeView.filter())
async def me_again(callback: CallbackQuery, person: Person) -> None:
    if reason := _unlinked(person):
        await callback.answer(reason[:200], show_alert=True)
        return
    text, markup = await sync_to_async(views.me)(person.member, language=person.language)
    await _redraw(callback, text, markup)


async def _redraw(callback: CallbackQuery, text: str, markup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        # Unchanged within the same minute: Telegram refuses an edit to the same text. A message
        # that is gone goes to on_error, which tells the person to open it again.
        if "not modified" not in str(exc).lower():
            raise
    await callback.answer(_("Updated"))
