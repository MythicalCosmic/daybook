"""Callback data of the bots' task buttons.

`TaskCallback` keeps its exact format (`task:<action>:<id>`): buttons on messages sent before a
change still unpack. Actions that carry something more get their own short prefix. Telegram
allows 64 bytes of callback data.
"""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class TaskAction(StrEnum):
    LIST = "list"
    OPEN = "open"
    START = "start"
    DONE = "done"
    CONFIRM = "confirm"
    RETURN = "return"
    SNOOZE = "snooze"  # the policy's own length, as reminders sent before snooze choices had it
    STOP = "stop"  # abandon whatever the bot is asking for
    UNDO = "undo"  # reopen what was just marked done (research R2 T38)
    SNOOZE_MENU = "snz"  # turn the card's keyboard into the snooze choices
    COMMENT = "comment"  # ask for a comment on the task
    NEW = "new"  # start a new task from a list
    REVIEWS = "reviews"  # the work waiting for my check
    FINISH = "finish"  # Done although some steps aren't ticked
    TICK_ALL = "tickall"  # tick every step, then Done
    BACK = "back"  # the card's normal keyboard again
    MORE_TIME = "moretime"  # ask for a later deadline
    BLOCK = "block"  # "can't do it": pick a reason
    NUDGE = "nudge"  # a manager reminds the assignee now
    REASSIGN = "reassign"  # a manager gives it to someone else
    NEW_DUE = "newdue"  # a manager sets a new deadline
    CANCEL = "cancel"  # a manager cancels it (asks first)
    CANCEL_YES = "cancelyes"
    PHOTO = "photo"  # send the proof photo


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


class StepCallback(CallbackData, prefix="tstep"):
    """Tick or untick one checklist step from the card."""

    task_id: int
    item_id: int


class SnoozeCallback(CallbackData, prefix="tsnz"):
    """One of the snooze choices (`apps.tasks.services.SNOOZE_PRESETS`)."""

    task_id: int
    preset: str


class ListCallback(CallbackData, prefix="tlist"):
    """A page of a task list: "mine" (my open work) or "check" (waiting for my check)."""

    view: str
    page: int = 0


class PickCallback(CallbackData, prefix="tpick"):
    """A person picked from a list: who a new task is for (`task_id` 0), or who gets a task
    someone couldn't do. `member_id` 0 means "me"; `page` turns the list's pages."""

    task_id: int
    member_id: int = 0
    page: int = 0


class ReasonCallback(CallbackData, prefix="treason"):
    """A ready-made reason: why it can't be done (`kind` "block") or why work goes back
    (`kind` "return")."""

    kind: str
    task_id: int
    code: str


class WhenCallback(CallbackData, prefix="twhen"):
    """A deadline choice for a task that exists: more time asked for (`kind` "more"), or a new
    deadline a manager sets (`kind` "due"). `choice` is a preset, or "type" to write one."""

    kind: str
    task_id: int
    choice: str


class PhotoCallback(CallbackData, prefix="tphoto"):
    """Which task a photo sent on its own is proof for (`task_id` 0: none of them)."""

    task_id: int = 0


class QuickAddCallback(CallbackData, prefix="tqa"):
    """The quick-add preview's buttons: save, change the time, keep the words in the title."""

    action: str


class TeamCallback(CallbackData, prefix="team"):
    """A head's "My team": `member_id` 0 for the whole team, else one person's work."""

    member_id: int = 0
