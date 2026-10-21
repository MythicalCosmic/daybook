"""Inline-button callback data of the knowledge base."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class KbAction(StrEnum):
    OPEN = "open"  # send the page into the chat
    ACK = "ack"  # "I've read it"
    LIST = "list"  # back to the list of pages to read


class KbCallback(CallbackData, prefix="kb"):
    action: KbAction
    page_id: int = 0
    version: int = 0
