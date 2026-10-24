"""Which task a button or a reply is about, read from its callback data.

People in several companies (audit X-1) act on a task in that task's company, whatever company
their lists show: the access gate reads the task id from here and lets the person act with
their membership there.
"""

from aiogram.types import CallbackQuery, Message

from apps.tasks.callbacks import (
    PhotoCallback,
    PickCallback,
    ReasonCallback,
    SnoozeCallback,
    StepCallback,
    TaskCallback,
    WhenCallback,
)

TASK_CALLBACKS = (
    TaskCallback,
    StepCallback,
    SnoozeCallback,
    PickCallback,
    ReasonCallback,
    WhenCallback,
    PhotoCallback,
)


def task_id_of(data: str | None) -> int | None:
    """The task a button's callback data names, or None."""
    if not data:
        return None
    for kind in TASK_CALLBACKS:
        try:
            unpacked = kind.unpack(data)
        except TypeError, ValueError:
            continue
        return getattr(unpacked, "task_id", 0) or None
    return None


def task_id_of_message(message: Message | None) -> int | None:
    """The task a bot message is about: the first task button on its keyboard."""
    markup = getattr(message, "reply_markup", None)
    for row in getattr(markup, "inline_keyboard", None) or ():
        for button in row:
            if (task_id := task_id_of(button.callback_data)) is not None:
                return task_id
    return None


def task_id_of_event(event) -> int | None:
    """The task an update is about: a task button pressed, or a reply to a task message."""
    if isinstance(event, CallbackQuery):
        return task_id_of(event.data)
    if isinstance(event, Message) and event.reply_to_message is not None:
        return task_id_of_message(event.reply_to_message)
    return None
