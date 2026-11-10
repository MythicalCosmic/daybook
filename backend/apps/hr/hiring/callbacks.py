"""Inline-button data of applying for a vacancy in the employee bot (sent by `bot.py`, handled by
`employee_bot/bot/handlers/features/applicants.py`)."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class ApplyStep(StrEnum):
    APPLY = "go"  # "Apply" under the vacancy
    LANGUAGE = "ln"  # the vacancy again in language `pick` (0 uz, 1 ru, 2 en)
    NAME = "nm"  # the name Telegram knows them by is right
    ANSWER = "a"  # option `pick` of question `q` (yes is 1 and no is 0 for a yes-or-no one)
    SKIP = "sk"  # no answer to optional question `q` (or no document photo)
    SEND = "ok"  # send the application
    CANCEL = "x"


class ApplyButton(CallbackData, prefix="hrj"):
    """`v` is the vacancy and `q` the question the button belongs to, so a tap on a button of
    an earlier question or another application does nothing."""

    step: ApplyStep
    v: int
    q: int = 0
    pick: int = 0
