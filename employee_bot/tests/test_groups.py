import pytest
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    SetMyCommands,
)
from aiogram.types import BotCommandScopeAllGroupChats, User
from asgiref.sync import sync_to_async

from apps.accounts.models import User as Account
from apps.groups.callbacks import GroupAction, GroupCallback
from apps.groups.models import DEFAULT_EVENTS, GroupEvent, TelegramGroup, available_events
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members.tests.factories import PositionFactory
from apps.notifications.emoji import has_emoji
from bot.commands import set_commands
from tests import updates
from tests.mocked_bot import BOT_USERNAME

pytestmark = pytest.mark.django_db(transaction=True)

make_group = sync_to_async(TelegramGroupFactory)
make_position = sync_to_async(PositionFactory)


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def alerts(bot) -> list[str]:
    return [r.text for r in bot.requests if isinstance(r, AnswerCallbackQuery) and r.show_alert]


def toggles(markup) -> list[str]:
    return [row[0].text for row in markup.inline_keyboard]


def turned_on(markup) -> list[str]:
    """The switches that are on: they are green ("success"), with no mark in their words."""
    return [row[0].text for row in markup.inline_keyboard if row[0].style == "success"]


def press(action: GroupAction, event: str = "") -> str:
    return GroupCallback(action=action, event=event).pack()


async def linked(chat_id: int = updates.GROUP_ID) -> TelegramGroup | None:
    return await TelegramGroup.objects.filter(chat_id=chat_id, is_active=True).afirst()


@pytest.fixture
async def manager(company, member):
    return await member.aregistered(company, "Manager")


@pytest.fixture
async def worker(company, member):
    return await member.aregistered(company)


def tg(member) -> User:
    return updates.tg_user(member.user.telegram_id)


async def test_a_manager_adding_the_bot_links_the_group(dp, bot, company, manager):
    await dp.feed_update(bot, updates.bot_added(tg(manager)))

    group = await linked()
    assert group.company_id == company.pk
    assert group.title == "Shop team"
    assert group.events == DEFAULT_EVENTS
    [reply] = sent(bot)
    assert reply.chat_id == updates.GROUP_ID
    assert company.name in reply.text
    labels = toggles(reply.reply_markup)
    # every event the company can use, whose news, then Done
    assert len(labels) == len(available_events(company)) + 2
    assert not any(has_emoji(label) for label in labels)
    on = turned_on(reply.reply_markup)
    assert "Daily tasks done" in on  # on by default
    assert "Assigned tasks done" not in on
    # The text says what is on, for apps that show no button colours.
    assert "Turned on: Daily tasks done" in reply.text


async def test_anyone_else_adding_the_bot_gets_told_how_to_link_it(dp, bot, worker):
    await dp.feed_update(bot, updates.bot_added(tg(worker)))

    assert await linked() is None
    [reply] = sent(bot)
    assert "/connect" in reply.text


async def test_adding_the_bot_back_to_a_linked_group_stays_quiet(dp, bot, company, manager):
    await make_group(company=company, chat_id=updates.GROUP_ID)

    await dp.feed_update(bot, updates.bot_added(tg(manager)))

    assert sent(bot) == []


async def test_removing_the_bot_switches_the_group_off(dp, bot, company, manager):
    await make_group(company=company, chat_id=updates.GROUP_ID)

    await dp.feed_update(bot, updates.bot_removed(tg(manager)))

    assert await linked() is None


async def test_connect_needs_a_manager(dp, bot, company, manager, worker):
    await dp.feed_update(bot, updates.group_message(tg(worker), "/connect"))

    assert await linked() is None
    assert "manager" in sent(bot)[-1].text

    await dp.feed_update(bot, updates.group_message(tg(manager), "/connect"))

    assert (await linked()).company_id == company.pk
    assert company.name in sent(bot)[-1].text


async def test_connect_works_with_the_bots_username(dp, bot, company, manager):
    await dp.feed_update(bot, updates.group_message(tg(manager), f"/connect@{BOT_USERNAME}"))

    assert (await linked()).company_id == company.pk


async def test_anonymous_admins_are_asked_to_show_themselves(dp, bot, company, manager):
    await make_group(company=company, chat_id=updates.GROUP_ID)

    for command in ("/connect", "/settings", "/disconnect"):
        await dp.feed_update(bot, updates.group_message(updates.ANONYMOUS_ADMIN, command))

    replies = sent(bot)
    assert len(replies) == 3
    assert all("anonymous" in reply.text for reply in replies)
    assert await linked() is not None


async def test_a_manager_chooses_what_the_group_gets(dp, bot, company, manager):
    await make_group(company=company, chat_id=updates.GROUP_ID, events=[GroupEvent.LATE])

    await dp.feed_update(bot, updates.group_message(tg(manager), "/settings"))
    assert len(toggles(sent(bot)[-1].reply_markup)) == len(available_events(company)) + 2

    await dp.feed_update(
        bot, updates.group_callback(tg(manager), press(GroupAction.TOGGLE, GroupEvent.MORNING))
    )

    group = await linked()
    assert group.events == [GroupEvent.LATE, GroupEvent.MORNING]
    [edit] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert turned_on(edit.reply_markup) == ["Late tasks", "Morning plan"]
    assert "Turned on: Late tasks, Morning plan" in edit.text

    await dp.feed_update(bot, updates.group_callback(tg(manager), press(GroupAction.CLOSE)))

    done = [r for r in bot.requests if isinstance(r, EditMessageText)][-1]
    assert "Late tasks" in done.text
    assert "Morning plan" in done.text
    assert done.reply_markup is None


