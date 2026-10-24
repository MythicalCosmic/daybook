"""The bot's language (research R1 L1 to L5): asked once at first contact unless Telegram is in
Uzbek, changed any time with /language, and the whole chat follows: replies, the command menu,
the menu button and the reply keyboard."""

import pytest
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    SendMessage,
    SetChatMenuButton,
    SetMyCommands,
)
from aiogram.types import BotCommandScopeChat, ReplyKeyboardMarkup
from asgiref.sync import sync_to_async
from django.utils import translation
from django.utils.translation import gettext

from apps.accounts.models import User
from apps.accounts.telegram_chat import FIRST_PICK
from apps.members.models import Membership
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

GREETING = "👋 Hi! To join your company, open the invite link your manager sent you."


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def said(language: str, msgid: str) -> str:
    with translation.override(language):
        return gettext(msgid)


@pytest.mark.parametrize("telegram_language", ["ru", "en", "de"])
async def test_a_new_person_picks_the_language_first(dp, bot, telegram_language):
    person = updates.tg_user(9_001, language_code=telegram_language)

    await dp.feed_update(bot, updates.message(person, "/start"))

    [picker] = sent(bot)
    assert picker.text == FIRST_PICK  # all three at once: their language isn't known yet
    assert [b.text for b in picker.reply_markup.inline_keyboard[0]] == [
        "O‘zbekcha",
        "Русский",
        "English",
    ]


async def test_uzbek_telegram_gets_the_welcome_with_the_other_two(dp, bot):
    person = updates.tg_user(9_002, language_code="uz")

    await dp.feed_update(bot, updates.message(person, "/start"))

    [reply] = sent(bot)
    assert reply.text == said("uz", GREETING)
    assert [b.text for b in reply.reply_markup.inline_keyboard[-1]] == ["Русский", "English"]


async def test_the_choice_is_kept_and_the_welcome_follows_in_it(dp, bot):
    person = updates.tg_user(9_003, language_code="ru")
    await dp.feed_update(bot, updates.message(person, "/start"))

    await dp.feed_update(bot, updates.pick_language(person, "ru"))

    assert (await User.objects.aget(telegram_id=9_003)).language == "ru"
    assert sent(bot)[-1].text == said("ru", GREETING)
    assert any(isinstance(r, DeleteMessage) for r in bot.requests)  # the picker goes
    [menu] = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert isinstance(menu.scope, BotCommandScopeChat) and menu.scope.chat_id == 9_003


async def test_an_invite_survives_the_picker(dp, bot, company):
    person = updates.tg_user(9_004, language_code="ru")
    await dp.feed_update(bot, updates.message(person, f"/start {company.invite_start_param}"))
    assert not await Membership.objects.filter(user__telegram_id=9_004).aexists()

    await dp.feed_update(bot, updates.pick_language(person, "en"))

    assert await Membership.objects.filter(user__telegram_id=9_004, company=company).aexists()
    assert "You're joining" in sent(bot)[-1].text


async def test_the_uzbek_welcome_switches_in_place(dp, bot):
    person = updates.tg_user(9_005, language_code="uz")
    await dp.feed_update(bot, updates.message(person, "/start"))

    await dp.feed_update(bot, updates.pick_language(person, "en", mode="welcome"))

    assert (await User.objects.aget(telegram_id=9_005)).language == "en"
    assert len(sent(bot)) == 1  # edited, not sent again


async def test_language_command_relabels_the_whole_chat(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/language"))
    picker = sent(bot)[-1]
    assert [b.text for b in picker.reply_markup.inline_keyboard[0]] == [
        "O‘zbekcha",
        "Русский",
        "✓ English",
    ]

    await dp.feed_update(bot, updates.pick_language(tg, "ru", mode="set"))

    [menu] = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert menu.scope.chat_id == worker.user.telegram_id
    assert menu.commands[0].description == said("ru", "Home")
    [button] = [r for r in bot.requests if isinstance(r, SetChatMenuButton)]
    assert button.chat_id == worker.user.telegram_id
    confirmation = sent(bot)[-1]
    assert confirmation.text.startswith("✅ Теперь пишу по-русски")
    assert isinstance(confirmation.reply_markup, ReplyKeyboardMarkup)
    assert confirmation.reply_markup.keyboard[0][0].text == said("ru", "📋 My tasks")


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
    assert sent(bot)[-1].text == "🌐 Choose a language:"


async def test_help_and_settings(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/help"))
    assert "/language" in sent(bot)[-1].text

    await dp.feed_update(bot, updates.message(tg, "/settings"))
    settings_reply = sent(bot)[-1]
    assert settings_reply.reply_markup.inline_keyboard[0][0].text == "🌐 Language: English ›"


async def test_someone_waiting_for_approval_can_change_the_language(dp, bot, company, member):
    waiting = await member.acreate(company, status=Membership.Status.PENDING)
    tg = updates.tg_user(waiting.user.telegram_id)

    await dp.feed_update(bot, updates.pick_language(tg, "uz", mode="set"))

    user = await sync_to_async(User.objects.get)(pk=waiting.user_id)
    assert user.language == "uz"
    assert sent(bot)  # their status, in Uzbek
