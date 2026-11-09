"""What the bots say about recognition: plain words, short, no emoji (PLAN-OWNER n2 rule).

Call these under the reader's language (`translation.override`).

    text, markup = kudos(kudos, points=5)          # "Madina thanked you: careful work."
    text, markup = kudos_command(member)           # /kudos: the button to the kudos sheet
"""

from __future__ import annotations

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from apps.members.bot_messages import BotMessage, miniapp_url
from apps.recognition.models import Kudos

# How a kudos badge reads inside "Madina thanked you: …." (lower case, mid-sentence).
REASONS = {
    Kudos.Badge.TEAMWORK: gettext_lazy("great teamwork"),
    Kudos.Badge.FAST: gettext_lazy("quick help"),
    Kudos.Badge.CAREFUL: gettext_lazy("careful work"),
    Kudos.Badge.HELPFUL: gettext_lazy("helping a customer"),
    Kudos.Badge.STAR: gettext_lazy("star of the day"),
}
# Mini app deep links (`?screen=`): the kudos sheet with someone picked, the feed, achievements.
THANK_SCREEN = "thank"
FEED_SCREEN = "kudos"
ACHIEVEMENTS_SCREEN = "achievements"


def giver_name(kudos: Kudos) -> str:
    giver = kudos.from_member
    return giver.first_name or str(giver)


def thanked_line(kudos: Kudos) -> str:
    """ "Madina thanked you: careful work." """
    name = giver_name(kudos)
    reason = REASONS.get(kudos.badge)
    if reason is None:
        return _("%(name)s thanked you.") % {"name": name}
    return _("%(name)s thanked you: %(reason)s.") % {"name": name, "reason": reason}


def points_line(points: int) -> str:
    return ngettext("+%(count)s point", "+%(count)s points", points) % {"count": points}


def _app_button(label: str, screen: str) -> InlineKeyboardButton | None:
    """A button that opens the mini app at `screen`; Telegram only takes https Mini App links."""
    if not settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):
        return None
    return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=miniapp_url(screen)))


def kudos(kudos: Kudos, *, points: int | None) -> BotMessage:
    """The receiver's message: who thanked them and for what, the note, the points, and "Say
    thanks back" (the kudos sheet with the giver picked)."""
    lines = [f"<b>{html.quote(thanked_line(kudos))}</b>"]
    if kudos.message:
        lines.append(f"«{html.quote(kudos.message)}»")
    if points:
        lines.append(points_line(points))
    button = _app_button(_("Say thanks back"), f"{THANK_SCREEN}:{kudos.from_member_id}")
    markup = InlineKeyboardMarkup(inline_keyboard=[[button]]) if button else None
    return "\n".join(lines), markup


def kudos_command(*, enabled: bool, left: int | None = None) -> BotMessage:
    """The answer to /kudos: the kudos sheet in the app, or why not."""
    if not enabled:
        return _("Thanks between colleagues aren't switched on in your company."), None
    button = _app_button(_("Say thanks"), THANK_SCREEN)
    lines = [_("Thank a colleague for their help: pick them, a reason and a few words.")]
    if left is not None:
        if left <= 0:
            lines.append(_("You've used today's thanks. More tomorrow."))
        else:
            lines.append(
                ngettext(
                    "You can thank %(count)s more colleague today.",
                    "You can thank %(count)s more colleagues today.",
                    left,
                )
                % {"count": left}
            )
    if button is None:
        lines.append(_("Open the app from the menu button to send it."))
        return "\n".join(lines), None
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[[button]])


def level_title(name: str) -> str:
    return _("New level: %(name)s") % {"name": name}


def to_next_level(points: int) -> str:
    return ngettext(
        "%(count)s point to the next level.", "%(count)s points to the next level.", points
    ) % {"count": points}


def badges_line(names: list[str]) -> str:
    return ngettext("New badge: %(names)s", "New badges: %(names)s", len(names)) % {
        "names": ", ".join(names)
    }
