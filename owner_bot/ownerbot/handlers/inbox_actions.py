"""Notification buttons (`InboxAction` callback data): approve, reject, seen… in place.

The handler is shared with the employee bot (`apps.inbox.bot_handlers`); modules only register
their actions with `apps.inbox.registry.register_action`.
"""

from aiogram import Router

from apps.inbox.bot_handlers import handle_action
from apps.inbox.callbacks import InboxAction


def make_router() -> Router:
    """A fresh router (a router attaches to one dispatcher only; tests build their own)."""
    router = Router(name="inbox_actions")
    router.callback_query.register(handle_action, InboxAction.filter())
    return router


router = make_router()
