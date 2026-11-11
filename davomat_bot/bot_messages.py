"""What the Davomat bot says outside `/today` and `/me` (views.py). Call these under the
person's language. Plain and short, no emoji (apps.notifications.emoji)."""

from aiogram import html
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)
from django.conf import settings
from django.utils.translation import gettext as _

from apps.accounts.telegram_chat import LANGUAGE_BUTTON
from apps.companies.models import Company
from apps.davomat import conf as davomat_conf
from apps.members.models import Membership
from apps.members.permissions import Perm
from davomat_bot.callbacks import HomeLanguage

type BotMessage = tuple[str, InlineKeyboardMarkup | None]
type MenuButton = MenuButtonWebApp | MenuButtonCommands

START_LINK = "link_"
# Telegram's limit for the words on the button beside the message field (kept short anyway).
MENU_TEXT_LIMIT = 32


def dashboard_url(path: str = "") -> str:
    """`DASHBOARD_URL` + a dashboard path ("c/1/attendance"), or "" when unset."""
    base = settings.DASHBOARD_URL
    if not base:
        return ""
    return base.rstrip("/") + "/" + path.lstrip("/") if path else base


def app_url(path: str = "") -> str:
    """The web app's address to open inside Telegram, or "" when there is none Telegram takes
    (it opens only https addresses as a Mini App)."""
    url = dashboard_url(path)
    return url if url.startswith("https://") else ""


def open_button(text: str, path: str = "") -> InlineKeyboardButton | None:
    """Opens the web app inside Telegram as a Mini App, already signed in: the launch data the
    organization's bot signs says who it is (apps.signin), no password. Mini App buttons work
    in private chats only, the only chats this bot talks in; a place that isn't one would need
    a link (`url=`) instead."""
    url = app_url(path)
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url)) if url else None


def menu_button(member: Membership | None) -> MenuButton:
    """The button beside the message field: for people who use the web app, the web app itself
    as a Mini App (named as the product, "Davomat" unless the organization renamed it); for
    everyone else the command menu (an employee's day is in /me; the web app has nothing for
    them, and their launch data would only get "no access")."""
    url = app_url(f"c/{member.company_id}") if uses_dashboard(member) else ""
    if not url:
        return MenuButtonCommands()
    return web_app_menu(url, davomat_conf.product_name(member.company))


def web_app_menu(url: str, product: str) -> MenuButtonWebApp:
    text = (product or davomat_conf.PRODUCT).strip()[:MENU_TEXT_LIMIT] or davomat_conf.PRODUCT
    return MenuButtonWebApp(text=text, web_app=WebAppInfo(url=url))


def sees_attendance(member: Membership | None) -> bool:
    return (
        member is not None
        and member.status == Membership.Status.APPROVED
        and member.company.has_feature("attendance")
        and member.has_perm(Perm.ATTENDANCE_VIEW)
    )


# `/report` sends the report by person: what an accountant asks for.
REPORT_KIND = "summary"


def may_download(member: Membership | None) -> bool:
    """`/report`: attendance.view and data.export, as the web app's export asks."""
    from apps.attendance import reports
    from apps.exports.registry import get_exporter, may_export

    exporter = get_exporter(reports.EXPORTERS[REPORT_KIND])
    return sees_attendance(member) and exporter is not None and may_export(member, exporter)


def uses_dashboard(member: Membership | None) -> bool:
    return (
        member is not None
        and member.status == Membership.Status.APPROVED
        and member.has_perm(Perm.DASHBOARD_ACCESS)
    )


def home_keyboard(member: Membership | None) -> InlineKeyboardMarkup:
    """The web app (for people who use it) and the one "Til / Язык / Language" button."""
    rows = []
    if uses_dashboard(member):
        button = open_button(_("Open Davomat"), f"c/{member.company_id}")
        if button is not None:
            rows.append([button])
    rows.append(
        [InlineKeyboardButton(text=LANGUAGE_BUTTON, callback_data=HomeLanguage(code="").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def commands_lines(member: Membership | None) -> list[str]:
    lines = []
    if sees_attendance(member):
        lines.append(_("/today: who is at work, who is late and who isn't in yet"))
    if may_download(member):
        lines.append(_("/report: the month's attendance report, Excel or PDF"))
    lines += [
        _("/me: your day and your month"),
        _("/language: change language"),
        _("/help: what this bot does"),
    ]
    return lines


def home(member: Membership | None, company: Company | None, first_name: str) -> BotMessage:
    """`/start`: hello, and what the bot does for this person."""
    if company is None:
        return _("Davomat isn't set up yet. Come back once your administrator has set it up."), None
    hello = _("Hello, %(name)s!") % {"name": html.quote(first_name)} if first_name else _("Hello!")
    organization = f"<b>{html.quote(company.name)}</b>"
    if member is None:
        lines = [
            hello,
            "",
            _("This is the attendance bot of %(organization)s.") % {"organization": organization},
            _(
                "To get your arrivals, departures and reports here, ask your administrator for "
                "the Telegram link of your profile and open it."
            ),
        ]
        return "\n".join(lines), home_keyboard(None)
    lines = [
        hello,
        "",
        _("You are linked to %(organization)s.") % {"organization": organization},
        _("Your arrivals and departures come here."),
        "",
        *commands_lines(member),
    ]
    return "\n".join(lines), home_keyboard(member)


def linked(member: Membership) -> BotMessage:
    """A link code claimed: who this Telegram now belongs to, and what comes next."""
    name = member.full_name or member.user.get_full_name() or member.user.username
    lines = [
        _("Done. This Telegram is now linked to %(name)s at %(organization)s.")
        % {
            "name": f"<b>{html.quote(name)}</b>",
            "organization": html.quote(member.company.name),
        },
        _("Your arrivals and departures come here."),
        "",
        *commands_lines(member),
    ]
    return "\n".join(lines), home_keyboard(member)


def link_failed(reason: str | None = None) -> str:
    return html.quote(reason) if reason else bad_link()


def bad_link() -> str:
    return _("This link doesn't work any more. Ask your administrator for a new one.")


def not_linked() -> str:
    return _(
        "This Telegram isn't linked to anyone yet. Ask your administrator for the Telegram "
        "link of your profile and open it."
    )


def not_for_you() -> str:
    return _("Only managers see who is at work today. Your own day: /me")


def module_off() -> str:
    return _("Attendance isn't switched on.")


def help_text(member: Membership | None, company: Company | None) -> str:
    """`/help`: the commands, and where the rest lives."""
    if company is None:
        return _("Davomat isn't set up yet. Come back once your administrator has set it up.")
    if member is None:
        return not_linked()
    lines = [
        f"<b>{html.quote(company.name)}</b> · Davomat",
        "",
        _("Your arrivals and departures come here, as the terminals see you."),
        "",
        *commands_lines(member),
    ]
    if uses_dashboard(member):
        lines += ["", web_app_line()]
    return "\n".join(lines)


def web_app_line() -> str:
    """Where the web app is, for the people who use it: inside Telegram when it can open there."""
    if app_url():
        return _(
            "Reports, schedules and the team are in the Davomat web app: the Davomat button "
            "next to the message field opens it here, no password needed."
        )
    return _("Reports, schedules and the team are in the Davomat web app.")
