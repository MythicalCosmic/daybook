"""Telegram texts and keyboards about memberships, used by the bot and by backend notifications."""

from aiogram import html
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.members.callbacks import JoinAction, JoinDecision
from apps.members.models import Membership

type BotMessage = tuple[str, InlineKeyboardMarkup | ReplyKeyboardMarkup | None]


def join_request(membership: Membership) -> BotMessage:
    """What approvers see. Once decided, it shows the outcome instead of buttons."""
    user = membership.user
    name = html.quote(user.get_full_name() or str(user))
    lines = [
        _("📝 <b>Join request</b> · %(company)s")
        % {"company": html.quote(membership.company.name)},
        "",
        _("Name: %(name)s") % {"name": f'<a href="tg://user?id={user.telegram_id}">{name}</a>'},
    ]
    if user.telegram_username:
        lines.append(
            _("Username: @%(username)s") % {"username": html.quote(user.telegram_username)}
        )
    lines.append(_("Telegram ID: <code>%(id)s</code>") % {"id": user.telegram_id})

    if membership.status != Membership.Status.PENDING:
        lines += ["", _outcome(membership)]
        return "\n".join(lines), None

    buttons = [
        InlineKeyboardButton(
            text=_("✅ Approve"),
            callback_data=JoinDecision(
                action=JoinAction.APPROVE, membership_id=membership.pk
            ).pack(),
        ),
        InlineKeyboardButton(
            text=_("❌ Reject"),
            callback_data=JoinDecision(
                action=JoinAction.REJECT, membership_id=membership.pk
            ).pack(),
        ),
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[buttons])


def status(membership: Membership | None) -> BotMessage | None:
    """The reply for someone using the bot. None means stay silent (blocked people)."""
    if membership is None or membership.status == Membership.Status.LEFT:
        return _("👋 Hi! To join your company, open the invite link your manager sent you."), None
    if membership.status == Membership.Status.PENDING:
        text = _(
            "⏳ Your request to join <b>%(company)s</b> is waiting for approval. "
            "I'll message you as soon as it's decided."
        ) % {"company": html.quote(membership.company.name)}
        return text, None
    if membership.status == Membership.Status.REJECTED:
        return _declined(membership), None
    if membership.status == Membership.Status.APPROVED:
        return member_home(membership)
    return None


def decision_for_requester(membership: Membership) -> BotMessage | None:
    if membership.status == Membership.Status.APPROVED:
        header = _("🎉 Your request to join <b>%(company)s</b> was approved!") % {
            "company": html.quote(membership.company.name)
        }
        return _compose(header, _next_step(membership))
    if membership.status == Membership.Status.REJECTED:
        return _declined(membership), None
    return None


def member_home(membership: Membership) -> BotMessage:
    company = {"company": html.quote(membership.company.name)}
    if membership.is_onboarded:
        header = _("✅ You're a member of <b>%(company)s</b>.") % company
    else:
        header = _("👋 Welcome to <b>%(company)s</b>!") % company
    return _compose(header, _next_step(membership))


def phone_saved(membership: Membership) -> BotMessage:
    return _compose(_("📱 Thanks, your phone number is saved."), _next_step(membership))


def foreign_contact() -> BotMessage:
    return _("Please share your own phone number with the button below."), _share_phone_keyboard()


def onboarding_complete(membership: Membership) -> BotMessage:
    header = _("🎉 Registration complete! Welcome aboard, %(name)s.") % {
        "name": html.quote(membership.first_name)
    }
    return _compose(header, _app_prompt(_("Open the app to see your tasks.")))


def _next_step(membership: Membership) -> BotMessage:
    if membership.is_onboarded:
        return _app_prompt(_("Open the app to see your tasks."))
    if not membership.user.phone:
        text = _("To finish registration, share your phone number with the button below.")
        return text, _share_phone_keyboard()
    return _app_prompt(_("Open the app to enter your name and position."))


def _app_prompt(text: str) -> BotMessage:
    if not settings.EMPLOYEE_MINIAPP_URL:
        return text, None
    button = InlineKeyboardButton(
        text=_("📱 Open app"), web_app=WebAppInfo(url=settings.EMPLOYEE_MINIAPP_URL)
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[[button]])


def _share_phone_keyboard() -> ReplyKeyboardMarkup:
    button = KeyboardButton(text=_("📱 Share my phone number"), request_contact=True)
    return ReplyKeyboardMarkup(keyboard=[[button]], resize_keyboard=True, one_time_keyboard=True)


def _compose(header: str, step: BotMessage) -> BotMessage:
    text, markup = step
    return f"{header}\n\n{text}", markup


def _declined(membership: Membership) -> str:
    text = _("Your request to join <b>%(company)s</b> was declined.") % {
        "company": html.quote(membership.company.name)
    }
    available_at = membership.rejoin_available_at
    if available_at is not None and available_at > timezone.now():
        retry = _("You can ask again after %(time)s.") % {
            "time": membership.company.format_datetime(available_at)
        }
    else:
        retry = _("You can ask again by opening the invite link.")
    return f"{text} {retry}"


def _outcome(membership: Membership) -> str:
    by = {"name": html.quote(str(membership.decided_by)) if membership.decided_by else "—"}
    if membership.status == Membership.Status.APPROVED:
        return _("✅ Approved by %(name)s") % by
    if membership.status == Membership.Status.REJECTED:
        return _("❌ Rejected by %(name)s") % by
    if membership.status == Membership.Status.BLOCKED:
        return _("⛔ Blocked by %(name)s") % by
    return str(membership.get_status_display())
