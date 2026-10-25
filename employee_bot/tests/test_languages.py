"""The bot's language: everyone starts in Uzbek (the owner's "uzbek first", 25.10.2026) with one
small "Til / Язык / Language" button on the greeting; /language changes it any time, and the
whole chat follows: replies, the command menu, the menu button and the reply keyboard."""

from datetime import datetime
from itertools import count

import pytest
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    SetChatMenuButton,
    SetMyCommands,
)
from aiogram.types import (
    BotCommandScopeChat,
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    Update,
)
from asgiref.sync import sync_to_async
from django.utils import translation
from django.utils.translation import gettext

from apps.accounts.models import User
from apps.accounts.telegram_chat import LANGUAGE_BUTTON
from apps.members.models import Membership
from bot.callbacks import LangCallback
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

GREETING = "Hi! To join your company, open the invite link your manager sent you."
_ids = count(50_000)


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def said(language: str, msgid: str) -> str:
    with translation.override(language):
        return gettext(msgid)


def tap(person, data: str, markup: InlineKeyboardMarkup | None) -> Update:
    """A button pressed on a message that carries `markup`."""
    return Update(
        update_id=next(_ids),
        callback_query=CallbackQuery(
            id=str(next(_ids)),
            from_user=person,
            chat_instance="test",
            data=data,
            message=Message(
                message_id=next(_ids),
                date=datetime.now(),
                chat=Chat(id=person.id, type="private"),
                text="…",
                reply_markup=markup,
            ),
        ),
    )


@pytest.mark.parametrize("telegram_language", ["ru", "en", "de", "uz", None])
async def test_a_new_person_is_greeted_in_uzbek(dp, bot, telegram_language):
    person = updates.tg_user(9_001, language_code=telegram_language)

    await dp.feed_update(bot, updates.message(person, "/start"))

    [greeting] = sent(bot)  # no picker first
    assert greeting.text == said("uz", GREETING)
    assert [[b.text for b in row] for row in greeting.reply_markup.inline_keyboard] == [
        [LANGUAGE_BUTTON]
    ]
    assert (await User.objects.aget(telegram_id=9_001)).language == "uz"


async def test_the_language_button_shows_the_three_in_its_place(dp, bot):
    person = updates.tg_user(9_002)
    await dp.feed_update(bot, updates.message(person, "/start"))
    greeting = sent(bot)[-1]

    button = greeting.reply_markup.inline_keyboard[-1][0]
    await dp.feed_update(bot, tap(person, button.callback_data, greeting.reply_markup))

    [edit] = [r for r in bot.requests if isinstance(r, EditMessageReplyMarkup)]
    row = edit.reply_markup.inline_keyboard[-1]
    assert [b.text for b in row] == ["O‘zbekcha", "Русский", "English"]  # O‘zbekcha first
    assert [b.style for b in row] == ["success", None, None]  # the current one, coloured
    assert len(sent(bot)) == 1  # in place, nothing new in the chat


async def test_a_language_picked_on_the_greeting_redraws_it_in_place(dp, bot):
    person = updates.tg_user(9_003)
    await dp.feed_update(bot, updates.message(person, "/start"))

    data = LangCallback(code="ru", mode="welcome").pack()
    await dp.feed_update(bot, tap(person, data, None))

    assert (await User.objects.aget(telegram_id=9_003)).language == "ru"
    [edit] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert edit.text == said("ru", GREETING)
    assert edit.reply_markup.inline_keyboard[-1][0].text == LANGUAGE_BUTTON
    assert len(sent(bot)) == 1  # edited, not sent again
    menus = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert isinstance(menus[-1].scope, BotCommandScopeChat) and menus[-1].scope.chat_id == 9_003
    assert menus[-1].commands[0].description == said("ru", "Home")


async def test_an_invite_greets_in_uzbek_at_once(dp, bot, company):
    person = updates.tg_user(9_004, language_code="ru")

    await dp.feed_update(bot, updates.message(person, f"/start {company.invite_start_param}"))

    assert await Membership.objects.filter(user__telegram_id=9_004, company=company).aexists()
    [greeting] = sent(bot)
    expected = said("uz", "Welcome! You're joining <b>%(company)s</b>.") % {"company": company.name}
    assert greeting.text.startswith(expected)
    assert greeting.reply_markup.inline_keyboard[-1][0].text == LANGUAGE_BUTTON


async def test_the_old_first_contact_picker_still_works(dp, bot):
    """Chats from before 25.10.2026 may still show the three-language picker."""
    person = updates.tg_user(9_005)

    await dp.feed_update(bot, updates.pick_language(person, "en", mode="first"))

    assert (await User.objects.aget(telegram_id=9_005)).language == "en"
    assert sent(bot)[-1].text == GREETING
    assert any(isinstance(r, DeleteMessage) for r in bot.requests)  # the picker goes


async def test_language_command_relabels_the_whole_chat(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/language"))
    picker = sent(bot)[-1]
    assert picker.text == "Choose a language. Now: English."
    row = picker.reply_markup.inline_keyboard[0]
    assert [b.text for b in row] == ["O‘zbekcha", "Русский", "English"]
    assert [b.style for b in row] == [None, None, "success"]

    await dp.feed_update(bot, updates.pick_language(tg, "ru", mode="set"))

    [menu] = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert menu.scope.chat_id == worker.user.telegram_id
    assert menu.commands[0].description == said("ru", "Home")
    [button] = [r for r in bot.requests if isinstance(r, SetChatMenuButton)]
    assert button.chat_id == worker.user.telegram_id
    confirmation = sent(bot)[-1]
    assert confirmation.text.startswith("Теперь пишу по-русски")
    assert isinstance(confirmation.reply_markup, ReplyKeyboardMarkup)
    assert confirmation.reply_markup.keyboard[0][0].text == said("ru", "My tasks")


async def test_the_same_language_only_says_so(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)
    before = len(sent(bot))

    await dp.feed_update(bot, updates.pick_language(tg, "en", mode="set"))

    answer = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)][-1]
    assert answer.text == "English is already selected"
    assert len(sent(bot)) == before


@pytest.mark.parametrize("command", ["/til", "/lang", "/language"])
async def test_the_language_command_has_short_forms(dp, bot, company, member, command):
    worker = await member.aregistered(company)
    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), command))
    assert sent(bot)[-1].text == "Choose a language. Now: English."


async def test_help_and_settings(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/help"))
    assert sent(bot)[-1].text.startswith("<b>Here's what I can do:</b>\n")
    assert "/language" in sent(bot)[-1].text

    await dp.feed_update(bot, updates.message(tg, "/settings"))
    settings_reply = sent(bot)[-1]
    assert settings_reply.reply_markup.inline_keyboard[0][0].text == "Language: English"


async def test_someone_waiting_for_approval_can_change_the_language(dp, bot, company, member):
    waiting = await member.acreate(company, status=Membership.Status.PENDING)
    tg = updates.tg_user(waiting.user.telegram_id)

    await dp.feed_update(bot, updates.pick_language(tg, "uz", mode="set"))

    user = await sync_to_async(User.objects.get)(pk=waiting.user_id)
    assert user.language == "uz"
    assert sent(bot)  # their status, in Uzbek
