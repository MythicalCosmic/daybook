"""Telegram texts and keyboards about memberships, used by the bot and by backend notifications."""

from urllib.parse import urlencode, urlsplit

from aiogram import html
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from apps.members import bot_menu
from apps.members.callbacks import JoinAction, JoinDecision
from apps.members.models import Membership

type BotMessage = tuple[
    str, InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None
]

# Main menu labels. The bot matches incoming text against every translation of these.
MENU_MY_TASKS = gettext_noop("📋 My tasks")
MENU_NEW_TASK = gettext_noop("➕ New task")
MENU_APP = gettext_noop("📱 Open app")


def main_menu(membership: Membership | None = None) -> ReplyKeyboardMarkup:
    """The persistent menu: tasks first, then the buttons modules registered for this person
    (apps.members.bot_menu), then the app."""
    rows = [[KeyboardButton(text=_(MENU_MY_TASKS)), KeyboardButton(text=_(MENU_NEW_TASK))]]
    extra = []
    if membership is not None:
        extra = [_menu_button(button) for button in bot_menu.buttons_for(membership)]
    rows += [extra[index : index + 2] for index in range(0, len(extra), 2)]
    if settings.EMPLOYEE_MINIAPP_URL:
        app = WebAppInfo(url=settings.EMPLOYEE_MINIAPP_URL)
        rows.append([KeyboardButton(text=_(MENU_APP), web_app=app)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def miniapp_url(screen: str | None = None) -> str:
    """The mini app's address, opening `screen` (e.g. "payslip:12") when given."""
    url = settings.EMPLOYEE_MINIAPP_URL
    if not url or not screen:
        return url
    separator = "&" if urlsplit(url).query else "?"
    return f"{url}{separator}{urlencode({'screen': screen})}"


def _menu_button(button: bot_menu.MenuButton) -> KeyboardButton:
    if button.web_app_screen and settings.EMPLOYEE_MINIAPP_URL:
        app = WebAppInfo(url=miniapp_url(button.web_app_screen))
        return KeyboardButton(text=_(button.msgid), web_app=app)
    return KeyboardButton(text=_(button.msgid))


def join_request(membership: Membership) -> BotMessage:
    """What approvers see. Once decided, it shows the outcome instead of buttons."""
    user = membership.user
    name = html.quote(membership.full_name or user.get_full_name() or str(user))
    lines = [
        _("📝 <b>Join request</b> · %(company)s")
        % {"company": html.quote(membership.company.name)},
        "",
        _("Name: %(name)s") % {"name": f'<a href="tg://user?id={user.telegram_id}">{name}</a>'},
    ]
    if membership.position:
        lines.append(
            _("Position: %(position)s") % {"position": html.quote(membership.position.name)}
        )
    if user.phone:
        lines.append(_("Phone: %(phone)s") % {"phone": html.quote(user.phone)})
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
        company = {"company": html.quote(membership.company.name)}
        if not membership.is_onboarded:
            header = _("👋 Welcome! You're joining <b>%(company)s</b>.") % company
            return _compose(header, _create_account_prompt())
        text = (
            _(
                "⏳ Your request to join <b>%(company)s</b> is waiting for approval. "
                "I'll message you as soon as it's decided."
            )
            % company
        )
        return text, None
    if membership.status == Membership.Status.REJECTED:
        return _declined(membership), None
    if membership.status == Membership.Status.APPROVED:
        return member_home(membership)
    if membership.status == Membership.Status.SUSPENDED:
        return paused(membership)
    return None


def paused(membership: Membership) -> BotMessage:
    """What a suspended person hears, whatever they send."""
    text = paused_text(membership, company=f"<b>{html.quote(membership.company.name)}</b>")
    return f"⏸ {text}", ReplyKeyboardRemove()


def paused_text(membership: Membership, *, company: str | None = None) -> str:
    """The same in plain text (for alerts), or with `company` already formatted."""
    names = {"company": company if company is not None else membership.company.name}
    if membership.suspended_until is None:
        return _("Your access to %(company)s is paused until further notice.") % names
    return _("Your access to %(company)s is paused until %(date)s.") % {
        **names,
        "date": membership.suspended_until.strftime("%d.%m.%Y"),
    }


def reinstated(membership: Membership) -> BotMessage:
    header = _("▶️ Your access to <b>%(company)s</b> is back.") % {
        "company": html.quote(membership.company.name)
    }
    return _compose(header, _next_step(membership))


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


def offboarded(membership: Membership) -> BotMessage:
    text = _("👋 You're no longer on the team at <b>%(company)s</b>. Thank you for your work!") % {
        "company": html.quote(membership.company.name)
    }
    return text, ReplyKeyboardRemove()


def phone_saved(membership: Membership) -> BotMessage:
    return _compose(_("📱 Thanks, your phone number is saved."), _next_step(membership))


def foreign_contact() -> BotMessage:
    return _("Please share your own phone number with the button below."), _share_phone_keyboard()


def onboarding_complete(membership: Membership) -> BotMessage:
    header = _("🎉 Registration complete! Welcome aboard, %(name)s.") % {
        "name": html.quote(membership.first_name)
    }
    return _compose(header, _menu_prompt(membership))


def _next_step(membership: Membership) -> BotMessage:
    if not membership.is_onboarded:
        return _create_account_prompt()
    if membership.status == Membership.Status.APPROVED:
        return _menu_prompt(membership)
    return _(
        "Your request is waiting for approval. I'll message you as soon as it's decided."
    ), None


def _menu_prompt(membership: Membership | None = None) -> BotMessage:
    return _("Use the menu below to see your tasks or add one."), main_menu(membership)


def _create_account_prompt() -> BotMessage:
    if not settings.EMPLOYEE_MINIAPP_URL:
        return _("Accounts are created in the app, which isn't set up yet. Ask your manager."), None
    button = InlineKeyboardButton(
        text=_("📱 Create account"), web_app=WebAppInfo(url=settings.EMPLOYEE_MINIAPP_URL)
    )
    text = _("Open the app to create your account: your name, phone and position.")
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
