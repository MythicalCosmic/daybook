from aiogram import Dispatcher

from bot.handlers.start import router as start_router


def register_all_handlers(dp: Dispatcher) -> None:
    dp.include_router(start_router)
