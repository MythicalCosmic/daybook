"""Inline-button callback data of the owner bot's own conversations (sign-in buttons live in
`apps.signin.callbacks`, shared with the employee bot)."""

from aiogram.filters.callback_data import CallbackData


class NewCompanyStep(CallbackData, prefix="onc"):
    """A button in the `/new` conversation: `tz` (with `value`), `type_tz`, `create`,
    `rename` or `cancel`."""

    action: str
    value: str = ""


class TodayPick(CallbackData, prefix="otd"):
    """Which company `/today` is about, when the owner has several."""

    company: int
