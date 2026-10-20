from aiogram import Dispatcher

from bot.handlers.admin.approvals import router as approvals_router
from bot.handlers.contact import router as contact_router
from bot.handlers.groups import router as groups_router
from bot.handlers.member import router as member_router
from bot.handlers.start import router as start_router


def register_all_handlers(dp: Dispatcher) -> None:
    # Order matters: the member router's gate answers everything that reaches it,
    # so group chats are handled before it.
    dp.include_routers(start_router, approvals_router, contact_router, groups_router, member_router)
