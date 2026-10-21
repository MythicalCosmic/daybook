"""Inline-button callback data of the company calendar."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class EvAction(StrEnum):
    GOING = "going"
    DECLINE = "decline"
    WEEK = "week"  # the next seven days, from /calendar


class EvCallback(CallbackData, prefix="ev"):
    action: EvAction
    event_id: int = 0
