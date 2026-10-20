import importlib
import pkgutil
from contextlib import contextmanager

import pytest
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.handlers import features
from bot.handlers.features import sales, signin
from tests import updates

# Every area router W0 creates; inbox_actions joins them once the platform track is merged.
AREAS = [
    "sales",
    "attendance",
    "finance",
    "payroll",
    "hr",
    "ai",
    "recognition",
    "projects",
    "lifecycle",
    "knowledge",
    "agenda",
    "crm",
]


def names(router: Router) -> list[str]:
    return [sub.name for sub in router.sub_routers]


def test_dispatcher_handles_messages_and_callbacks(dp):
    used = dp.resolve_used_update_types()

    assert {"message", "callback_query", "my_chat_member"} <= set(used)


def test_top_level_order(dp):
    assert names(dp) == [
        "feature_signin",  # sign-in and deep links work for anyone, member or not
        "start",
        "approvals",
        "time_off",
        "contact",
        "groups",  # group chats before the member gate, which answers everything it gets
        "member",
    ]


def test_feature_routers_sit_between_the_state_bound_routers_and_home(dp):
    [member] = [sub for sub in dp.sub_routers if sub.name == "member"]
    inside = [name for name in names(member) if name != "feature_inbox_actions"]

    assert inside == [
        "member_tasks",
        "member_announcements",
        *(f"feature_{area}" for area in AREAS),
        "member_home",
    ]


def test_every_feature_module_is_registered_once(dp):
    def all_names(router: Router) -> list[str]:
        return [router.name] + [name for sub in router.sub_routers for name in all_names(sub)]

    registered = all_names(dp)
    for module in pkgutil.iter_modules(features.__path__):
        router = importlib.import_module(f"{features.__name__}.{module.name}").router
        assert registered.count(router.name) == 1, module.name
        assert router.name == f"feature_{module.name}"


@contextmanager
def temporary_handler(observer, callback, *filters):
    """A handler on one of the real routers, removed again afterwards."""
    observer.register(callback, *filters)
    try:
        yield
    finally:
        observer.handlers[:] = [h for h in observer.handlers if h.callback is not callback]


# Handlers reach the ORM from worker threads, so test data must really be committed.
@pytest.mark.django_db(transaction=True)
async def test_signin_buttons_reach_people_without_a_membership(dp, bot):
    pressed = []

    async def confirm(callback: CallbackQuery) -> None:
        pressed.append(callback.data)
        await callback.answer()

    with temporary_handler(signin.router.callback_query, confirm, F.data == "test-signin"):
        await dp.feed_update(bot, updates.callback(updates.tg_user(601), "test-signin"))

    assert pressed == ["test-signin"]


@pytest.mark.django_db(transaction=True)
async def test_a_feature_handler_answers_members_before_home(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    async def ping(message: Message) -> None:
        await message.answer("sales heard you")

    def heard() -> int:
        return bot.sent_texts().count("sales heard you")

    with temporary_handler(sales.router.message, ping, F.text == "ping"):
        await dp.feed_update(bot, updates.message(tg, "ping"))
        assert heard() == 1

        # Someone who isn't a member is stopped at the gate first.
        await dp.feed_update(bot, updates.message(updates.tg_user(603), "ping"))
        assert heard() == 1

    await dp.feed_update(bot, updates.message(tg, "ping"))
    assert heard() == 1  # home answers once the handler is gone
    assert len(bot.sent_texts()) == 3
