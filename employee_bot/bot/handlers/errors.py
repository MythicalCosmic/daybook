"""When a handler fails (research R1 F1): every button tap still gets an answer, so no spinner
runs forever, and every message a reply. The failure is logged with its traceback."""

import logging
from contextlib import suppress

from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent
from django.utils import translation
from django.utils.translation import gettext as _

from apps.accounts.models import User

logger = logging.getLogger(__name__)


async def on_error(event: ErrorEvent, user: User | None = None) -> bool:
    logger.error("Update %s failed", event.update.update_id, exc_info=event.exception)
    with translation.override(user.language if user is not None else "uz"):
        text = _("Something went wrong. Please try again in a moment.")
    update = event.update
    with suppress(TelegramAPIError):
        if update.callback_query is not None:
            await update.callback_query.answer(text)
        elif update.message is not None and update.message.chat.type == ChatType.PRIVATE:
            await update.message.answer(text)
    return True
