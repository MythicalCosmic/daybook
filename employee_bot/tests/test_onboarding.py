import pytest
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from apps.accounts.models import User
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def last_message(bot) -> SendMessage:
    return [r for r in bot.requests if isinstance(r, SendMessage)][-1]


async def test_approved_but_unregistered_member_is_sent_to_create_an_account(
    dp, bot, company, member, settings
):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com"
    newcomer = await member.acreate(company)

    await dp.feed_update(bot, updates.message(updates.tg_user(newcomer.user.telegram_id), "hi"))

    reply = last_message(bot)
    assert "create your account" in reply.text
    assert reply.reply_markup.inline_keyboard[0][0].web_app.url == "https://app.example.com"


async def test_sharing_own_contact_saves_a_verified_phone(dp, bot, company, member, settings):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com"
    newcomer = await member.acreate(company)
    tg_user = updates.tg_user(newcomer.user.telegram_id)

    await dp.feed_update(bot, updates.contact(tg_user, "998 90 123-45-67"))

    user = await User.objects.aget(pk=newcomer.user_id)
    assert user.phone == "+998901234567"
    reply = last_message(bot)
    assert "phone number is saved" in reply.text
    assert isinstance(reply.reply_markup, InlineKeyboardMarkup)
    assert reply.reply_markup.inline_keyboard[0][0].web_app.url == "https://app.example.com"


async def test_someone_elses_contact_is_not_saved(dp, bot, company, member):
    newcomer = await member.acreate(company)
    tg_user = updates.tg_user(newcomer.user.telegram_id)

    await dp.feed_update(bot, updates.contact(tg_user, "+998900000000", owner_id=123))

    user = await User.objects.aget(pk=newcomer.user_id)
    assert user.phone == ""
    reply = last_message(bot)
    assert "your own phone number" in reply.text
    assert isinstance(reply.reply_markup, ReplyKeyboardMarkup)
    assert reply.reply_markup.keyboard[0][0].request_contact


async def test_pending_people_share_their_phone_while_creating_an_account(dp, bot, company):
    tg_user = updates.tg_user(601)
    await dp.feed_update(bot, updates.message(tg_user, f"/start {company.invite_start_param}"))

    await dp.feed_update(bot, updates.contact(tg_user, "+998901234567"))

    user = await User.objects.aget(telegram_id=601)
    assert user.phone == "+998901234567"
    assert "phone number is saved" in last_message(bot).text


async def test_strangers_cannot_store_a_phone(dp, bot, db):
    tg_user = updates.tg_user(602)

    await dp.feed_update(bot, updates.contact(tg_user, "+998901234567"))

    user = await User.objects.aget(telegram_id=602)
    assert user.phone == ""
    assert "open the invite link" in last_message(bot).text
