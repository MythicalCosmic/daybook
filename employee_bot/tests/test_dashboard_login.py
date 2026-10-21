"""Dashboard sign-in through the employee bot while the owner bot has no token (§7.1)."""

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from asgiref.sync import sync_to_async
from django.test import RequestFactory

from apps.signin import links, services
from apps.signin.callbacks import NOT_ME, LoginTap, SessionsAction
from apps.signin.models import DeviceSession, LoginLink
from bot import deeplinks
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

OWNER_TG = 8801


@pytest.fixture
def employee_bot_only(settings):
    settings.OWNER_BOT_TOKEN = ""
    settings.EMPLOYEE_BOT_USERNAME = "daybook_test_bot"
    settings.EMPLOYEE_BOT_TOKEN = "42:TEST"


@pytest.fixture
def owner(company, member, employee_bot_only):
    return member.registered(company, "Owner", user__telegram_id=OWNER_TG)


@sync_to_async
def new_link() -> links.NewLink:
    request = RequestFactory().post(
        "/", HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Chrome/141.0", REMOTE_ADDR="213.230.1.9"
    )
    return links.create_link(request)


@sync_to_async
def status_of(made) -> str:
    return LoginLink.objects.get(pk=made.link.pk).status


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def test_login_is_a_registered_deep_link():
    assert "login_" in deeplinks.registered_prefixes()
    handler, payload = deeplinks.resolve("login_abcDEF-123")
    assert handler is not None
    assert payload == "abcDEF-123"


async def test_the_employee_bot_confirms_with_the_right_number(dp, bot, owner):
    made = await new_link()
    assert made.deep_link.startswith("https://t.me/daybook_test_bot?start=login_")
    person = updates.tg_user(OWNER_TG)

    await dp.feed_update(bot, updates.message(person, f"/start login_{made.code}"))

    [prompt] = sent(bot)
    assert "Chrome · Windows" in prompt.text and "213.230.x.x" in prompt.text
    numbers = prompt.reply_markup.inline_keyboard[0]
    right = next(b for b in numbers if b.text == made.link.match_code)

    await dp.feed_update(bot, updates.callback(person, right.callback_data))

    assert await status_of(made) == LoginLink.Status.APPROVED
    [edited] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert "Confirmed" in edited.text


async def test_a_wrong_number_or_not_me_denies(dp, bot, owner):
    made = await new_link()
    person = updates.tg_user(OWNER_TG)
    wrong = next(n for n in ("11", "12") if n != made.link.match_code)

    await dp.feed_update(
        bot, updates.callback(person, LoginTap(link=made.link.pk.hex, pick=wrong).pack())
    )
    assert await status_of(made) == LoginLink.Status.DENIED

    other = await new_link()
    await dp.feed_update(
        bot, updates.callback(person, LoginTap(link=other.link.pk.hex, pick=NOT_ME).pack())
    )
    assert await status_of(other) == LoginLink.Status.DENIED


async def test_people_who_are_not_members_get_a_clear_answer(dp, bot, employee_bot_only):
    made = await new_link()

    await dp.feed_update(bot, updates.message(updates.tg_user(8899), f"/start login_{made.code}"))

    [reply] = sent(bot)
    assert "don't have access" in reply.text


async def test_a_conversation_in_progress_does_not_swallow_the_link(dp, bot, owner):
    made = await new_link()
    person = updates.tg_user(OWNER_TG)
    # Start creating a task (a conversation waiting for its title)…
    await dp.feed_update(bot, updates.message(person, "➕ New task"))

    await dp.feed_update(bot, updates.message(person, f"/start login_{made.code}"))

    assert any("Sign in to the dashboard?" in m.text for m in sent(bot))


@sync_to_async
def signed_in_twice(user):
    request = RequestFactory().post("/", HTTP_USER_AGENT="Safari", REMOTE_ADDR="10.0.0.1")
    services.issue_session(user, request)
    return services.issue_session(user, request).session


@sync_to_async
def active(user) -> int:
    return DeviceSession.objects.filter(user=user, revoked_at__isnull=True).count()


async def test_log_out_everywhere_button(dp, bot, owner):
    session = await signed_in_twice(owner.user)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(OWNER_TG), SessionsAction(action="all", session=session.pk).pack()
        ),
    )

    assert await active(owner.user) == 0
    [answer] = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)]
    assert answer.show_alert
