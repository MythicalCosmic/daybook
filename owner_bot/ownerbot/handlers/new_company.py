"""`/new` (and `/start new_<code>`): create a company in three taps (§10.2).

    (signup code, when COMPANY_SIGNUP needs one) → name → timezone (Tashkent preselected, or
    typed) → confirm → "Company created. You are its owner. [Open Get started]"

The code is checked when typed and used up only when the company is created.
"""

from contextlib import suppress

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.accounts.models import User
from apps.core.exceptions import DomainError
from ownerbot import bot_messages, new_company
from ownerbot.callbacks import NewCompanyStep
from ownerbot.states import NewCompany

router = Router(name="new_company")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

START_PREFIX = "new_"
NAME_LIMIT = 200


async def begin(message: Message, user: User, state: FSMContext, code: str | None = None) -> None:
    """Start the conversation, with a code from a `/start new_<code>` link when there is one."""
    await state.clear()
    rules = await sync_to_async(new_company.policy)(user)
    if not rules.allowed:
        await message.answer(bot_messages.signup_closed(rules.reason))
        return
    if rules.needs_code:
        found = await sync_to_async(new_company.code_ok)(code) if code else None
        if found is None:
            if code:
                await message.answer(bot_messages.bad_code())
            await state.set_state(NewCompany.code)
            text, markup = bot_messages.ask_code()
            await message.answer(text, reply_markup=markup)
            return
        await state.update_data(code=found)
    await state.set_state(NewCompany.name)
    text, markup = bot_messages.ask_name()
    await message.answer(text, reply_markup=markup)


@router.message(Command("new"))
async def cmd_new(message: Message, user: User, state: FSMContext) -> None:
    await begin(message, user, state)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is not None:
        await state.clear()
        await message.answer(bot_messages.cancelled())


@router.message(NewCompany.code, F.text, ~F.text.startswith("/"))
async def got_code(message: Message, state: FSMContext) -> None:
    found = await sync_to_async(new_company.code_ok)(message.text)
    if found is None:
        await message.answer(bot_messages.bad_code())
        return
    await state.update_data(code=found)
    await state.set_state(NewCompany.name)
    text, markup = bot_messages.ask_name()
    await message.answer(text, reply_markup=markup)


@router.message(NewCompany.name, F.text, ~F.text.startswith("/"))
async def got_name(message: Message, state: FSMContext) -> None:
    name = " ".join(message.text.split())
    if not name or len(name) > NAME_LIMIT:
        await message.answer(bot_messages.bad_name())
        return
    await state.update_data(name=name)
    await state.set_state(NewCompany.timezone)
    text, markup = bot_messages.ask_timezone(name, timezone.now())
    await message.answer(text, reply_markup=markup)


@router.message(NewCompany.timezone, F.text, ~F.text.startswith("/"))
async def got_timezone(message: Message, state: FSMContext, user: User) -> None:
    zone = new_company.resolve_timezone(message.text)
    if zone is None:
        await message.answer(bot_messages.bad_timezone())
        return
    await _confirm(message, state, user, zone)


@router.message(NewCompany.code)
@router.message(NewCompany.name)
@router.message(NewCompany.timezone)
async def not_text(message: Message) -> None:
    """A photo, sticker or voice note in the middle of /new."""
    if message.text and message.text.startswith("/"):
        return
    await message.answer(bot_messages.bad_name())


async def _confirm(message: Message, state: FSMContext, user: User, zone: str) -> None:
    await state.update_data(timezone=zone)
    await state.set_state(NewCompany.confirm)
    data = await state.get_data()
    text, markup = bot_messages.confirm(data["name"], zone, user.language, timezone.now())
    await message.answer(text, reply_markup=markup)


@router.callback_query(NewCompanyStep.filter(F.action == "cancel"))
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(bot_messages.cancelled(), reply_markup=None)
    await callback.answer()


@router.callback_query(NewCompany.timezone, NewCompanyStep.filter(F.action == "tz"))
async def picked_timezone(
    callback: CallbackQuery, callback_data: NewCompanyStep, state: FSMContext, user: User
) -> None:
    zone = new_company.resolve_timezone(callback_data.value)
    if zone is None:
        await callback.answer(bot_messages.bad_timezone(), show_alert=True)
        return
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await _confirm(callback.message, state, user, zone)
    await callback.answer()


@router.callback_query(NewCompany.timezone, NewCompanyStep.filter(F.action == "type_tz"))
async def type_timezone(callback: CallbackQuery) -> None:
    await callback.message.answer(bot_messages.type_timezone())
    await callback.answer()


@router.callback_query(NewCompany.confirm, NewCompanyStep.filter(F.action == "rename"))
async def rename(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewCompany.name)
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    text, markup = bot_messages.ask_name()
    await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(NewCompany.confirm, NewCompanyStep.filter(F.action == "create"))
async def create(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.clear()
    try:
        company = await sync_to_async(new_company.create)(
            user, name=data["name"], timezone=data["timezone"], code=data.get("code")
        )
    except DomainError as exc:
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(str(exc))
        await callback.answer()
        return
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    text, markup = bot_messages.created(company.pk, company.name)
    await callback.message.answer(text, reply_markup=markup)
    await callback.answer("")


@router.callback_query(NewCompanyStep.filter())
async def stale_button(callback: CallbackQuery) -> None:
    """A button from a conversation that already ended."""
    await callback.answer(bot_messages.cancelled())
