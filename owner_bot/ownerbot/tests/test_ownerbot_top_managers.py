"""The owner bot is for owners and top managers; other managers are sent to the staff bot."""

import pytest
from asgiref.sync import sync_to_async

from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


async def test_a_branch_manager_is_pointed_to_the_staff_bot(dp, bot, company, member, settings):
    settings.EMPLOYEE_BOT_USERNAME = "staff_bot"
    role = await sync_to_async(AccessRoleFactory)(
        company=company, permissions=[Perm.DASHBOARD_ACCESS, Perm.TASKS_ASSIGN]
    )
    await sync_to_async(member.registered)(company, role.name, user__telegram_id=7701)

    await dp.feed_update(bot, updates.message(updates.tg_user(7701), "/start"))

    assert "for owners and top managers" in bot.sent()[-1].text
    assert "@staff_bot" in bot.sent()[-1].text


async def test_the_owner_still_gets_their_companies(dp, bot, company, member):
    await sync_to_async(member.registered)(company, "Owner", user__telegram_id=7702)

    await dp.feed_update(bot, updates.message(updates.tg_user(7702), "/start"))

    assert company.name in bot.sent()[-1].text
