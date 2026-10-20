"""What the bots say about notifications: the Telegram copy and its buttons.

Call these under the recipient's language (`translation.override`).
"""

from urllib.parse import urlencode, urlsplit

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils.translation import gettext as _

from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification

SEVERITY_MARK = {
    Notification.Severity.WARNING: "⚠️ ",
    Notification.Severity.CRITICAL: "🚨 ",
}
BUTTONS_PER_ROW = 3


def notification(
    item: Notification, *, audience: str, outcome: str = ""
) -> tuple[str, InlineKeyboardMarkup | None]:
    """The Telegram copy. Once someone acted (`outcome`), the buttons go and the outcome shows."""
    lines = [f"{SEVERITY_MARK.get(item.severity, '')}<b>{html.quote(item.title)}</b>"]
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


def outcome_line(label: str, actor_name: str) -> str:
    """ "✅ Approved · Dilnoza", or just "✅ Approved" when the system decided."""
    if not actor_name:
        return _("✅ %(action)s") % {"action": label}
    return _("✅ %(action)s · %(name)s") % {"action": label, "name": actor_name}


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
        return InlineKeyboardButton(text=_("Open"), web_app=WebAppInfo(url=url))
    return None
