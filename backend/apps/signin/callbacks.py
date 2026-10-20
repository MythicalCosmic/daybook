"""Inline-button callback data of owner sign-in, shared by both bots and the backend.

Both fit Telegram's 64 bytes: "lgn:<32 hex>:47" and "lgs:all:<session id>".
"""

from aiogram.filters.callback_data import CallbackData

# The "It wasn't me" button's pick.
NOT_ME = "x"


class LoginTap(CallbackData, prefix="lgn"):
    """A tap on one of the three numbers (or "It wasn't me") under a sign-in prompt."""

    link: str  # LoginLink id as 32 hex digits
    pick: str  # "47", or NOT_ME


class SessionsAction(CallbackData, prefix="lgs"):
    """The "Log out everywhere" button under a "Signed in on …" message."""

    action: str  # "all"
    session: int
