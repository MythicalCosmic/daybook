from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from apps.notifications import telegram
from apps.notifications.tasks import send_telegram_message


def test_message_is_dropped_without_a_token(settings, monkeypatch):
    settings.EMPLOYEE_BOT_TOKEN = ""
    calls = []
    monkeypatch.setattr(telegram, "_send", lambda *args: calls.append(args))

    telegram.send_message(telegram.BotName.EMPLOYEE, 1, "hi")

    assert calls == []


def test_keyboard_survives_the_trip_through_celery():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Approve", callback_data="join:approve:1")]]
    )

    assert InlineKeyboardMarkup.model_validate(telegram.serialize_markup(markup)) == markup


def test_task_gives_up_quietly_when_the_user_blocked_the_bot(monkeypatch):
    def forbidden(*args):
        raise TelegramForbiddenError(SendMessage(chat_id=1, text="hi"), "bot was blocked")

    monkeypatch.setattr(telegram, "send_message", forbidden)

    send_telegram_message.delay(telegram.BotName.EMPLOYEE, 1, "hi")
