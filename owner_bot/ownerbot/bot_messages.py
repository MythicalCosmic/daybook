"""What the owner bot says. Call these under the user's language."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils.translation import gettext as _

from apps.accounts.models import User

type BotMessage = tuple[str, InlineKeyboardMarkup | None]


def welcome(user: User) -> BotMessage:
    name = user.first_name or _("there")
    text = "\n\n".join(
        (
            _("Hello, %(name)s! This is the 911 owner bot.") % {"name": name},
            _(
                "Approvals, sign-in confirmations and alerts from your companies will come "
                "here. Open the dashboard to see everything."
            ),
        )
    )
    return text, dashboard_keyboard()


def dashboard_keyboard() -> InlineKeyboardMarkup | None:
    """"Open dashboard" as a Mini App (Telegram only accepts https links)."""
    if not settings.DASHBOARD_URL.startswith("https://"):
        return None
    button = InlineKeyboardButton(
        text=_("📊 Open dashboard"), web_app=WebAppInfo(url=settings.DASHBOARD_URL)
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])
