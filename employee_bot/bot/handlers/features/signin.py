"""Employee bot, Package A. Dashboard sign-in while the owner bot has no token: `/start login_…`
(registered with `bot.deeplinks.register_start_param`), the number-matching buttons, and "Log
out everywhere" under the "Signed in on …" message. The conversation itself is
`apps.signin.bot_flow`, the same one the owner bot runs.

Registered before the start router and the member gate, so whoever signs in reaches it
whatever the state of their memberships. Private chats only: it comes before the group
router, and nothing here belongs in a group.
"""

from contextlib import suppress

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.signin import bot_flow
from apps.signin.callbacks import LoginTap, SessionsAction
from bot.deeplinks import register_start_param

router = Router(name="feature_signin")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


async def start_login(message: Message, payload: str, *, user: User, state: FSMContext) -> None:
    """`/start login_<code>`: the prompt with three numbers. A conversation in progress is left
    as it is; the prompt is answered with buttons."""
    text, markup = await sync_to_async(bot_flow.start)(user, payload)
    await message.answer(text, reply_markup=markup)


register_start_param("login_", start_login)


@router.callback_query(LoginTap.filter())
async def tapped(callback: CallbackQuery, callback_data: LoginTap, user: User) -> None:
    text, signed_in = await sync_to_async(bot_flow.tap)(
        user, callback_data.link, callback_data.pick
    )
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=None)
    await callback.answer("" if signed_in else None)


@router.callback_query(SessionsAction.filter(F.action == "all"))
async def log_out_everywhere(callback: CallbackQuery, user: User) -> None:
    text = await sync_to_async(bot_flow.log_out_everywhere)(user)
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(text, show_alert=True)
