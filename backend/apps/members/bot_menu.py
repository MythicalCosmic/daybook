"""Extra buttons in the employee bot's main menu, registered by the modules that answer them.

    register_menu_button(gettext_noop("📍 Keldim"), order=10,
                         visible=lambda member: member.company.has_feature("attendance"),
                         web_app_screen="attendance")

`msgid` is the untranslated label (the bot matches incoming text against every translation of
it, apps.members.bot_messages and bot.filters.menu.MenuButton); `visible(member)` decides per
person; with `web_app_screen` the bot answers the button with an inline button that opens that
screen of the mini app (`?screen=<screen>`) when the app is configured, and the module's own
handler gets the text otherwise. (A keyboard button can't open the app itself: Telegram gives
such a Mini App no initData, so it couldn't sign the person in.) Buttons appear after "My
tasks" and "New task", two per row, by `order`.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MenuButton:
    msgid: str
    order: int
    visible: Callable[[object], bool]
    web_app_screen: str | None = None


_buttons: dict[str, MenuButton] = {}


class DuplicateMenuButton(ValueError):
    pass


def register_menu_button(
    msgid: str,
    *,
    order: int,
    visible: Callable[[object], bool],
    web_app_screen: str | None = None,
) -> None:
    if msgid in _buttons:
        raise DuplicateMenuButton(f"A menu button {msgid!r} is already registered.")
    _buttons[msgid] = MenuButton(msgid, order, visible, web_app_screen)


def registered() -> list[MenuButton]:
    return sorted(_buttons.values(), key=lambda button: (button.order, button.msgid))


def buttons_for(member) -> list[MenuButton]:
    """The registered buttons `member` sees. A module whose check fails loses its button
    instead of breaking everyone's menu."""
    shown = []
    for button in registered():
        try:
            if button.visible(member):
                shown.append(button)
        except Exception:
            logger.exception("Menu button %r failed its visibility check", button.msgid)
    return shown
