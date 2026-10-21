"""Inline-button callback data of attendance (the employee bot's own buttons; approvals use
the inbox's generic `InboxAction` buttons)."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class AttendanceAction(StrEnum):
    CHECK_IN = "in"  # start checking in (asks for the location)
    CHECK_OUT = "out"  # start checking out
    OFF_TODAY = "off"  # "I'm off today" on a missed-start nudge
    DONE_NOW = "done"  # "I'm done now": check out without a location
    STILL_HERE = "still"  # "Still here": no more questions about this shift
    CANCEL = "cancel"


class AttendanceButton(CallbackData, prefix="att"):
    action: AttendanceAction
    # The shift (OFF_TODAY) or record (DONE_NOW, STILL_HERE) the button is about.
    ref: int = 0
