"""Both bots wait out Telegram's flood limit instead of dropping replies
(apps.core.bot_runtime.WaitOnFloodLimit)."""

import main
from apps.core.bot_runtime import WaitOnFloodLimit
from core.config import Settings as EmployeeSettings
from ownerbot.config import Settings as OwnerSettings
from ownerbot.dispatcher import create_bot as create_owner_bot


def test_both_bots_wait_on_the_flood_limit(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        EmployeeSettings(
            BOT_TOKEN="42:TEST", FSM_REDIS_URL="", MINIAPP_URL="", PLATFORM_ADMIN_IDS=()
        ),
    )
    bots = [
        main.create_bot(),
        create_owner_bot(OwnerSettings(BOT_TOKEN="42:TEST", FSM_REDIS_URL="", DASHBOARD_URL="")),
    ]

    for bot in bots:
        assert any(isinstance(layer, WaitOnFloodLimit) for layer in bot.session.middleware)
