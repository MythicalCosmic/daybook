"""Ko‘z alerts (docs/KOZ.md §7): the "I'll go" button under an alert a manager got through the
owner bot. The handler is shared with the employee bot (`apps.vision.bot_handlers`)."""

from aiogram import Router

from apps.vision.bot_handlers import going
from apps.vision.callbacks import KozButton


def make_router() -> Router:
    """A fresh router (a router attaches to one dispatcher only; tests build their own)."""
    router = Router(name="vision")
    router.callback_query.register(going, KozButton.filter())
    return router


router = make_router()
