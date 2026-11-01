"""Inline-button callback data of the AI features. Telegram allows 64 bytes of callback data."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class DraftAction(StrEnum):
    APPLY = "apply"  # create the drafts' tasks
    CANCEL = "cancel"  # throw the voice note away
    UNDO = "undo"  # take back what an automatic create made


class AIDraftCallback(CallbackData, prefix="aid"):
    action: DraftAction
    id: int


class LateAction(StrEnum):
    HOUR_MORE = "hour"  # the deadline watcher's "+1 hour"


class AILateCallback(CallbackData, prefix="ail"):
    action: LateAction
    task_id: int
