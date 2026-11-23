"""The "I'll go" button of Ko‘z alerts, registered by both bots (aiogram):

    router.callback_query.register(going, KozButton.filter())

The user comes from the bot's user middleware (`data["user"]`). Every copy of the alert is
edited by `apps.vision.notify` once the acknowledgement commits; the handler only answers the
tap.
"""

from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.vision import services
from apps.vision.callbacks import KozButton


async def going(query: CallbackQuery, callback_data: KozButton, user: User | None = None) -> None:
    if user is None:
        await query.answer(_("You don't have access to this."), show_alert=True)
        return
    answer = await sync_to_async(services.acknowledge_from_bot)(callback_data.alert_id, user=user)
    await query.answer(answer.message[:200], show_alert=not answer.ok)
