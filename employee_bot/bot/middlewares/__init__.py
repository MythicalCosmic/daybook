from aiogram import Dispatcher

from bot.middlewares.database import DjangoConnectionMiddleware


def register_all_middlewares(dp: Dispatcher) -> None:
    dp.update.outer_middleware(DjangoConnectionMiddleware())
