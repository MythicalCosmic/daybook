"""Fixtures for the Davomat bot's tests. Everything lives inside `davomat_bot.tests`, so nothing
clashes with the other bots' test packages.

The organization is "Namuna MChJ" with attendance on; `linked(role, telegram_id, …)` makes a
person whose Telegram is linked (as `/start link_<code>` leaves them)."""

import asyncio

import pytest
from asgiref.sync import sync_to_async
from django.db import connections

from apps.core.bot_runtime import close_database_threads
from apps.notifications.tests.telegram_checks import report
from davomat_bot.dispatcher import create_dispatcher
from davomat_bot.tests.mocked_bot import MockedBot


@pytest.fixture(scope="session")
def dp():
    # Routers are module-level singletons and attach to one dispatcher only.
    return create_dispatcher()


@pytest.fixture
async def bot():
    mocked = MockedBot()
    yield mocked
    # Handlers query from the bots' database threads (apps.core.bot_runtime) and asgiref's own
    # thread; close their connections so the test database can be dropped at the end.
    await asyncio.to_thread(close_database_threads)
    await sync_to_async(connections.close_all)()
    # A message Telegram would refuse fails the test that sent it.
    assert not mocked.session.problems, report(mocked.session.problems)


@pytest.fixture
def org(company):
    company.name = "Namuna MChJ"
    company.features = ["attendance", "face_id"]
    company.save(update_fields=["name", "features"])
    return company


@pytest.fixture
def linked(org, member):
    """`linked(role="Employee", telegram_id=…, **kwargs)`: an approved person of the
    organization whose Telegram is linked, in English unless told otherwise."""

    def make(role="Employee", telegram_id=None, *, language="en", **kwargs):
        kwargs.setdefault("user__language", language)
        made = member(org, role, user__telegram_id=telegram_id, **kwargs)
        branch = org.branches.order_by("order", "pk").first()
        made.home_branch = branch
        made.save(update_fields=["home_branch"])
        made.branches.add(branch)
        return made

    return make
