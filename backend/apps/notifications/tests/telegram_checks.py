"""Telegram's rules for what a bot sends, checked on every Bot API call a test makes: both
bots' mocked sessions and the `sent_messages` fixture collect what breaks them, and the test
that sent a message Telegram would refuse (bad HTML, too long, callback data over 64 bytes)
fails when it ends. Collected rather than raised: a handler's exception would only reach the
bots' error handler, which answers "Something went wrong" and lets the test go on."""

from aiogram.client.default import Default
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageCaption,
    EditMessageReplyMarkup,
    EditMessageText,
    SendDocument,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from apps.notifications.html_limits import (
    CALLBACK_DATA_LIMIT,
    CAPTION_LIMIT,
    TEXT_LIMIT,
    problems,
)

ALERT_LIMIT = 200  # answerCallbackQuery text
WITH_MARKUP = (
    SendMessage,
    EditMessageText,
    SendPhoto,
    SendDocument,
    EditMessageCaption,
    EditMessageReplyMarkup,
)


def text_problems(text: str | None, *, limit: int, html: bool = True) -> list[str]:
    if not text:
        return []
    if html:
        return problems(text, limit=limit)
    return [f"{len(text)} characters, more than {limit}"] if len(text) > limit else []


def markup_problems(markup) -> list[str]:
    """Inline buttons need words and at most 64 bytes of callback data; reply buttons words."""
    if markup is None:
        return []
    if isinstance(markup, dict):
        rows = markup.get("inline_keyboard") or markup.get("keyboard") or []
        buttons = [button for row in rows for button in row]
        texts = [button.get("text", "") for button in buttons]
        data = [button.get("callback_data") for button in buttons]
    elif isinstance(markup, InlineKeyboardMarkup):
        buttons = [button for row in markup.inline_keyboard for button in row]
        texts = [button.text for button in buttons]
        data = [button.callback_data for button in buttons]
    elif isinstance(markup, ReplyKeyboardMarkup):
        texts = [button.text for row in markup.keyboard for button in row]
        data = []
    else:
        return []
    found = [f"a button without words: {texts}" for text in texts if not str(text).strip()]
    found += [
        f"callback data {value!r} is {len(value.encode())} bytes, more than {CALLBACK_DATA_LIMIT}"
        for value in data
        if value and len(value.encode()) > CALLBACK_DATA_LIMIT
    ]
    return found


def method_problems(method: TelegramMethod) -> list[str]:
    html = isinstance(getattr(method, "parse_mode", None), Default | str)
    found = []
    if isinstance(method, SendMessage | EditMessageText):
        found += text_problems(method.text, limit=TEXT_LIMIT, html=html)
    elif isinstance(method, SendPhoto | SendDocument | EditMessageCaption):
        found += text_problems(method.caption, limit=CAPTION_LIMIT, html=html)
    elif isinstance(method, AnswerCallbackQuery):
        found += text_problems(method.text, limit=ALERT_LIMIT, html=False)
    if isinstance(method, WITH_MARKUP):
        found += markup_problems(method.reply_markup)
    return found


def sent_problems(text: str, reply_markup: dict | None, photo: str | None) -> list[str]:
    """A message the backend sends through apps.notifications.telegram.send_message."""
    limit = CAPTION_LIMIT if photo and len(text) <= CAPTION_LIMIT else TEXT_LIMIT
    return text_problems(text, limit=limit) + markup_problems(reply_markup)


def report(problems: list[str]) -> str:
    return "Telegram would refuse what this test sent:\n" + "\n".join(problems)
