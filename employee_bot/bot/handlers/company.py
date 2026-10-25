"""Someone in several companies picks the one the bot's lists and new tasks use (audit X-1).

    /company, the menu's "Demo Dorixona ▸" button, or Settings, then Company

A task's own buttons always act in that task's company (bot.middlewares.access), so a push
from either company works whatever is picked here.
"""

from contextlib import suppress

from aiogram import F, Router, html
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.accounts.services import approved_memberships, bot_membership, remember_company
from apps.members import bot_messages
from apps.members.bot_messages import is_company_button
from bot.callbacks import CompanyCallback

router = Router(name="company")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


class CompanyButton(Filter):
    """The menu's company switch, whatever the company is called."""

    async def __call__(self, message: Message) -> bool:
        return is_company_button(message.text)


@router.message(Command("company"))
@router.message(CompanyButton())
async def ask_company(message: Message, user: User) -> None:
    text, markup = await sync_to_async(_picker)(user)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "co_open")
async def open_picker(callback: CallbackQuery, user: User) -> None:
    text, markup = await sync_to_async(_picker)(user)
    with suppress(TelegramAPIError):
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(CompanyCallback.filter())
async def pick_company(callback: CallbackQuery, callback_data: CompanyCallback, user: User) -> None:
    home = await sync_to_async(_switch)(user, callback_data.company_id)
    if home is None:
        await callback.answer(_("You don't have access to this."), show_alert=True)
        return
    name, (text, markup) = home
    await callback.answer(f"{name}")
    with suppress(TelegramAPIError):
        await callback.message.edit_text(
            _("Now working in <b>%(company)s</b>.") % {"company": html.quote(name)}
        )
    # The main menu differs per company (its modules), so it comes again with the home message.
    await callback.message.answer(text, reply_markup=markup)


def _picker(user: User) -> bot_messages.BotMessage:
    memberships = approved_memberships(user)
    if len(memberships) < 2:
        if memberships:
            return _("You work in one company: <b>%(company)s</b>.") % {
                "company": html.quote(memberships[0].company.name)
            }, None
        return _("You don't have access to this."), None
    current = bot_membership(user)
    rows = [
        [
            InlineKeyboardButton(
                text=("✓ " if current and m.pk == current.pk else "") + m.company.name,
                callback_data=CompanyCallback(company_id=m.company_id).pack(),
            )
        ]
        for m in memberships
    ]
    return _("Which company are you working in?"), InlineKeyboardMarkup(inline_keyboard=rows)


def _switch(user: User, company_id: int) -> tuple[str, bot_messages.BotMessage] | None:
    membership = next((m for m in approved_memberships(user) if m.company_id == company_id), None)
    if membership is None:
        return None
    remember_company(user, company_id)
    return membership.company.name, bot_messages.member_home(membership)
