from aiogram import Dispatcher

from bot.middlewares.database import DjangoConnectionMiddleware
from bot.middlewares.menu_commands import MenuCommandMiddleware
from bot.middlewares.user import UserMiddleware


def register_all_middlewares(dp: Dispatcher) -> None:
    dp.update.outer_middleware(DjangoConnectionMiddleware())
    dp.update.outer_middleware(UserMiddleware())
    # After the update-level FSM middleware has read the conversation state.
    dp.message.outer_middleware(MenuCommandMiddleware())
