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
from apps.members.callbacks import JoinAction, JoinDecision, JoinSetup, JoinStep
from apps.members.models import Membership

type BotMessage = tuple[
    str, InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None
]

# Main menu labels. The bot matches incoming text against every translation of these, without
# emoji (bot.filters.menu): keyboards from before 25.10.2026 still send "📋 Vazifalarim".
MENU_MY_TASKS = gettext_noop("My tasks")
MENU_NEW_TASK = gettext_noop("New task")
MENU_APP = gettext_noop("Open app")
MENU_TO_CHECK = gettext_noop("To check")
# The company switch of someone in several companies (audit X-1): "Kompaniya: Demo Dorixona".
# Keyboards from before 25.10.2026 send "🏢 Demo Dorixona ▸".
COMPANY_BUTTON = gettext_noop("Company: %(name)s")
OLD_COMPANY_BUTTON = ("🏢 ", " ▸")


def main_menu(membership: Membership | None = None) -> ReplyKeyboardMarkup:
    """The persistent menu: tasks first, "To check" for whoever checks work, then the buttons
    modules registered for this person (apps.members.bot_menu), the company switch for someone
    in several companies, and the app.

    Every button sends its text, none opens the mini app itself: Telegram gives a Mini App
    opened from a keyboard button no initData, so the app couldn't sign the person in. The bot
    answers the app's buttons with `open_app` (an inline button, which does carry initData); the
    chat's menu button (bot.commands.menu_button) opens the app as well."""
    rows = [[KeyboardButton(text=_(MENU_MY_TASKS)), KeyboardButton(text=_(MENU_NEW_TASK))]]
    extra = []
    if membership is not None:
        if checks_work(membership):
            extra.append(KeyboardButton(text=_(MENU_TO_CHECK)))
        extra += [KeyboardButton(text=_(b.msgid)) for b in bot_menu.buttons_for(membership)]
    rows += [extra[index : index + 2] for index in range(0, len(extra), 2)]
    if membership is not None and several_companies(membership):
        rows.append([KeyboardButton(text=company_button(membership.company))])
    if settings.EMPLOYEE_MINIAPP_URL:
        rows.append([KeyboardButton(text=_(MENU_APP))])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=_("Type a task or pick from the menu")[:64],
    )


def checks_work(membership: Membership) -> bool:
    """Whoever accepts or sends back finished work: tasks.confirm holders and those who give
    work (they check what they gave)."""
    from apps.members.permissions import Perm

    return membership.has_perm(Perm.TASKS_CONFIRM) or membership.has_perm(Perm.TASKS_ASSIGN)


def several_companies(membership: Membership) -> bool:
    """Whether the person is an approved member of more than one active company."""
    cached = getattr(membership, "_several_companies", None)
    if cached is None:
        cached = (
            Membership.objects.filter(
                user_id=membership.user_id,
                status=Membership.Status.APPROVED,
                company__is_active=True,
            ).count()
            > 1
        )
        membership._several_companies = cached
    return cached


def company_button(company) -> str:
    return _(COMPANY_BUTTON) % {"name": company.name}


def is_company_button(text: str | None) -> bool:
    """The company switch, in any language, also as old keyboards still write it."""
    if not text:
        return False
    start, end = OLD_COMPANY_BUTTON
    if text.startswith(start) and text.endswith(end):
        return True
    return any(text.startswith(prefix) for prefix in _company_prefixes())


def _company_prefixes() -> list[str]:
    from django.utils import translation

    prefixes = []
    for code, _name in settings.LANGUAGES:
        with translation.override(code):
            prefix = _(COMPANY_BUTTON).split("%(name)s")[0]
        if prefix.strip():
            prefixes.append(prefix)
    return prefixes


def open_app(screen: str | None = None, label: str | None = None) -> BotMessage:
    """The answer to a menu button that opens the mini app (at `screen`): an inline button,
    which opens it signed in."""
    button = InlineKeyboardButton(
        text=label or _(MENU_APP), web_app=WebAppInfo(url=miniapp_url(screen))
    )
    text = _("Tap the button to open the app.")
    if settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):  # the chat's menu button opens it
        text += " " + _(
            "The «%(button)s» button next to the message field opens it in one tap."
        ) % {"button": _(MENU_APP)}
    return text, InlineKeyboardMarkup(inline_keyboard=[[button]])


def miniapp_url(screen: str | None = None) -> str:
    """The mini app's address, opening `screen` (e.g. "payslip:12") when given."""
    url = settings.EMPLOYEE_MINIAPP_URL
    if not url or not screen:
        return url
    separator = "&" if urlsplit(url).query else "?"
    return f"{url}{separator}{urlencode({'screen': screen})}"


def join_request(membership: Membership) -> BotMessage:
    """What approvers see. Once decided, it shows the outcome instead of buttons."""
    user = membership.user
    name = html.quote(membership.full_name or user.get_full_name() or str(user))
    lines = [
        _("<b>Join request</b> · %(company)s") % {"company": html.quote(membership.company.name)},
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
            text=_("Approve"),
            callback_data=JoinDecision(
                action=JoinAction.APPROVE, membership_id=membership.pk
            ).pack(),
        ),
        InlineKeyboardButton(
            text=_("Reject"),
            callback_data=JoinDecision(
                action=JoinAction.REJECT, membership_id=membership.pk
            ).pack(),
        ),
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[buttons])


