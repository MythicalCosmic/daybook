"""Team links in the employee bot: `/start j_…` from one QR code that many people scan."""

from datetime import timedelta

import pytest
from aiogram.methods import SendMessage
from aiogram.types import ReplyKeyboardMarkup
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.members import join_links, services
from apps.members.models import JoinLink, Membership
from apps.members.tests.factories import MembershipFactory
from tests import updates

# Handlers reach the ORM from worker threads, so test data must really be committed.
pytestmark = pytest.mark.django_db(transaction=True)


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


async def make_link(company, member, **fields):
    owner = await member.aregistered(company, "Owner")
    fields.setdefault("name", "Staff meeting")
    return await sync_to_async(join_links.create_link)(company, by=owner, **fields)


async def test_a_team_link_says_there_is_no_waiting(dp, bot, company, member, settings):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com"
    link = await make_link(company, member)
    ali = updates.tg_user(601)

    await dp.feed_update(bot, updates.message(ali, f"/start {link.start_param}"))
    await dp.feed_update(bot, updates.pick_language(ali))  # in English from here

    membership = await Membership.objects.aget(company=company, user__telegram_id=601)
    assert membership.status == Membership.Status.PENDING
    assert membership.join_link_id == link.pk
    reply = sent(bot)[-1]
    assert "You're joining" in reply.text
    assert "you're on the team: no waiting" in reply.text
    assert reply.reply_markup.inline_keyboard[0][0].web_app.url == "https://app.example.com"


async def test_a_link_that_asks_first_promises_nothing(dp, bot, company, member, settings):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.com"
    link = await make_link(company, member, auto_approve=False)
    ali = updates.tg_user(602)

    await dp.feed_update(bot, updates.message(ali, f"/start {link.start_param}"))
    await dp.feed_update(bot, updates.pick_language(ali))

    assert "no waiting" not in sent(bot)[-1].text


async def test_an_ended_link_is_explained_in_uzbek_to_someone_new(dp, bot, company, member):
    link = await make_link(company, member)
    await JoinLink.objects.filter(pk=link.pk).aupdate(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    nobody = updates.tg_user(603)

    await dp.feed_update(bot, updates.message(nobody, f"/start {link.start_param}"))

    assert "muddati tugagan" in bot.sent_texts()[-1]
    assert not await Membership.objects.filter(user__telegram_id=603).aexists()


async def test_finishing_the_account_brings_the_welcome_and_the_menu(
    dp, bot, company, member, sent_messages
):
    link = await make_link(company, member)
    ali = updates.tg_user(604)
    await dp.feed_update(bot, updates.message(ali, f"/start {link.start_param}"))
    membership = await Membership.objects.select_related("user").aget(user__telegram_id=604)
    membership.user.phone = "+998901234567"
    await membership.user.asave()

    await sync_to_async(services.complete_onboarding)(
        membership, first_name="Ali", last_name="Valiyev", position_id=None
    )

    [welcome] = [m for m in sent_messages if m["chat_id"] == 604]
    assert "Ali" in welcome["text"]
    assert ReplyKeyboardMarkup.model_validate(welcome["reply_markup"]).keyboard  # the main menu


async def test_someone_waiting_who_scans_the_link_is_let_in_at_once(dp, bot, company, member):
    link = await make_link(company, member)
    waiting = await sync_to_async(MembershipFactory)(
        company=company,
        onboarded_at=timezone.now(),
        first_name="Laylo",
        user__telegram_id=605,
        user__language="en",
    )

    await dp.feed_update(bot, updates.message(updates.tg_user(605), f"/start {link.start_param}"))

    await waiting.arefresh_from_db()
    assert waiting.status == Membership.Status.APPROVED
    reply = sent(bot)[-1]
    assert "Welcome to the team, Laylo!" in reply.text
    assert isinstance(reply.reply_markup, ReplyKeyboardMarkup)
    # The chat's answer is the welcome: no second one comes from the backend.
    assert sum("Welcome to the team" in text for text in bot.sent_texts()) == 1
