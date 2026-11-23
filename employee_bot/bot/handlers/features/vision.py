"""Ko‘z alerts (docs/KOZ.md §7): the "I'll go" button under a queue or "nobody at the counter"
alert, pressed by someone on shift. The handler is shared with the owner bot
(`apps.vision.bot_handlers`); it checks that the person pressing got a copy of the alert, so it
needs no gate of its own. Every copy is edited once the acknowledgement commits.
"""

from aiogram import Router

from apps.vision.bot_handlers import going
from apps.vision.callbacks import KozButton


def make_router() -> Router:
    """A fresh router (a router attaches to one dispatcher only; tests build their own)."""
    router = Router(name="feature_vision")
    router.callback_query.register(going, KozButton.filter())
    return router


router = make_router()
