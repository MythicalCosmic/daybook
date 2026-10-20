from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class GroupAction(StrEnum):
    TOGGLE = "toggle"  # an event on or off
    WHO = "who"  # open the positions picker
    POSITION = "pos"  # a position in or out of the filter
    BACK = "back"  # from the picker to the events
    CLOSE = "close"


class GroupCallback(CallbackData, prefix="grp"):
    action: GroupAction
    event: str = ""
    position_id: int = 0