async def test_a_manager_narrows_the_group_to_some_positions(dp, bot, company, manager):
    group = await make_group(company=company, chat_id=updates.GROUP_ID)
    cashier = await make_position(company=company, name="Cashier")
    await make_position(company=company, name="Courier")

    await dp.feed_update(bot, updates.group_callback(tg(manager), press(GroupAction.WHO)))

    [picker] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert toggles(picker.reply_markup) == ["Cashier", "Courier", "Back"]

    await dp.feed_update(
        bot,
        updates.group_callback(
            tg(manager), GroupCallback(action=GroupAction.POSITION, position_id=cashier.pk).pack()
        ),
    )

    assert [p.pk async for p in group.positions.all()] == [cashier.pk]
    edit = [r for r in bot.requests if isinstance(r, EditMessageText)][-1]
    assert toggles(edit.reply_markup)[0] == "Cashier"
    assert turned_on(edit.reply_markup) == ["Cashier"]
    assert "Whose news: Cashier" in edit.text

    await dp.feed_update(bot, updates.group_callback(tg(manager), press(GroupAction.BACK)))

    back = [r for r in bot.requests if isinstance(r, EditMessageText)][-1]
    assert "Cashier" in toggles(back.reply_markup)[len(available_events(company))]


async def test_a_position_from_another_company_is_refused(dp, bot, company, other_company, manager):
    group = await make_group(company=company, chat_id=updates.GROUP_ID)
    foreign = await make_position(company=other_company)

    await dp.feed_update(
        bot,
        updates.group_callback(
            tg(manager), GroupCallback(action=GroupAction.POSITION, position_id=foreign.pk).pack()
        ),
    )

    assert alerts(bot)
    assert not await group.positions.aexists()


async def test_only_managers_change_the_settings(dp, bot, company, worker):
    await make_group(company=company, chat_id=updates.GROUP_ID, events=[GroupEvent.LATE])

    await dp.feed_update(bot, updates.group_message(tg(worker), "/settings"))
    assert "manager" in sent(bot)[-1].text
    assert sent(bot)[-1].reply_markup is None

    await dp.feed_update(
        bot, updates.group_callback(tg(worker), press(GroupAction.TOGGLE, GroupEvent.MORNING))
    )

    assert alerts(bot)
    assert (await linked()).events == [GroupEvent.LATE]
    assert not [r for r in bot.requests if isinstance(r, (EditMessageReplyMarkup, EditMessageText))]


async def test_settings_in_a_group_that_isnt_linked(dp, bot, manager):
    await dp.feed_update(bot, updates.group_message(tg(manager), "/settings"))

    assert "/connect" in sent(bot)[-1].text


async def test_a_manager_disconnects_the_group(dp, bot, company, manager):
    await make_group(company=company, chat_id=updates.GROUP_ID)

    await dp.feed_update(bot, updates.group_message(tg(manager), "/disconnect"))

    assert await linked() is None
    assert "/connect" in sent(bot)[-1].text


async def test_an_upgrade_to_a_supergroup_keeps_the_link(dp, bot, company, manager):
    old_id, new_id = -555, -1_000_555
    await make_group(company=company, chat_id=old_id, events=[GroupEvent.MORNING])
    old_chat = updates.group_chat(old_id, chat_type="group")

    await dp.feed_update(
        bot, updates.group_message(tg(manager), chat=old_chat, migrate_to_chat_id=new_id)
    )

    assert await linked(old_id) is None
    assert (await linked(new_id)).events == [GroupEvent.MORNING]


async def test_group_chatter_never_reaches_the_personal_menus(dp, bot, company, worker):
    await make_group(company=company, chat_id=updates.GROUP_ID)

    for text in ("My tasks", "/tasks", "/start", "hello everyone"):
        await dp.feed_update(bot, updates.group_message(tg(worker), text))

    assert sent(bot) == []


async def test_group_chatter_isnt_recorded(dp, bot, company):
    await make_group(company=company, chat_id=updates.GROUP_ID)
    stranger = updates.tg_user(777_000, first_name="Stranger")

    await dp.feed_update(bot, updates.group_message(stranger, "hi all"))

    assert not await Account.objects.filter(telegram_id=777_000).aexists()


async def test_the_command_menus(bot):
    await set_commands(bot)

    menus = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    group_menus = [m for m in menus if isinstance(m.scope, BotCommandScopeAllGroupChats)]
    assert len(menus) == 8  # private and group, by default and in each language
    assert {m.language_code for m in group_menus} == {None, "uz", "ru", "en"}
    assert [c.command for c in group_menus[0].commands] == ["connect", "settings", "disconnect"]
