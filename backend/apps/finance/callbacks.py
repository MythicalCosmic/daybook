"""Inline-button callback data of finance (the employee bot's expense claim flow; approvals
use the inbox's generic `InboxAction` buttons)."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class ClaimAction(StrEnum):
    CATEGORY = "cat"  # a category was picked (value: its id)
    SOURCE = "src"  # paid from (value: 0 own money, 1 company cash I hold)
    SUBMIT = "ok"
    AMOUNT = "amt"  # change the amount
    CHANGE_CATEGORY = "chc"
    CANCEL = "no"


class ClaimButton(CallbackData, prefix="fcl"):
    action: ClaimAction
    value: int = 0
