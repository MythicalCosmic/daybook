"""Notification buttons (`InboxAction` callback data): approve, reject, seen… in place.

The handler is shared with the owner bot (`apps.inbox.bot_handlers`); it checks that the person
pressing is the notification's recipient, so it needs no gate of its own. Modules only register
their actions with `apps.inbox.registry.register_action`.
"""

from aiogram import Router

from apps.inbox.bot_handlers import handle_action
from apps.inbox.callbacks import InboxAction


def make_router() -> Router:
    """A fresh router (a router attaches to one dispatcher only; tests build their own).

    Named `feature_<module>` like every area router in this package (W0-L3's dispatcher
    tests check it)."""
    router = Router(name="feature_inbox_actions")
    router.callback_query.register(handle_action, InboxAction.filter())
    return router


router = make_router()
