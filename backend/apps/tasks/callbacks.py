from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class TaskAction(StrEnum):
    LIST = "list"
    OPEN = "open"
    START = "start"
    DONE = "done"
    CONFIRM = "confirm"
    RETURN = "return"
    STOP = "stop"  # abandon whatever the bot is asking for


class TaskCallback(CallbackData, prefix="task"):
    action: TaskAction
    task_id: int = 0


class DuePreset(StrEnum):
    IN_AN_HOUR = "1h"
    TODAY_EVENING = "today"
    TOMORROW_MORNING = "tomorrow"
    NONE = "none"


class DueCallback(CallbackData, prefix="due"):
    preset: DuePreset
