"""Each person's chat gets the app's menu button labelled in their own language (the one every chat
starts with is Uzbek), on /start and when the app asks for a button that signs in. Best effort."""

from datetime import datetime

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage, SetChatMenuButton
from aiogram.types import Chat, MenuButtonWebApp, Message, Update, WebAppData

from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

APP = "https://app.example.com/app/"


def menu_buttons(bot) -> list[SetChatMenuButton]:
    return [r for r in bot.requests if isinstance(r, SetChatMenuButton)]


def app_data(telegram_id: int, language: str) -> Update:
    """What Telegram sends when the app, opened from an old keyboard button, asks for a button."""
    return Update(
        update_id=telegram_id * 10 + 1,
        message=Message(
            message_id=telegram_id * 10 + 2,
            date=datetime.now(),
            chat=Chat(id=telegram_id, type="private"),
            from_user=updates.tg_user(telegram_id, language_code=language),
            web_app_data=WebAppData(data="open_app", button_text="Open app"),
        ),
    )


@pytest.mark.parametrize(
    ("language", "label"),
    [("ru", "Открыть приложение"), ("uz", "Ilovani ochish"), ("en", "Open app")],
)
async def test_start_labels_the_chats_menu_button_in_their_language(
    dp, bot, settings, language, label
):
    settings.EMPLOYEE_MINIAPP_URL = APP

    person = updates.tg_user(9_201, language_code=language)

    await dp.feed_update(bot, updates.message(person, "/start"))
    if language != "uz":  # everyone starts in Uzbek; the greeting's language button changes it
        await dp.feed_update(bot, updates.pick_language(person, language, mode="welcome"))

    button = menu_buttons(bot)[-1]
    assert button.chat_id == 9_201
    assert isinstance(button.menu_button, MenuButtonWebApp)
    assert button.menu_button.text == label
    assert button.menu_button.web_app.url == APP
    # The answer came first: the label never holds it up.
    kinds = [type(r) for r in bot.requests if isinstance(r, (SendMessage, SetChatMenuButton))]
    assert kinds.index(SendMessage) < kinds.index(SetChatMenuButton)


async def test_the_apps_request_for_a_button_labels_it_too(dp, bot, company, member, settings):
    settings.EMPLOYEE_MINIAPP_URL = APP
    worker = await member.aregistered(company)
    worker.user.language = "ru"
    await worker.user.asave(update_fields=["language"])

    await dp.feed_update(bot, app_data(worker.user.telegram_id, "ru"))

    [button] = menu_buttons(bot)
    assert button.chat_id == worker.user.telegram_id
    assert button.menu_button.text == "Открыть приложение"


async def test_a_refused_label_never_stops_the_answer(dp, bot, settings, monkeypatch, caplog):
    settings.EMPLOYEE_MINIAPP_URL = APP
    real = bot.session.make_request

    async def refuse(bot_, method, timeout=None):  # noqa: ASYNC109 (aiogram's signature)
        if isinstance(method, SetChatMenuButton):
            raise TelegramBadRequest(method=method, message="Bad Request: chat not found")
        return await real(bot_, method, timeout)

    monkeypatch.setattr(bot.session, "make_request", refuse)

    person = updates.tg_user(9_202)
    await dp.feed_update(bot, updates.message(person, "/start"))
    await dp.feed_update(bot, updates.pick_language(person))

    assert bot.sent_texts()  # the greeting still went out
    assert "Couldn't label the menu button" in caplog.text
