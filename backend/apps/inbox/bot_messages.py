"""What the bots say about notifications: the Telegram copy and its buttons.

Call these under the recipient's language (`translation.override`).
"""

from urllib.parse import urlencode, urlsplit

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification

# A warning or a critical notification says so in words at the start of its bold title.
SEVERITY_TITLE = {
    # Translators: %(title)s is the notification's title, e.g. "Kassa yopilmadi".
    Notification.Severity.WARNING: gettext_noop("Warning: %(title)s"),
    Notification.Severity.CRITICAL: gettext_noop("Urgent: %(title)s"),
}
BUTTONS_PER_ROW = 3


def notification(
    item: Notification, *, audience: str, outcome: str = ""
) -> tuple[str, InlineKeyboardMarkup | None]:
    """The Telegram copy. Once someone acted (`outcome`), the buttons go and the outcome shows."""
    lines = [f"<b>{html.quote(title(item))}</b>"]
    if item.body:
        lines.append(html.quote(item.body))
    if outcome:
        lines += ["", html.quote(outcome)]
    rows: list[list[InlineKeyboardButton]] = []
    if not outcome and item.acted_at is None:
        # Actions that need a reason are answered in the dashboard (the Open button).
        buttons = [
            InlineKeyboardButton(
                text=action["label"],
                callback_data=InboxAction(notification_id=item.pk, key=action["key"]).pack(),
            )
            for action in item.actions
            if not action.get("needs_reason")
        ]
        rows += [
            buttons[start : start + BUTTONS_PER_ROW]
            for start in range(0, len(buttons), BUTTONS_PER_ROW)
        ]
    if open_button := _open_button(item, audience):
        rows.append([open_button])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def title(item: Notification) -> str:
    """The title, with "Warning:" or "Urgent:" in front for those severities (plain text)."""
    template = SEVERITY_TITLE.get(item.severity)
    return _(template) % {"title": item.title} if template else item.title


def outcome_line(label: str, actor_name: str) -> str:
    """ "Approved · Dilnoza", or just "Approved" when the system decided."""
    label = str(label)
    if not actor_name:
        return label
    return _("%(action)s · %(name)s") % {"action": label, "name": actor_name}


def answered_line(label: str, actor_name: str) -> str:
    """What the other copies show when someone answered with a button and nothing more was
    said: the button's words ("Tasdiqlash") read as the answer, not as a button to tap."""
    values = {"action": str(label), "name": actor_name}
    if not actor_name:
        return _("Answer: %(action)s") % values
    return _("Answer: %(action)s · %(name)s") % values


def _open_button(item: Notification, audience: str) -> InlineKeyboardButton | None:
    """Opens the record: the dashboard for owner notifications, the mini app otherwise.

    Telegram only accepts https Mini App links, so nothing is shown without one."""
    if audience == "owner" and item.url and settings.DASHBOARD_URL.startswith("https://"):
        url = f"{settings.DASHBOARD_URL.rstrip('/')}/{item.url.lstrip('/')}"
        return InlineKeyboardButton(text=_("Open"), web_app=WebAppInfo(url=url))
    if item.app_screen and settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):
        base = settings.EMPLOYEE_MINIAPP_URL
        joiner = "&" if urlsplit(base).query else "?"
        url = f"{base}{joiner}{urlencode({'screen': item.app_screen})}"
        # Worded like the task messages' button, which opens the same app.
        return InlineKeyboardButton(text=_("Open in app"), web_app=WebAppInfo(url=url))
    return None
