"""What the bots say about owner sign-in. Both bots use these (the employee bot confirms
sign-ins while the owner bot has no token); call them under the person's language."""

import zoneinfo
from datetime import datetime

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.members.models import Membership
from apps.signin import devices
from apps.signin.callbacks import NOT_ME, LoginTap, SessionsAction
from apps.signin.models import DeviceSession

type BotMessage = tuple[str, InlineKeyboardMarkup | None]


def user_timezone(user: User) -> zoneinfo.ZoneInfo:
    """The timezone of the person's first company (owners rarely span timezones), else the
    server's."""
    name = (
        Membership.objects.filter(user=user, status=Membership.Status.APPROVED)
        .order_by("pk")
        .values_list("company__timezone", flat=True)
        .first()
    )
    try:
        return zoneinfo.ZoneInfo(name or settings.TIME_ZONE)
    except zoneinfo.ZoneInfoNotFoundError, ValueError:
        return zoneinfo.ZoneInfo(settings.TIME_ZONE)


def _clock(moment: datetime, user: User) -> str:
    return timezone.localtime(moment, user_timezone(user)).strftime("%H:%M")


def login_prompt(prompt, user: User) -> BotMessage:
    """The question under `/start login_…`: where the sign-in comes from, three numbers."""
    origin = " · ".join(part for part in (prompt.ip, _clock(prompt.created_at, user)) if part)
    text = "\n".join(
        (
            "🔐 <b>" + html.quote(_("Sign in to the dashboard?")) + "</b>",
            "",
            "💻 " + html.quote(prompt.device.label),
            "🌐 " + html.quote(origin),
            "",
            html.quote(_("Tap the number you see on your screen.")),
            html.quote(_("Didn't start this? Tap “It wasn't me”.")),
        )
    )
    link = prompt.link_id.hex
    numbers = [
        InlineKeyboardButton(text=number, callback_data=LoginTap(link=link, pick=number).pack())
        for number in prompt.choices
    ]
    not_me = InlineKeyboardButton(
        text=_("🚫 It wasn't me"), callback_data=LoginTap(link=link, pick=NOT_ME).pack()
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[numbers, [not_me]])


def link_refused(reason: str) -> str:
    """Why `/start login_…` can't go on."""
    messages = {
        "expired": _("⏳ This sign-in code has expired. Get a new one in your browser."),
        "used": _("This sign-in code was already used. Get a new one in your browser."),
        "denied": _("This sign-in was cancelled. Get a new code in your browser."),
        "no_access": _(
            "You don't have access to the dashboard. Ask the company owner to give your role "
            "dashboard access."
        ),
    }
    return messages.get(reason, _("This sign-in link isn't valid. Get a new one in your browser."))


def login_outcome(outcome: str) -> str:
    """What replaces the prompt after a tap."""
    messages = {
        "approved": _("✅ Confirmed. Go back to your browser: you're being signed in."),
        "wrong_number": _(
            "❌ That wasn't the number on the screen, so this sign-in was cancelled. "
            "If it was you, start again in your browser."
        ),
        "denied": _("🛡 Cancelled. Nobody was signed in."),
        "no_access": link_refused("no_access"),
        "expired": link_refused("expired"),
        "used": link_refused("used"),
    }
    return messages.get(outcome, link_refused("unknown"))


def signed_in(session: DeviceSession) -> BotMessage:
    """After every desktop sign-in: where, and a way out if it wasn't them."""
    device = devices.describe(session.user_agent)
    place = " · ".join(
        part
        for part in (
            device.label,
            devices.masked_ip(session.ip),
            _clock(session.created_at, session.user),
        )
        if part
    )
    text = "\n".join(
        (
            "🔓 <b>" + html.quote(_("Signed in to the dashboard")) + "</b>",
            html.quote(place),
            "",
            html.quote(_("Not you? Log out everywhere and nobody stays signed in.")),
        )
    )
    button = InlineKeyboardButton(
        text=_("Log out everywhere"),
        callback_data=SessionsAction(action="all", session=session.pk).pack(),
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[[button]])


def logged_out_everywhere(count: int) -> str:
    if count == 0:
        return _("✅ You were already signed out everywhere.")
    return _("✅ Done: signed out on every device. Sign in again whenever you need.")
