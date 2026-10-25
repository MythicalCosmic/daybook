"""Callback data of buttons only the bot itself draws (the task buttons live in apps.tasks)."""

from aiogram.filters.callback_data import CallbackData


class LangCallback(CallbackData, prefix="lang"):
    """A language picked: in the picker ("set"), on the greeting ("welcome", after its
    "Til / Язык / Language" button, "langs", showed the three), on the first-contact picker
    older chats still have ("first"); "open" turns a message into the picker."""

    code: str
    mode: str = "set"


class CompanyCallback(CallbackData, prefix="co"):
    """The company someone in several companies works in through the bot (audit X-1)."""

    company_id: int
