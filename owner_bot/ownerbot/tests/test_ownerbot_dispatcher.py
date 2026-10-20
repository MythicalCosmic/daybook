"""The owner bot's dispatcher and entry point."""

import pytest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from ownerbot.config import Settings, load_settings
from ownerbot.dispatcher import create_storage


def test_dispatcher_handles_messages_buttons_and_blocks(dp):
    used = set(dp.resolve_used_update_types())

    assert {"message", "callback_query", "my_chat_member"} <= used


def test_settings_come_from_django(settings):
    settings.OWNER_BOT_TOKEN = "43:FROM-DJANGO"
    settings.DASHBOARD_URL = "https://app.example.uz/dashboard/"

    loaded = load_settings()

    assert (loaded.BOT_TOKEN, loaded.DASHBOARD_URL) == (
        "43:FROM-DJANGO",
        "https://app.example.uz/dashboard/",
    )


def test_fsm_state_never_mixes_with_the_employee_bots():
    storage = create_storage(
        Settings(BOT_TOKEN="", FSM_REDIS_URL="redis://localhost:1/0", DASHBOARD_URL="")
    )

    assert isinstance(storage, RedisStorage)
    assert storage.key_builder.prefix == "fsm_owner"
    assert storage.key_builder.with_bot_id is True
    assert isinstance(create_storage(Settings("", "", "")), MemoryStorage)


async def test_python_m_ownerbot_refuses_to_start_without_a_token(settings):
    from ownerbot.__main__ import main

    settings.OWNER_BOT_TOKEN = ""

    with pytest.raises(SystemExit, match="OWNER_BOT_TOKEN"):
        await main()
