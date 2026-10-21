"""Inline-button callback data of sales and cash."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class HandoverAnswer(StrEnum):
    RECEIVED = "ok"
    NOT_RECEIVED = "no"


class SalesHandover(CallbackData, prefix="sh"):
    """[Received] / [Not received] under a handover in the Kassa summary."""

    answer: HandoverAnswer
    movement_id: int
