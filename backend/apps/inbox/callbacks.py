"""Callback data of notification buttons in Telegram, handled once in each bot."""

from aiogram.filters.callback_data import CallbackData


class InboxAction(CallbackData, prefix="ib"):
    notification_id: int
    key: str
