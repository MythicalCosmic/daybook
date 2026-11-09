"""Inline-button callback data of the bot's own messages (notification buttons are
`apps.inbox.callbacks.InboxAction`, shared with the other bots)."""

from aiogram.filters.callback_data import CallbackData


class TodayView(CallbackData, prefix="dvt"):
    """`/today` again, in place: every branch in the person's scope (`branch` 0) or one."""

    branch: int = 0


class MeView(CallbackData, prefix="dvm"):
    """`/me` again, in place."""

    refresh: int = 1


class PickLanguage(CallbackData, prefix="dvl"):
    """A language picked in the `/language` picker."""

    code: str


class HomeLanguage(CallbackData, prefix="dvh"):
    """The home message's "Til / Язык / Language" (no code), then the language picked there."""

    code: str
