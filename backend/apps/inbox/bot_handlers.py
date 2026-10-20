"""The one notification-button handler both bots register (aiogram).

    router.callback_query.register(handle_action, InboxAction.filter())

The user comes from the bot's user middleware (`data["user"]`). The bot message is edited by
`inbox.delivery` once the action commits, for every copy, so the handler only answers the tap.
"""

from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.inbox import services
from apps.inbox.callbacks import InboxAction


async def handle_action(
    query: CallbackQuery, callback_data: InboxAction, user: User | None = None
) -> None:
    if user is None:
        await query.answer(_("You don't have access to this."), show_alert=True)
        return
    result = await sync_to_async(services.act_from_bot)(
        callback_data.notification_id, callback_data.key, user=user
    )
    await query.answer(result.message[:200], show_alert=not result.ok)
