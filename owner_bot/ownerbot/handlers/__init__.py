from aiogram import Dispatcher

from ownerbot.handlers.inbox_actions import router as inbox_actions_router
from ownerbot.handlers.start import router as start_router


def register_all_handlers(dp: Dispatcher) -> None:
    # Notification buttons first: they carry their own callback data and never clash.
    dp.include_routers(inbox_actions_router, start_router)
