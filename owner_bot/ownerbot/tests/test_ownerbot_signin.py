"""Dashboard sign-in confirmed in the owner bot: number matching, "Log out everywhere"."""

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText
from asgiref.sync import sync_to_async
from django.test import RequestFactory
from django.utils import translation

from apps.signin import bot_messages as signin_messages
from apps.signin import links, services
from apps.signin.callbacks import NOT_ME, LoginTap, SessionsAction
from apps.signin.models import DeviceSession, LoginLink
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

OWNER_TG = 7301


@pytest.fixture
def usernames(settings):
    settings.OWNER_BOT_USERNAME = "owner_test_bot"
    settings.OWNER_BOT_TOKEN = "43:OWNER-TEST"


@pytest.fixture
def owner(company, member, usernames):
    return member(company, "Owner", user__telegram_id=OWNER_TG)


@sync_to_async
def new_link() -> links.NewLink:
    request = RequestFactory().post(
        "/",
        HTTP_USER_AGENT="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Version/18.6 Safari/605",
        REMOTE_ADDR="84.54.71.203",
    )
    return links.create_link(request)


@sync_to_async
def link_status(made: links.NewLink) -> str:
    return LoginLink.objects.get(pk=made.link.pk).status


async def test_start_login_offers_three_numbers_and_the_right_one_approves(dp, bot, owner):
    made = await new_link()
    person = updates.tg_user(OWNER_TG)

    await dp.feed_update(bot, updates.message(person, f"/start login_{made.code}"))

    [prompt] = bot.sent()
    assert "Sign in to the dashboard?" in prompt.text
    assert "Safari · macOS" in prompt.text and "84.54.x.x" in prompt.text
    numbers, [not_me] = prompt.reply_markup.inline_keyboard
    assert made.link.match_code in [button.text for button in numbers]
    assert LoginTap.unpack(not_me.callback_data).pick == NOT_ME

    right = next(b for b in numbers if b.text == made.link.match_code)
    await dp.feed_update(bot, updates.callback(person, right.callback_data))

    assert await link_status(made) == LoginLink.Status.APPROVED
    [edited] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert "Confirmed" in edited.text and edited.reply_markup is None


async def test_a_wrong_number_denies(dp, bot, owner):
    made = await new_link()
    person = updates.tg_user(OWNER_TG)
    await dp.feed_update(bot, updates.message(person, f"/start login_{made.code}"))
    numbers = bot.sent()[0].reply_markup.inline_keyboard[0]

    wrong = next(b for b in numbers if b.text != made.link.match_code)
    await dp.feed_update(bot, updates.callback(person, wrong.callback_data))

    assert await link_status(made) == LoginLink.Status.DENIED
    [edited] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert "cancelled" in edited.text


async def test_it_wasnt_me(dp, bot, owner):
    made = await new_link()
    person = updates.tg_user(OWNER_TG)

    await dp.feed_update(
        bot, updates.callback(person, LoginTap(link=made.link.pk.hex, pick=NOT_ME).pack())
    )

    assert await link_status(made) == LoginLink.Status.DENIED


async def test_someone_without_dashboard_access_is_told_why(dp, bot, company, member, usernames):
    await sync_to_async(member)(company, "Employee", user__telegram_id=7302)
    made = await new_link()

    await dp.feed_update(bot, updates.message(updates.tg_user(7302), f"/start login_{made.code}"))

    [reply] = bot.sent()
    assert "don't have access" in reply.text and reply.reply_markup is None
    assert await link_status(made) == LoginLink.Status.PENDING


async def test_a_stranger_who_never_used_the_bot_is_refused(dp, bot, usernames):
    made = await new_link()

    await dp.feed_update(bot, updates.message(updates.tg_user(7399), f"/start login_{made.code}"))

    # Someone new hears it in Uzbek first.
    with translation.override("uz"):
        assert bot.sent()[0].text == signin_messages.link_refused("no_access")


async def test_an_unknown_code(dp, bot, owner):
    await dp.feed_update(bot, updates.message(updates.tg_user(OWNER_TG), "/start login_nope"))

    assert "isn't valid" in bot.sent()[0].text


@sync_to_async
def two_sessions(user):
    request = RequestFactory().post(
        "/", HTTP_USER_AGENT="Chrome/141 Windows", REMOTE_ADDR="10.1.1.1"
    )
    first = services.issue_session(user, request)
    services.issue_session(user, request)
    return first.session


@sync_to_async
def active_sessions(user) -> int:
    return DeviceSession.objects.filter(user=user, revoked_at__isnull=True).count()


async def test_log_out_everywhere_from_the_signed_in_message(dp, bot, owner):
    session = await two_sessions(owner.user)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(OWNER_TG), SessionsAction(action="all", session=session.pk).pack()
        ),
    )

    assert await active_sessions(owner.user) == 0
    [answer] = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)]
    assert answer.show_alert and "every device" in answer.text
    assert any(isinstance(r, EditMessageReplyMarkup) for r in bot.requests)
