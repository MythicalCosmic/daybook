"""The main menu's mini app buttons: "Open app" and the module buttons with a screen.

Telegram gives a Mini App opened from a keyboard button no initData, so the app couldn't sign
the person in: these buttons send their text, and the bot answers with an inline button that
opens the app (at the button's screen) signed in. The chat keeps one such helper message at most
(audit B-15): a new one replaces the one before.
"""

from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Filter
from aiogram.types import InlineKeyboardMarkup, Message
from django.conf import settings
from django.core.cache import cache
from django.utils.translation import gettext as _

from apps.members.bot_menu import MenuButton as Registered
from apps.members.bot_menu import registered
from apps.members.bot_messages import MENU_APP, open_app
from bot.filters.menu import MenuButton, is_label

router = Router(name="member-app")

# The chat's last "open the app" helper message. Telegram lets a bot delete its own messages in
# a private chat for 48 hours.
HELPER_KEY = "employee-bot:app-helper:{chat_id}"
HELPER_TTL = 47 * 3600


def screen_button(text: str | None) -> Registered | None:
    """The module button with a mini app screen that `text` is, in any language."""
    if not text:
        return None
    return next((b for b in registered() if b.web_app_screen and is_label(text, b.msgid)), None)


class OpensAppScreen(Filter):
    """A module's button that opens a mini app screen, while the app is configured; without
    the app the module's own handler answers it."""

    async def __call__(self, message: Message) -> bool | dict:
        button = screen_button(message.text) if settings.EMPLOYEE_MINIAPP_URL else None
        return {"button": button} if button else False


@router.message(MenuButton(MENU_APP))
async def open_the_app(message: Message) -> None:
    if not settings.EMPLOYEE_MINIAPP_URL:  # an old keyboard, from before the app was removed
        await message.answer(_("The app isn't available right now."))
        return
    text, markup = open_app()
    await send_helper(message, text, markup)


@router.message(OpensAppScreen())
async def open_a_screen(message: Message, button: Registered) -> None:
    text, markup = open_app(button.web_app_screen, label=_(button.msgid))
    await send_helper(message, text, markup)


async def send_helper(message: Message, text: str, markup: InlineKeyboardMarkup) -> Message:
    """Send the helper with its app button, deleting the chat's previous one first, so taps on
    the menu's app buttons never pile up messages."""
    key = HELPER_KEY.format(chat_id=message.chat.id)
    previous = await cache.aget(key)
    if previous:
        with suppress(TelegramAPIError):
            await message.bot.delete_message(chat_id=message.chat.id, message_id=previous)
    sent = await message.answer(text, reply_markup=markup)
    await cache.aset(key, sent.message_id, HELPER_TTL)
    return sent
