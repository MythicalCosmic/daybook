from aiogram import Dispatcher

from bot.middlewares.database import DjangoConnectionMiddleware
from bot.middlewares.user import UserMiddleware


def register_all_middlewares(dp: Dispatcher) -> None:
    dp.update.outer_middleware(DjangoConnectionMiddleware())
    dp.update.outer_middleware(UserMiddleware())
