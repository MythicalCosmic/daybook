from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class AnnounceAction(StrEnum):
    PICK = "pick"  # a position in or out of the audience, while drafting
    SEND = "send"
    CANCEL = "cancel"
    READ = "read"  # a recipient has read it
    WHO = "who"  # the author asks who has read it


class AnnounceCallback(CallbackData, prefix="ann"):
    action: AnnounceAction
    announcement_id: int = 0
    position_id: int = 0
