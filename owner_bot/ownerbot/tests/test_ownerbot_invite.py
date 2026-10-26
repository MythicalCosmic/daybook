"""`/invite`: invite links as QR codes, and a team link made in three taps."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import EditMessageCaption, EditMessageText, SendPhoto
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.companies.tests.factories import BranchFactory, CompanyFactory
from apps.members import join_links
from apps.members.models import JoinLink
from apps.notifications.emoji import has_emoji
from ownerbot.callbacks import InviteAct, InviteNew
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def owner(company, member, settings):
    settings.EMPLOYEE_BOT_USERNAME = "team_bot"
    company.name = "Demo Dorixona"
    company.save()
    return member(company, "Owner", user__telegram_id=7601, user__first_name="Dilnoza")


def photos(bot) -> list[SendPhoto]:
    return [request for request in bot.requests if isinstance(request, SendPhoto)]


def edits(bot) -> list[EditMessageText]:
    return [request for request in bot.requests if isinstance(request, EditMessageText)]


async def test_invite_lists_the_main_link_and_working_team_links(dp, bot, owner):
    await sync_to_async(join_links.create_link)(
        owner.company, by=owner, name="Staff meeting", max_uses=20
    )
    ended = await sync_to_async(join_links.create_link)(owner.company, by=owner, name="Old")
    await sync_to_async(join_links.update_link)(ended, by=owner, is_active=False)

    await dp.feed_update(bot, updates.message(updates.tg_user(7601), "/invite"))

    [reply] = bot.sent()
    assert "<b>Invite staff</b> · Demo Dorixona" in reply.text
    assert "Staff meeting · Joined: 0 of 20" in reply.text
    assert "Old" not in reply.text  # stopped links aren't offered
    assert not has_emoji(reply.text)
    labels = [row[0].text for row in reply.reply_markup.inline_keyboard]
    assert labels == ["Main link QR code", "Staff meeting · 0/20", "New team link"]


async def test_the_main_link_comes_as_a_qr_code(dp, bot, owner):
    tap = InviteAct(action="main", company=owner.company_id).pack()

    await dp.feed_update(bot, updates.callback(updates.tg_user(7601), tap))

    [photo] = photos(bot)
    assert photo.photo.data.startswith(PNG)
    assert "the main invite link" in photo.caption
    assert f"https://t.me/team_bot?start=c_{owner.company.invite_code}" in photo.caption
    share = photo.reply_markup.inline_keyboard[0][0]
    assert share.url.startswith("https://t.me/share/url?")


async def test_a_team_link_is_made_in_three_taps(dp, bot, owner):
    yunusobod = await sync_to_async(BranchFactory)(company=owner.company, name="Yunusobod")
    dilnoza = updates.tg_user(7601)

    await dp.feed_update(bot, updates.callback(dilnoza, InviteNew(company=owner.company_id).pack()))
    assert "Which branch will these people work in?" in edits(bot)[-1].text
    branch_buttons = [b.text for row in edits(bot)[-1].reply_markup.inline_keyboard for b in row]
    assert "Yunusobod" in branch_buttons

    step = InviteNew(company=owner.company_id, branch=yunusobod.pk)
    await dp.feed_update(bot, updates.callback(dilnoza, step.pack()))
    assert "How many people will join through it?" in edits(bot)[-1].text

    step = step.model_copy(update={"places": 20})
    await dp.feed_update(bot, updates.callback(dilnoza, step.pack()))
    assert "How long should it work?" in edits(bot)[-1].text

    step = step.model_copy(update={"days": 7})
    await dp.feed_update(bot, updates.callback(dilnoza, step.pack()))

    link = await JoinLink.objects.select_related("branch").aget(company=owner.company)
    assert link.branch == yunusobod
    assert link.max_uses == 20
    assert link.auto_approve is True
    assert timedelta(days=6, hours=23) < link.expires_at - timezone.now() <= timedelta(days=7)
    assert link.name.startswith("Yunusobod · ")
    [photo] = photos(bot)
    assert photo.photo.data.startswith(PNG)
    assert "People who open it join straight away." in photo.caption
    assert "Branch: Yunusobod" in photo.caption
    assert "Joined: 0 of 20" in photo.caption
    assert link.link in photo.caption
    assert not has_emoji(photo.caption)


async def test_with_one_branch_the_bot_skips_that_question(dp, bot, owner):
    await dp.feed_update(
        bot,
        updates.callback(updates.tg_user(7601), InviteNew(company=owner.company_id).pack()),
    )

    assert "How many people will join through it?" in edits(bot)[-1].text


async def test_until_tonight_ends_at_midnight_in_the_company(dp, bot, owner):
    step = InviteNew(company=owner.company_id, branch=0, places=0, days=0)

    await dp.feed_update(bot, updates.callback(updates.tg_user(7601), step.pack()))

    link = await JoinLink.objects.aget(company=owner.company)
    local = timezone.localtime(link.expires_at, ZoneInfo(owner.company.timezone))
    assert (local.hour, local.minute) == (0, 0)
    assert link.max_uses is None


async def test_stopping_a_link_from_its_qr_code(dp, bot, owner):
    link = await sync_to_async(join_links.create_link)(owner.company, by=owner, name="Meeting")
    tap = InviteAct(action="stop", company=owner.company_id, link=link.pk).pack()

    await dp.feed_update(bot, updates.callback(updates.tg_user(7601), tap))

    await link.arefresh_from_db()
    assert link.is_active is False
    [edit] = [r for r in bot.requests if isinstance(r, EditMessageCaption)]
    assert "The link is stopped." in edit.caption
    assert "Nobody new can join" in bot.answers()[-1].text


async def test_people_who_cant_approve_get_no_links(dp, bot, company, member):
    await sync_to_async(member)(company, "Accountant", user__telegram_id=7602)

    await dp.feed_update(bot, updates.message(updates.tg_user(7602), "/invite"))

    assert "can't invite people" in bot.sent()[-1].text


async def test_with_several_companies_invite_asks_which(dp, bot, owner, member):
    other = await sync_to_async(CompanyFactory)(name="Demo Distribyutor")
    await sync_to_async(member)(other, "Owner", user=owner.user)

    await dp.feed_update(bot, updates.message(updates.tg_user(7601), "/invite"))

    reply = bot.sent()[-1]
    assert "Which company" in reply.text
    assert [row[0].text for row in reply.reply_markup.inline_keyboard] == [
        "Demo Distribyutor",
        "Demo Dorixona",
    ]
