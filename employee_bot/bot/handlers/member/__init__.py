from aiogram import Router

from bot.handlers.member.announcements import router as announcements_router
from bot.handlers.member.home import router as home_router
from bot.handlers.member.tasks import router as tasks_router
from bot.middlewares.access import MemberAccessMiddleware

# Everything included here is for approved members only.
router = Router(name="member")
router.message.outer_middleware(MemberAccessMiddleware())
router.callback_query.outer_middleware(MemberAccessMiddleware())
# Tasks first: their menu buttons win over an announcement being drafted.
router.include_routers(tasks_router, announcements_router, home_router)
