"""Inline-button callback data of learning (package Q2: answering the question of the day).

Only the daily question's id and an option id travel (Telegram allows 64 bytes); the handler
checks that the person pressing owns the question and that its day isn't over.
"""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class DailyAction(StrEnum):
    PICK = "p"  # one tap answers (single, true or false); toggles an option (several right)
    SEND = "s"  # several right: answer with the options chosen


class DailyCallback(CallbackData, prefix="dq"):
    action: DailyAction
    daily_id: int
    option: str = ""


# The two answers of a true-or-false question, as option ids.
TRUE, FALSE = "t", "f"
