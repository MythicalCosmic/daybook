"""Inline-button callback data of Ko‘z: the "I'll go" button on an alert, handled the same way
in both bots (`apps.vision.bot_handlers`)."""

from aiogram.filters.callback_data import CallbackData


class KozButton(CallbackData, prefix="koz"):
    alert_id: int
