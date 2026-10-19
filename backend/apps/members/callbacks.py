"""Callback data shared by the backend, which sends the buttons, and the bot, which handles them."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class JoinAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class JoinDecision(CallbackData, prefix="join"):
    action: JoinAction
    membership_id: int