def status(membership: Membership | None) -> BotMessage | None:
    """The reply for someone using the bot. None means stay silent (blocked people)."""
    if membership is None or membership.status == Membership.Status.LEFT:
        return _("Hi! To join your company, open the invite link your manager sent you."), None
    if membership.status == Membership.Status.PENDING:
        company = {"company": html.quote(membership.company.name)}
        if not membership.is_onboarded:
            header = _("Welcome! You're joining <b>%(company)s</b>.") % company
            return _compose(header, _create_account_prompt())
        text = (
            _(
                "Your request to join <b>%(company)s</b> is waiting for approval. "
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
    return text, ReplyKeyboardRemove()


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
    header = _("Your access to <b>%(company)s</b> is back.") % {
        "company": html.quote(membership.company.name)
    }
    return _compose(header, _next_step(membership))


def decision_for_requester(membership: Membership) -> BotMessage | None:
    if membership.status == Membership.Status.APPROVED:
        header = _("Your request to join <b>%(company)s</b> was approved!") % {
            "company": html.quote(membership.company.name)
        }
        return _compose(header, _next_step(membership))
    if membership.status == Membership.Status.REJECTED:
        return _declined(membership), None
    return None


def member_home(membership: Membership) -> BotMessage:
    company = {"company": html.quote(membership.company.name)}
    if membership.is_onboarded:
        header = _("You're a member of <b>%(company)s</b>.") % company
        if summary := _work_summary(membership):
            header += "\n" + summary
    else:
        header = _("Welcome to <b>%(company)s</b>!") % company
    text, markup = _compose(header, _next_step(membership))
    if membership.is_onboarded and membership.status == Membership.Status.APPROVED:
        text += "\n\n" + _("Language: /language · Help: /help")
    return text, markup


def _work_summary(membership: Membership) -> str:
    """One line of what's on the person's plate (audit B-7): open, late, waiting for them."""
    from django.utils import timezone

    from apps.tasks import queries
    from apps.tasks.models import Task

    work = queries.open_work(membership)
    total = work.count()
    if not total and not checks_work(membership):
        return ""
    late = work.filter(status__in=Task.OPEN_STATUSES, due_at__lt=timezone.now()).count()
    parts = [_("Open: %(count)d") % {"count": total}]
    if late:
        parts.append(_("late: %(count)d") % {"count": late})
    if checks_work(membership):
        waiting = queries.awaiting_review_by(membership).count()
        if waiting:
            parts.append(_("to check: %(count)d") % {"count": waiting})
    return " · ".join(parts)


def offboarded(membership: Membership) -> BotMessage:
    text = _("You're no longer on the team at <b>%(company)s</b>. Thank you for your work!") % {
        "company": html.quote(membership.company.name)
    }
    return text, ReplyKeyboardRemove()


def phone_saved(membership: Membership) -> BotMessage:
    return _compose(_("Thanks, your phone number is saved."), _next_step(membership))


def foreign_contact() -> BotMessage:
    return _("Please share your own phone number with the button below."), _share_phone_keyboard()


def onboarding_complete(membership: Membership) -> BotMessage:
    header = _("Registration complete! Welcome aboard, %(name)s.") % {
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
        text=_("Create account"), web_app=WebAppInfo(url=settings.EMPLOYEE_MINIAPP_URL)
    )
    text = _("Open the app to create your account: your name, phone and position.")
    return text, InlineKeyboardMarkup(inline_keyboard=[[button]])


def _share_phone_keyboard() -> ReplyKeyboardMarkup:
    button = KeyboardButton(text=_("Share my phone number"), request_contact=True)
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
        return _("Approved by %(name)s") % by
    if membership.status == Membership.Status.REJECTED:
        return _("Rejected by %(name)s") % by
    if membership.status == Membership.Status.BLOCKED:
        return _("Blocked by %(name)s") % by
    return str(membership.get_status_display())


# Join requests through the inbox, and approving one with branches in the bot ----------


def join_request_title(membership: Membership) -> str:
    """The inbox copy's title (plain text: the inbox escapes it)."""
    return _("Join request · %(name)s") % {"name": _requester_name(membership)}


def join_request_body(membership: Membership) -> str:
    user = membership.user
    lines = [_("Company: %(company)s") % {"company": membership.company.name}]
    if membership.position:
        lines.append(_("Position: %(position)s") % {"position": membership.position.name})
    if user.phone:
        lines.append(_("Phone: %(phone)s") % {"phone": user.phone})
    if user.telegram_username:
        lines.append(_("Username: @%(username)s") % {"username": user.telegram_username})
    return "\n".join(lines)


def join_setup(
    membership: Membership,
    *,
    branches: list,
    chosen: list[int],
    role,
    nid: int,
) -> BotMessage:
    """Step 1 of approving in a company with several branches: pick the branches (and the role,
    optionally), then Approve."""
    name = html.quote(membership.first_name or _requester_name(membership))
    lines = [
        _join_header(membership),
        "",
        _("<b>Where will %(name)s work?</b> Tap the branches, then approve.") % {"name": name},
    ]
    # The choice in words; the chosen buttons are coloured too (no tick marks).
    names = [html.quote(branch.name) for branch in branches if branch.pk in chosen]
    if names:
        lines.append(_("Chosen: %(names)s") % {"names": ", ".join(names)})
    packed = _pack(chosen, branches)
    role_id = role.pk if role is not None and not role.is_default else 0
    rows = []
    row: list[InlineKeyboardButton] = []
    for branch in branches:
        row.append(
            _setup_button(
                branch.name,
                JoinStep.BRANCH,
                membership,
                style="success" if branch.pk in chosen else None,
                nid=nid,
                branches=packed,
                role=role_id,
                pick=branch.pk,
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    role_name = role.name if role is not None else "—"
    rows.append(
        [
            _setup_button(
                _("Role: %(role)s") % {"role": role_name},
                JoinStep.ROLES,
                membership,
                nid=nid,
                branches=packed,
                role=role_id,
            )
        ]
    )
    rows.append(
        [
            _setup_button(
                _("Approve"),
                JoinStep.APPROVE,
                membership,
                nid=nid,
                branches=packed,
                role=role_id,
            ),
            _setup_button(_("Back"), JoinStep.BACK, membership, nid=nid),
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def join_home(
    membership: Membership, *, branches: list, chosen: list[int], role_id: int, nid: int
) -> BotMessage:
    """Step 2 when they work in several branches: which one is home (new tasks belong to it)."""
    name = html.quote(membership.first_name or _requester_name(membership))
    lines = [
        _join_header(membership),
        "",
        _("<b>Which is %(name)s's home branch?</b> New tasks will belong to it.") % {"name": name},
    ]
    packed = _pack(chosen, branches)
    rows = [
        [
            _setup_button(
                branch.name,
                JoinStep.HOME,
                membership,
                nid=nid,
                branches=packed,
                role=role_id,
                pick=branch.pk,
            )
        ]
        for branch in branches
        if branch.pk in chosen
    ]
    rows.append(
        [
            _setup_button(
                _("Back"),
                JoinStep.ROLE,
                membership,
                nid=nid,
                branches=packed,
                role=role_id,
                pick=role_id,
            )
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def join_roles(
    membership: Membership,
    *,
    roles: list,
    current_id: int,
    branches: list,
    chosen: list[int],
    nid: int,
) -> BotMessage:
    """The roles the approver may give; the default one first."""
    lines = [_join_header(membership), "", _("<b>Which role?</b> It decides what they may do.")]
    packed = _pack(chosen, branches)
    rows = []
    for role in roles:
        value = 0 if role.is_default else role.pk
        selected = value == current_id
        label = role.name + (" · " + _("default") if role.is_default else "")
        if selected:  # in words; its button is coloured too
            lines.append(_("Chosen: %(names)s") % {"names": html.quote(label)})
        rows.append(
            [
                _setup_button(
                    label,
                    JoinStep.ROLE,
                    membership,
                    style="success" if selected else None,
                    nid=nid,
                    branches=packed,
                    role=current_id,
                    pick=value,
                )
            ]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def unpack_branches(text: str, branches: list) -> list[int]:
    """The ids of the branches a button's choice names (see `_pack`), in branch order."""
    try:
        mask = int(text or "0", 36)
    except ValueError:
        return []
    return [branch.pk for index, branch in enumerate(branches) if mask >> index & 1]


def _pack(chosen: list[int], branches: list) -> str:
    """The chosen branches as a base-36 bitmask over the approver's branches in order: Telegram
    allows 64 bytes of callback data, which a list of ids outgrows once ids are long."""
    mask = sum(1 << index for index, branch in enumerate(branches) if branch.pk in chosen)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    packed = ""
    while mask:
        mask, rest = divmod(mask, 36)
        packed = digits[rest] + packed
    return packed


def _join_header(membership: Membership) -> str:
    user = membership.user
    lines = [
        _("<b>Join request</b> · %(company)s") % {"company": html.quote(membership.company.name)},
        _("Name: %(name)s") % {"name": html.quote(_requester_name(membership))},
    ]
    if membership.position:
        lines.append(
            _("Position: %(position)s") % {"position": html.quote(membership.position.name)}
        )
    if user.phone:
        lines.append(_("Phone: %(phone)s") % {"phone": html.quote(user.phone)})
    return "\n".join(lines)


def _requester_name(membership: Membership) -> str:
    user = membership.user
    return membership.full_name or user.get_full_name() or str(user)


def _setup_button(
    text: str, step: JoinStep, membership: Membership, *, style: str | None = None, **fields
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=JoinSetup(step=step, membership_id=membership.pk, **fields).pack(),
        style=style,
    )
