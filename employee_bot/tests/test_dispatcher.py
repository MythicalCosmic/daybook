import importlib
import pkgutil
from contextlib import contextmanager

import pytest
from aiogram import F, Router
from aiogram.methods import EditMessageText
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async

from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import Proof
from apps.tasks.tests.factories import TaskFactory
from bot.handlers import features
from bot.handlers.features import applicants, finance, sales, signin
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
        "language",  # the language picker, /help and /settings: anyone may use them
        "company",  # the company switch of someone in several companies
        "feature_applicants",  # applicants aren't members; their contact isn't a join request
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
        "member-app",  # the menu's app buttons answer before a module handles its button's text
        "member_tasks",
        "member_new_task",
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


@pytest.mark.django_db(transaction=True)
async def test_feature_handlers_wait_until_the_member_has_registered(dp, bot, company, member):
    newcomer = await member.acreate(company)  # approved, but hasn't shared a phone yet
    heard = []

    async def ping(message: Message) -> None:
        heard.append(message.text)

    tg = updates.tg_user(newcomer.user.telegram_id)
    with temporary_handler(sales.router.message, ping, F.text == "ping"):
        await dp.feed_update(bot, updates.message(tg, "ping"))

    assert heard == []
    assert "Accounts are created in the app" in bot.sent_texts()[-1]  # home's registration prompt


# Rule 20: a photo nobody asked for never reaches a feature. Tasks answer it ("which task is
# this photo for?", research R1 C4); a caption tag (#xarajat) leaves it to its module. Once
# packages add photo handlers, these fail if one of them takes photos outside its own
# conversation or caption tag.


@pytest.mark.django_db(transaction=True)
async def test_photos_outside_a_conversation_are_asked_about_by_tasks(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)
    taken = []

    async def greedy(message: Message) -> None:
        taken.append(message.caption)

    with temporary_handler(finance.router.message, greedy, F.photo):
        await dp.feed_update(bot, updates.photo(tg))
        await dp.feed_update(bot, updates.photo(tg, caption="Shelf after restock"))

    assert taken == []
    assert len(bot.sent_texts()) == 2
    assert all("No task is waiting for a photo" in text for text in bot.sent_texts())


@pytest.mark.django_db(transaction=True)
async def test_a_proof_photo_reaches_its_task_before_any_feature(dp, bot, company, member):
    worker = await member.aregistered(company)
    task = await sync_to_async(TaskFactory)(assignee=worker, proof=Proof.PHOTO)
    tg = updates.tg_user(worker.user.telegram_id)
    taken = []

    async def greedy(message: Message) -> None:
        taken.append(message.caption)

    done = TaskCallback(action=TaskAction.DONE, task_id=task.pk).pack()
    with temporary_handler(finance.router.message, greedy, F.photo):
        await dp.feed_update(bot, updates.callback(tg, done))
        [prompt] = [r for r in bot.requests if isinstance(r, EditMessageText)]
        assert "Send a photo" in prompt.text  # the tapped card asks for it (research R1 C3)

        # Even with a caption a feature listens for: the task asked for this photo.
        await dp.feed_update(bot, updates.photo(tg, caption="#xarajat shelf"))
        assert taken == []

        # Outside the conversation the same photo does reach the feature.
        await dp.fsm.get_context(bot, chat_id=tg.id, user_id=tg.id).clear()
        await dp.feed_update(bot, updates.photo(tg, caption="#xarajat"))
    assert taken == ["#xarajat"]


@pytest.mark.django_db(transaction=True)
async def test_group_updates_never_reach_the_routers_before_the_group_router(dp, bot):
    reached = []

    async def record(event) -> None:
        reached.append(event)

    tg = updates.tg_user(611)
    with (
        temporary_handler(signin.router.message, record),
        temporary_handler(signin.router.callback_query, record),
        temporary_handler(applicants.router.message, record),
        temporary_handler(applicants.router.callback_query, record),
    ):
        await dp.feed_update(bot, updates.group_message(tg, "/hello"))
        await dp.feed_update(bot, updates.group_message(tg, "good morning"))
        await dp.feed_update(bot, updates.group_callback(tg, "test-signin"))
        assert reached == []

        await dp.feed_update(bot, updates.message(tg, "/hello"))  # private chats do reach them
    assert len(reached) == 1
