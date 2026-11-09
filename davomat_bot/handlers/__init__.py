from aiogram import Dispatcher

from apps.core.bot_runtime import on_error
from davomat_bot.handlers.inbox_actions import router as inbox_actions_router
from davomat_bot.handlers.language import router as language_router
from davomat_bot.handlers.start import fallback_router
from davomat_bot.handlers.start import router as start_router
from davomat_bot.handlers.today import router as today_router


def register_all_handlers(dp: Dispatcher) -> None:
    # Notification buttons first (their own callback data); then /start, /help, /language,
    # /today and /me; last the home message for anything else said outside a conversation.
    dp.include_routers(
        inbox_actions_router,
        start_router,
        language_router,
        today_router,
        fallback_router,
    )
    # A handler that fails still answers the tap or the message.
    dp.errors.register(on_error)
