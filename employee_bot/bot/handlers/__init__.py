from aiogram import Dispatcher

from bot.handlers.admin.approvals import router as approvals_router
from bot.handlers.admin.time_off import router as time_off_router
from bot.handlers.company import router as company_router
from bot.handlers.contact import router as contact_router
from bot.handlers.errors import on_error
from bot.handlers.features.applicants import router as applicants_router
from bot.handlers.features.signin import router as signin_router
from bot.handlers.groups import router as groups_router
from bot.handlers.language import router as language_router
from bot.handlers.member import router as member_router
from bot.handlers.start import router as start_router


def register_all_handlers(dp: Dispatcher) -> None:
    # Order matters:
    # - sign-in confirmations and /start (with its deep links) work for anyone, member or not;
    # - so do the language picker, /help and /settings, and the company switch;
    # - an applicant's answers and contact reach the application before the join flow's
    #   contact handler;
    # - group chats come before the member router, whose gate answers everything that reaches it.
    dp.include_routers(
        signin_router,
        start_router,
        language_router,
        company_router,
        applicants_router,
        approvals_router,
        time_off_router,
        contact_router,
        groups_router,
        member_router,
    )
    # A handler that fails still answers the tap or the message (research R1 F1).
    dp.errors.register(on_error)
