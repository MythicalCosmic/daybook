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


class InvitePick(CallbackData, prefix="oiv"):
    """Which company `/invite` is about, when the owner has several."""

    company: int


class InviteAct(CallbackData, prefix="oia"):
    """A button of `/invite`: `main` (the main link's QR code), `show` (team link `link`'s QR
    code), `stop` (stop team link `link`) or `list` (the company's links again)."""

    action: str
    company: int
    link: int = 0


class InviteNew(CallbackData, prefix="oin"):
    """A step of making a team link in the bot; the choices so far travel in the button.
    -1: not chosen yet; `branch` 0: none; `places` 0: no limit; `days` 0: until tonight."""

    company: int
    branch: int = -1
    places: int = -1
    days: int = -1
