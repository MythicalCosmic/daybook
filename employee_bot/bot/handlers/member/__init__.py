from aiogram import Router

from bot.handlers.features.agenda import router as agenda_router
from bot.handlers.features.ai import router as ai_router
from bot.handlers.features.attendance import router as attendance_router
from bot.handlers.features.crm import router as crm_router
from bot.handlers.features.finance import router as finance_router
from bot.handlers.features.hr import router as hr_router
from bot.handlers.features.inbox_actions import router as inbox_actions_router
from bot.handlers.features.knowledge import router as knowledge_router
from bot.handlers.features.lifecycle import router as lifecycle_router
from bot.handlers.features.payroll import router as payroll_router
from bot.handlers.features.projects import router as projects_router
from bot.handlers.features.recognition import router as recognition_router
from bot.handlers.features.sales import router as sales_router
from bot.handlers.member.announcements import router as announcements_router
from bot.handlers.member.app import router as app_router
from bot.handlers.member.home import router as home_router
from bot.handlers.member.tasks import router as tasks_router
from bot.middlewares.access import MemberAccessMiddleware

# Module areas, after the state-bound routers and before home (docs/PLAN-OWNER.md §10.2).
FEATURE_ROUTERS = [
    inbox_actions_router,
    sales_router,
    attendance_router,
    finance_router,
    payroll_router,
    hr_router,
    ai_router,
    recognition_router,
    projects_router,
    lifecycle_router,
    knowledge_router,
    agenda_router,
    crm_router,
]

# Everything included here is for approved members only.
router = Router(name="member")
router.message.outer_middleware(MemberAccessMiddleware())
router.callback_query.outer_middleware(MemberAccessMiddleware())
# The app's buttons first: they answer with a button that opens the mini app, before a module
# handles its own button's text. Then tasks: their menu buttons win over an announcement being
# drafted. Both hold conversation states (a proof photo, an announcement text), and a state they
# are waiting in wins over every feature; home answers whatever nothing else took. A menu
# command (/checkin …) ends an open conversation before routing (bot.middlewares.menu_commands).
router.include_routers(
    app_router, tasks_router, announcements_router, *FEATURE_ROUTERS, home_router
)
