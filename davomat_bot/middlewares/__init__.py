from aiogram import Dispatcher

from davomat_bot.middlewares.database import DjangoConnectionMiddleware
from davomat_bot.middlewares.person import PersonMiddleware


def register_all_middlewares(dp: Dispatcher) -> None:
    dp.update.outer_middleware(DjangoConnectionMiddleware())
    dp.update.outer_middleware(PersonMiddleware())
