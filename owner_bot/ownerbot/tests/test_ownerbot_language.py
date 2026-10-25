"""The owner bot's languages (research R1 L5, L7, L8): an Uzbek default menu, its profile in
three languages, and /language."""

import pytest
from aiogram.methods import (
    EditMessageReplyMarkup,
    EditMessageText,
    SetChatMenuButton,
    SetMyCommands,
    SetMyDescription,
    SetMyShortDescription,
)
from asgiref.sync import sync_to_async
from django.utils import translation
from django.utils.translation import gettext

from apps.accounts.models import User
from apps.accounts.telegram_chat import LANGUAGE_BUTTON
from ownerbot.commands import set_commands
from ownerbot.handlers.language import OwnerLanguage, OwnerLanguageHome
from ownerbot.tests import updates


async def test_the_default_menu_is_uzbek_and_the_profile_has_three_languages(bot):
    await set_commands(bot)

    menus = {r.language_code: r for r in bot.requests if isinstance(r, SetMyCommands)}
    with translation.override("uz"):
        assert menus[None].commands[0].description == gettext("Today at a glance")
    assert "language" in [command.command for command in menus["en"].commands]
    descriptions = {r.language_code for r in bot.requests if isinstance(r, SetMyDescription)}
    shorts = {r.language_code for r in bot.requests if isinstance(r, SetMyShortDescription)}
    assert descriptions == shorts == {None, "uz", "ru", "en"}


@pytest.mark.django_db(transaction=True)
async def test_language_is_picked_and_the_menu_follows(dp, bot):
    person = updates.tg_user(7101)
    await dp.feed_update(bot, updates.message(person, "/language"))
    [picker] = bot.sent()
    assert picker.text == "Tilni tanlang. Hozir: O‘zbekcha."  # everyone starts in Uzbek
    row = picker.reply_markup.inline_keyboard[0]
    assert [b.text for b in row] == ["O‘zbekcha", "Русский", "English"]
    assert [b.style for b in row] == ["success", None, None]  # the current one, coloured

    await dp.feed_update(bot, updates.callback(person, OwnerLanguage(code="ru").pack()))

    user = await sync_to_async(User.objects.get)(telegram_id=7101)
    assert user.language == "ru"
    assert bot.sent()[-1].text == "Теперь пишу по-русски."
    [menu] = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert menu.scope.chat_id == 7101
    assert any(isinstance(r, SetChatMenuButton) for r in bot.requests)


@pytest.mark.django_db(transaction=True)
async def test_the_home_message_offers_the_languages_in_place(dp, bot):
    person = updates.tg_user(7102, language_code="ru")
    await dp.feed_update(bot, updates.message(person, "/start"))
    [home] = bot.sent()
    with translation.override("uz"):
        assert home.text.startswith(gettext("Hello, %(name)s!") % {"name": person.first_name})
    [[button]] = home.reply_markup.inline_keyboard
    assert button.text == LANGUAGE_BUTTON

    await dp.feed_update(bot, updates.callback(person, button.callback_data))
    [edit] = [r for r in bot.requests if isinstance(r, EditMessageReplyMarkup)]
    assert [b.text for b in edit.reply_markup.inline_keyboard[-1]] == [
        "O‘zbekcha",
        "Русский",
        "English",
    ]

    await dp.feed_update(bot, updates.callback(person, OwnerLanguageHome(code="ru").pack()))
    assert (await sync_to_async(User.objects.get)(telegram_id=7102)).language == "ru"
    [redrawn] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    with translation.override("ru"):
        assert redrawn.text.startswith(gettext("Hello, %(name)s!") % {"name": person.first_name})
    assert redrawn.reply_markup.inline_keyboard[-1][0].text == LANGUAGE_BUTTON
    assert len(bot.sent()) == 1  # all in place
