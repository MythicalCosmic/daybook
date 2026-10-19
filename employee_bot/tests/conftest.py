import pytest
from asgiref.sync import sync_to_async
from django.db import connections

from main import create_dispatcher
from tests.mocked_bot import MockedBot


@pytest.fixture(scope="session")
def dp():
    # Routers are module-level singletons and attach to one dispatcher only.
    return create_dispatcher()


@pytest.fixture
async def bot():
    yield MockedBot()
    # Handlers query from asgiref's worker thread; close its connection so the
    # test database can be dropped when the session ends.
    await sync_to_async(connections.close_all)()
