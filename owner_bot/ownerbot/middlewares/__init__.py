from aiogram import Dispatcher

from ownerbot.middlewares.database import DjangoConnectionMiddleware
from ownerbot.middlewares.user import OwnerUserMiddleware


def register_all_middlewares(dp: Dispatcher) -> None:
    dp.update.outer_middleware(DjangoConnectionMiddleware())
    dp.update.outer_middleware(OwnerUserMiddleware())
