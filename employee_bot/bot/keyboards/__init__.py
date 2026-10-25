"""Keyboards the bot's own handlers share."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from apps.accounts.telegram_chat import LANGUAGE_BUTTON
from bot.callbacks import LangCallback


def with_language_button(markup):
    """A last row with "Til / Язык / Language", which shows the three languages in its place:
    on the greeting and on whatever someone who isn't a member yet is told (everyone starts in
    Uzbek). A message whose keyboard is a reply keyboard can't carry inline buttons, so it goes
    without (a member finds /language in the menu and on the home message)."""
    if markup is not None and not isinstance(markup, InlineKeyboardMarkup):
        return markup
    button = InlineKeyboardButton(
        text=LANGUAGE_BUTTON, callback_data=LangCallback(code="", mode="langs").pack()
    )
    rows = [row for row in (markup.inline_keyboard if markup else []) if not is_language_row(row)]
    return InlineKeyboardMarkup(inline_keyboard=[*rows, [button]])


def is_language_row(row: list[InlineKeyboardButton]) -> bool:
    prefix = f"{LangCallback.__prefix__}:"
    return any((button.callback_data or "").startswith(prefix) for button in row)
