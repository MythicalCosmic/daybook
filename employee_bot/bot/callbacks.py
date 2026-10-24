"""Callback data of buttons only the bot itself draws (the task buttons live in apps.tasks)."""

from aiogram.filters.callback_data import CallbackData


class LangCallback(CallbackData, prefix="lang"):
    """A language picked: in the picker ("set"), on first contact ("first"), on the Uzbek
    welcome's row ("welcome"); "open" turns a message into the picker."""

    code: str
    mode: str = "set"


class CompanyCallback(CallbackData, prefix="co"):
    """The company someone in several companies works in through the bot (audit X-1)."""

    company_id: int
