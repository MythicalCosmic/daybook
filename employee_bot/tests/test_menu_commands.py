from contextlib import contextmanager
from datetime import datetime

import pytest
from aiogram import F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Chat, Message, User

from apps.members import bot_menu
from apps.tasks.models import Task
from bot.commands import private_commands
from bot.deeplinks import register_start_param, unregister_start_param
from bot.handlers.features import applicants, attendance, finance
from bot.middlewares.menu_commands import (
    interrupts,
    is_menu_button,
    is_menu_command,
    menu_commands,
)
from tests import updates

ASKS_FOR_DUE = "When is it due?"


class Expense(StatesGroup):
    amount = State()


@contextmanager
def temporary_handler(observer, callback, *filters):
    observer.register(callback, *filters)
    try:
        yield
    finally:
        observer.handlers[:] = [h for h in observer.handlers if h.callback is not callback]


def text_message(text: str | None) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="Ali"),
        text=text,
    )


def test_the_menu_commands_are_the_private_menu():
    assert menu_commands() == {command.command for command in private_commands()}
    assert {"checkin", "expense", "pay", "kudos", "tasks", "new", "announce"} <= menu_commands()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/checkin", True),
        ("/checkin@daybook_test_bot", True),
        ("/CHECKIN", True),
        ("/pay now", True),
        ("/cancel", False),
        ("/", False),
        ("/ checkin", False),
        ("checkin", False),
        ("Order /checkin rolls", False),
        ("", False),
        (None, False),
    ],
)
def test_what_counts_as_a_menu_command(text, expected):
    assert is_menu_command(text_message(text)) is expected
    assert interrupts(text_message(text)) is expected


def test_start_is_left_to_the_start_router():
    assert is_menu_command(text_message("/start login_abc"))
    assert not interrupts(text_message("/start login_abc"))
    assert not interrupts(text_message("/start"))


def test_a_modules_menu_button_interrupts_in_any_language(monkeypatch):
    monkeypatch.setattr(bot_menu, "_buttons", {})
    bot_menu.register_menu_button("Members", order=10, visible=lambda member: True)

    assert is_menu_button(text_message("Members"))
    assert interrupts(text_message("Members"))
    assert interrupts(text_message("Xodimlar"))  # the same button for an Uzbek speaker
    assert not interrupts(text_message("Members of staff"))
    assert not is_menu_button(text_message(None))


pytestmark_db = pytest.mark.django_db(transaction=True)


@pytestmark_db
async def test_a_menu_command_ends_the_conversation_it_interrupts(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)
    heard = []

    async def checkin(message: Message) -> None:
        heard.append(message.text)
        await message.answer("checked in")

    with temporary_handler(attendance.router.message, checkin, Command("checkin")):
        await dp.feed_update(bot, updates.message(tg, "/new"))
        await dp.feed_update(bot, updates.message(tg, "/checkin"))

    assert heard == ["/checkin"]  # not the new task's title
    assert bot.sent_texts()[-1] == "checked in"

    await dp.feed_update(bot, updates.message(tg, "Order receipt rolls"))
    assert ASKS_FOR_DUE not in bot.sent_texts()[-1]  # the half-made task is gone
    assert not await Task.objects.filter(assignee=worker).aexists()


@pytestmark_db
async def test_a_menu_command_without_a_handler_yet_goes_home(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/new"))
    await dp.feed_update(bot, updates.message(tg, "/kudos"))

    assert "You're a member of" in bot.sent_texts()[-1]
    await dp.feed_update(bot, updates.message(tg, "Thanks Madina"))
    assert ASKS_FOR_DUE not in bot.sent_texts()[-1]


@pytestmark_db
async def test_a_menu_command_never_becomes_an_announcement(dp, bot, company, member):
    manager = await member.aregistered(company, "Manager")
    tg = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/announce"))
    await dp.feed_update(bot, updates.message(tg, "/expense"))

    assert "You're a member of" in bot.sent_texts()[-1]  # home, not a preview of "/expense"
    await dp.feed_update(bot, updates.message(tg, "Shop closes at 18:00 today"))
    assert "You're a member of" in bot.sent_texts()[-1]  # and the draft is gone


@pytestmark_db
async def test_other_commands_still_reach_the_conversation(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)
    context = dp.fsm.get_context(bot, chat_id=tg.id, user_id=tg.id)
    heard = []

    async def in_expense(message: Message) -> None:
        heard.append(message.text)

    with temporary_handler(finance.router.message, in_expense, Expense.amount, F.text):
        await context.set_state(Expense.amount)
        await dp.feed_update(bot, updates.message(tg, "/cancel"))
        assert heard == ["/cancel"]  # a feature's own command inside its conversation

        await dp.feed_update(bot, updates.message(tg, "/pay"))
        assert heard == ["/cancel"]
        assert await context.get_state() is None


@pytestmark_db
async def test_start_ends_the_conversation(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/new"))
    await dp.feed_update(bot, updates.message(tg, "/start"))
    await dp.feed_update(bot, updates.message(tg, "Order receipt rolls"))

    assert ASKS_FOR_DUE not in bot.sent_texts()[-1]
    assert not await Task.objects.filter(assignee=worker).aexists()


class Application(StatesGroup):
    answer = State()


@pytestmark_db
async def test_a_menu_command_ends_an_applicants_conversation_too(dp, bot):
    tg = updates.tg_user(721)  # not a member of anything
    context = dp.fsm.get_context(bot, chat_id=tg.id, user_id=tg.id)
    answers = []

    async def answer(message: Message) -> None:
        answers.append(message.text)

    with temporary_handler(applicants.router.message, answer, Application.answer, F.text):
        await context.set_state(Application.answer)
        await dp.feed_update(bot, updates.message(tg, "Two years at a bakery"))
        await dp.feed_update(bot, updates.message(tg, "/tasks"))

    assert answers == ["Two years at a bakery"]
    assert await context.get_state() is None


@pytestmark_db
async def test_a_deep_link_handler_decides_about_the_open_conversation(dp, bot):
    tg = updates.tg_user(722)
    context = dp.fsm.get_context(bot, chat_id=tg.id, user_id=tg.id)
    seen = []

    async def opened(message: Message, payload: str, *, user, state) -> None:
        seen.append(await state.get_state())

    register_start_param("keep_", opened)
    try:
        await context.set_state(Application.answer)
        await dp.feed_update(bot, updates.message(tg, "/start keep_1"))
        assert seen == [Application.answer.state]  # still there for the handler to use

        await dp.feed_update(bot, updates.message(tg, "/start"))  # plain /start: home
        assert await context.get_state() is None
    finally:
        unregister_start_param("keep_")
