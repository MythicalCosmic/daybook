from aiogram import Router

from bot.handlers.member.home import router as home_router
from bot.middlewares.access import MemberAccessMiddleware

# Everything included here is for approved members only.
router = Router(name="member")
router.message.outer_middleware(MemberAccessMiddleware())
router.callback_query.outer_middleware(MemberAccessMiddleware())
router.include_router(home_router)
