"""`/new` in the owner bot: signup code → name → timezone → confirm → the company exists."""

import pytest
from aiogram.methods import SendMessage
from asgiref.sync import sync_to_async

from apps.companies.models import Branch, Company
from apps.finance.models import MoneyAccount
from apps.members.models import Membership
from apps.signin import signup
from ownerbot.callbacks import NewCompanyStep
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def last_text(bot) -> str:
    return bot.sent()[-1].text


def button(message: SendMessage, action: str, value: str = ""):
    for row in message.reply_markup.inline_keyboard:
        for item in row:
            if item.callback_data == NewCompanyStep(action=action, value=value).pack():
                return item
    raise AssertionError(f"no {action} button")


@sync_to_async
def make_code() -> str:
    return signup.create_code()[1]


@sync_to_async
def company_named(name: str) -> dict | None:
    company = Company.objects.filter(name=name).first()
    if company is None:
        return None
    owner = Membership.objects.select_related("role", "user").get(company=company)
    return {
        "company": company,
        "owner_is_owner": owner.role.is_owner,
        "owner_tg": owner.user.telegram_id,
        "branches": Branch.objects.filter(company=company).count(),
        "accounts": MoneyAccount.objects.filter(company=company).count(),
    }


async def test_new_with_a_signup_code_creates_the_company(dp, bot, settings):
    settings.COMPANY_SIGNUP = "code"
    settings.DASHBOARD_URL = "https://app.example.uz/dashboard/"
    person = updates.tg_user(7401, first_name="Malika")
    code = await make_code()

    await dp.feed_update(bot, updates.message(person, "/new"))
    assert "signup code" in last_text(bot)

    await dp.feed_update(bot, updates.message(person, "WRONG-CODE"))
    assert "isn't valid" in last_text(bot)

    await dp.feed_update(bot, updates.message(person, code.lower()))
    assert "What is your company called?" in last_text(bot)

    await dp.feed_update(bot, updates.message(person, "  Baraka   Market "))
    timezone_question = bot.sent()[-1]
    assert "Baraka Market" in timezone_question.text
    tashkent = button(timezone_question, "tz", "Asia/Tashkent")
    assert tashkent.text.startswith("")  # preselected

    await dp.feed_update(bot, updates.callback(person, tashkent.callback_data))
    confirm = bot.sent()[-1]
    assert "Create this company?" in confirm.text and "Asia/Tashkent" in confirm.text

    await dp.feed_update(bot, updates.callback(person, button(confirm, "create").callback_data))

    done = bot.sent()[-1]
    assert "Baraka Market is ready" in done.text
    [[get_started]] = done.reply_markup.inline_keyboard
    made = await company_named("Baraka Market")
    assert made is not None
    assert get_started.web_app.url == (
        f"https://app.example.uz/dashboard/c/{made['company'].pk}/get-started"
    )
    assert made["owner_is_owner"] and made["owner_tg"] == 7401
    assert made["branches"] == 1
    assert made["company"].timezone == "Asia/Tashkent"
    # company_created ran every module's defaults (finance's cash desk and terminal).
    assert made["accounts"] > 0
    assert await sync_to_async(signup.find)(code) is None  # the code is used up


async def test_a_deep_link_brings_the_code(dp, bot, settings):
    settings.COMPANY_SIGNUP = "code"
    code = await make_code()
    person = updates.tg_user(7402)

    await dp.feed_update(bot, updates.message(person, f"/start new_{signup.normalize(code)}"))

    assert "What is your company called?" in last_text(bot)


async def test_a_bad_deep_link_code_asks_for_one(dp, bot, settings):
    settings.COMPANY_SIGNUP = "code"

    await dp.feed_update(bot, updates.message(updates.tg_user(7403), "/start new_NOPE1234"))

    texts = [m.text for m in bot.sent()]
    assert "isn't valid" in texts[0] and "signup code" in texts[1]


async def test_open_signup_needs_no_code_and_takes_a_typed_timezone(dp, bot, settings):
    settings.COMPANY_SIGNUP = "open"
    person = updates.tg_user(7404, language_code="ru")  # who is answered in Russian

    await dp.feed_update(bot, updates.message(person, "/new"))
    assert "Как называется ваша компания?" in last_text(bot)
    await dp.feed_update(bot, updates.message(person, "Oqqayin Dorixona"))
    await dp.feed_update(bot, updates.callback(person, NewCompanyStep(action="type_tz").pack()))
    await dp.feed_update(bot, updates.message(person, "Mars"))
    assert "не знаю такого часового пояса" in last_text(bot)
    await dp.feed_update(bot, updates.message(person, "Samarqand"))
    confirm = bot.sent()[-1]
    assert "Asia/Samarkand" in confirm.text
    await dp.feed_update(bot, updates.callback(person, button(confirm, "create").callback_data))

    made = await company_named("Oqqayin Dorixona")
    assert made["company"].timezone == "Asia/Samarkand"
    assert made["company"].default_language == "ru"


async def test_signup_off_refuses(dp, bot, settings):
    settings.COMPANY_SIGNUP = "off"

    await dp.feed_update(bot, updates.message(updates.tg_user(7405), "/new"))

    assert "platform team" in last_text(bot)


async def test_cancel_and_stale_buttons(dp, bot, settings):
    settings.COMPANY_SIGNUP = "open"
    person = updates.tg_user(7406)
    await dp.feed_update(bot, updates.message(person, "/new"))
    await dp.feed_update(bot, updates.message(person, "Will cancel"))

    await dp.feed_update(bot, updates.callback(person, NewCompanyStep(action="cancel").pack()))
    await dp.feed_update(bot, updates.callback(person, NewCompanyStep(action="create").pack()))

    assert await company_named("Will cancel") is None


async def test_a_command_ends_the_conversation(dp, bot, settings, company, member):
    settings.COMPANY_SIGNUP = "open"
    person = updates.tg_user(7407)
    await dp.feed_update(bot, updates.message(person, "/new"))

    await dp.feed_update(bot, updates.message(person, "/today"))
    await dp.feed_update(bot, updates.message(person, "Not a company name"))

    # /today answered, and the next text wasn't taken as a company name.
    assert "dashboard access" in bot.sent()[1].text
    assert await company_named("Not a company name") is None
    assert len(bot.sent()) == 2


async def test_owners_add_companies_without_a_code(dp, bot, settings, company, member):
    settings.COMPANY_SIGNUP = "code"
    await sync_to_async(member)(company, "Owner", user__telegram_id=7408)

    await dp.feed_update(bot, updates.message(updates.tg_user(7408), "/new"))

    assert "What is your company called?" in last_text(bot)


async def test_someone_at_the_company_limit_hears_it_before_typing(
    dp, bot, settings, company, member
):
    settings.COMPANY_SIGNUP = "code"
    settings.MAX_COMPANIES_PER_USER = 1
    await sync_to_async(member)(company, "Owner", user__telegram_id=7409)

    await dp.feed_update(bot, updates.message(updates.tg_user(7409), "/new"))

    assert "the most one person can" in last_text(bot)
    assert len(bot.sent()) == 1
