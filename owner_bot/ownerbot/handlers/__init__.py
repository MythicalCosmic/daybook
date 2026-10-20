from aiogram import Dispatcher

from ownerbot.handlers.inbox_actions import router as inbox_actions_router
from ownerbot.handlers.new_company import router as new_company_router
from ownerbot.handlers.signin import router as signin_router
from ownerbot.handlers.start import router as start_router
from ownerbot.handlers.today import router as today_router


def register_all_handlers(dp: Dispatcher) -> None:
    # Buttons with their own callback data first (notifications, sign-in); then /start and the
    # menu commands, which end any conversation; the /new conversation last, so its "waiting
    # for text" handlers never swallow a command.
    dp.include_routers(
        inbox_actions_router, signin_router, start_router, today_router, new_company_router
    )
