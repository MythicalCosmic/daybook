from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class TimeOffAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class TimeOffDecision(CallbackData, prefix="off"):
    action: TimeOffAction
    time_off_id: int
