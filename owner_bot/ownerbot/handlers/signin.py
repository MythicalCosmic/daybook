"""Dashboard sign-in in the owner bot: the number buttons after `/start login_…` and the
"Log out everywhere" button under "Signed in on …" (the conversation lives in
`apps.signin.bot_flow`, shared with the employee bot)."""

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

router = Router(name="signin")
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

START_PREFIX = "login_"


async def start_login(message: Message, payload: str, *, user: User, state: FSMContext) -> None:
    """`/start login_<code>`: the prompt with three numbers. A conversation in progress (like
    /new) is left as it is."""
    text, markup = await sync_to_async(bot_flow.start)(user, payload)
    await message.answer(text, reply_markup=markup)


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
