"""Fixtures for the owner bot's tests. Everything lives inside `ownerbot.tests`, so nothing
clashes with the employee bot's top-level `tests` package."""

import asyncio

import pytest
from asgiref.sync import sync_to_async
from django.db import connections

from apps.core.bot_runtime import close_database_threads
from ownerbot.dispatcher import create_dispatcher
from ownerbot.tests.mocked_bot import MockedBot


@pytest.fixture(scope="session")
def dp():
    # Routers are module-level singletons and attach to one dispatcher only.
    return create_dispatcher()


@pytest.fixture
async def bot():
    yield MockedBot()
    # Handlers query from the bots' database threads (apps.core.bot_runtime) and asgiref's
    # own thread; close their connections so the test database can be dropped at the end.
    await asyncio.to_thread(close_database_threads)
    await sync_to_async(connections.close_all)()
