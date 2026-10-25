"""What the owner bot says. Call these under the user's language."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop, ngettext

from apps.accounts.models import User
from ownerbot.callbacks import NewCompanyStep, TodayPick

type BotMessage = tuple[str, InlineKeyboardMarkup | None]

# Offered as buttons in /new; anything else can be typed ("Asia/Bishkek", "Samarqand"…).
TIMEZONES = (
    ("Asia/Tashkent", gettext_noop("Tashkent")),
    ("Asia/Almaty", gettext_noop("Almaty")),
    ("Europe/Moscow", gettext_noop("Moscow")),
    ("Asia/Dubai", gettext_noop("Dubai")),
)


def dashboard_url(path: str = "") -> str:
    """`DASHBOARD_URL` + a dashboard path ("c/12/get-started"), or "" when unset."""
    base = settings.DASHBOARD_URL
    if not base:
        return ""
    return base.rstrip("/") + "/" + path.lstrip("/") if path else base


def _web_app_button(text: str, path: str = "") -> InlineKeyboardButton | None:
    """A Mini App button (Telegram only accepts https links), else None."""
    url = dashboard_url(path)
    if not url.startswith("https://"):
        return None
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))


def dashboard_keyboard(path: str = "") -> InlineKeyboardMarkup | None:
    """The "Open dashboard" button."""
    button = _web_app_button(_("Open dashboard"), path)
    return InlineKeyboardMarkup(inline_keyboard=[[button]]) if button else None


def welcome(user: User, companies: list[dict] | None = None) -> BotMessage:
    """`/start`: hello, the person's companies, and what the bot can do."""
    name = user.first_name or _("there")
    lines = [_("Hello, %(name)s!") % {"name": html.quote(name)}, ""]
    if companies:
        lines.append(_("Your companies:"))
        for row in companies:
            waiting = row.get("waiting", 0)
            extra = (
                " · "
                + ngettext("%(count)d waiting for you", "%(count)d waiting for you", waiting)
                % {"count": waiting}
                if waiting
                else ""
            )
            lines.append(f"• <b>{html.quote(row['name'])}</b>{html.quote(extra)}")
        lines += [
            "",
            _("/today: today's numbers and what waits for you"),
            _("/dashboard: open the dashboard"),
            _("/new: create another company"),
        ]
    else:
        lines += [
            _(
                "Here you create your company, confirm dashboard sign-ins and get approvals and "
                "alerts from your business."
            ),
            "",
            _("Start with /new to create your company."),
        ]
    return "\n".join(lines), dashboard_keyboard()


def open_dashboard() -> BotMessage:
    """`/dashboard`."""
    markup = dashboard_keyboard()
    if markup is not None:
        return _("Your dashboard: every task, sale, payment and person in one place."), markup
    url = dashboard_url()
    if url:
        return _("Open your dashboard: %(url)s") % {"url": html.quote(url)}, None
    return _("The dashboard address isn't set on this server yet."), None


# /new -------------------------------------------------------------------------------------


def cancel_row() -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(text=_("Cancel"), callback_data=NewCompanyStep(action="cancel").pack())
    ]


def signup_closed(reason: str) -> str:
    return html.quote(reason)


def ask_code() -> BotMessage:
    text = "\n".join(
        (
            "<b>" + html.quote(_("New company")) + "</b>",
            "",
            html.quote(_("Send the signup code you were given (like K7M2-QX9P).")),
        )
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[cancel_row()])


def bad_code() -> str:
    return _("This signup code isn't valid. Check it and send it again, or ask for a new one.")


def ask_name() -> BotMessage:
    text = "\n".join(
        (
            "<b>" + html.quote(_("New company")) + "</b>",
            "",
            html.quote(_("What is your company called? Send its name, as staff know it.")),
        )
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[cancel_row()])


def bad_name() -> str:
    return _("Send the name as text, up to 200 characters.")


def _offset(zone: str, now: datetime) -> str:
    delta = now.astimezone(ZoneInfo(zone)).utcoffset() or timedelta()
    hours, rest = divmod(int(delta.total_seconds()), 3600)
    minutes = rest // 60
    return f"UTC{'+' if hours >= 0 else '−'}{abs(hours)}" + (f":{minutes:02d}" if minutes else "")


def ask_timezone(name: str, now: datetime) -> BotMessage:
    text = "\n".join(
        (
            "<b>" + html.quote(name) + "</b>",
            "",
            html.quote(_("Which timezone does the company work in?")),
            html.quote(_("Tashkent fits all of Uzbekistan.")),
        )
    )
    # Tashkent, the usual answer, is green.
    buttons = [
        InlineKeyboardButton(
            text=f"{_(city)} ({_offset(zone, now)})",
            callback_data=NewCompanyStep(action="tz", value=zone).pack(),
            style="success" if zone == "Asia/Tashkent" else None,
        )
        for zone, city in TIMEZONES
    ]
    rows = [buttons[:2], buttons[2:]]
    rows.append(
        [
            InlineKeyboardButton(
                text=_("Type another"), callback_data=NewCompanyStep(action="type_tz").pack()
            )
        ]
    )
    rows.append(cancel_row())
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def type_timezone() -> str:
    return _("Send the timezone or city, like Asia/Samarkand or Bishkek.")


def bad_timezone() -> str:
    return _("I don't know that timezone. Try a city name, like Almaty or Asia/Bishkek.")


def confirm(name: str, zone: str, language: str, now: datetime) -> BotMessage:
    languages = {"uz": "O‘zbekcha", "ru": "Русский", "en": "English"}
    text = "\n".join(
        (
            "<b>" + html.quote(_("Create this company?")) + "</b>",
            "",
            _("Name: %(name)s") % {"name": f"<b>{html.quote(name)}</b>"},
            _("Timezone: %(zone)s") % {"zone": f"{html.quote(zone)} ({_offset(zone, now)})"},
            _("Language: %(language)s") % {"language": languages.get(language, language)},
            _("Base currency: %(currency)s") % {"currency": "UZS"},
            "",
            html.quote(_("You can change all of this later in the dashboard settings.")),
        )
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_("Create"), callback_data=NewCompanyStep(action="create").pack()
            ),
            InlineKeyboardButton(
                text=_("Change name"), callback_data=NewCompanyStep(action="rename").pack()
            ),
        ],
        cancel_row(),
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def created(company_id: int, name: str) -> BotMessage:
    text = "\n".join(
        (
            "<b>" + html.quote(_("%(name)s is ready.") % {"name": name}) + "</b>",
            "",
            html.quote(_("You are its owner. Next: add your branches and invite your staff.")),
        )
    )
    button = _web_app_button(_("Open Get started"), f"c/{company_id}/get-started")
    if button is None:
        url = dashboard_url(f"c/{company_id}/get-started")
        if url:
            text += "\n\n" + html.quote(_("Get started: %(url)s") % {"url": url})
        return text, None
    return text, InlineKeyboardMarkup(inline_keyboard=[[button]])


def cancelled() -> str:
    return _("Cancelled. Nothing was created.")


# /today -----------------------------------------------------------------------------------


def no_companies() -> str:
    return _("You don't have a company with dashboard access yet. Create one with /new.")


def pick_company(companies: list[tuple[int, str]]) -> BotMessage:
    rows = [
        [InlineKeyboardButton(text=name, callback_data=TodayPick(company=pk).pack())]
        for pk, name in companies
    ]
    return _("Which company?"), InlineKeyboardMarkup(inline_keyboard=rows)


def today_keyboard(company_id: int, waiting: int) -> InlineKeyboardMarkup | None:
    rows = []
    if waiting:
        approvals = _web_app_button(
            _("Approvals (%(count)d)") % {"count": waiting}, f"c/{company_id}?inbox=needs"
        )
        if approvals:
            rows.append([approvals])
    opened = _web_app_button(_("Open dashboard"), f"c/{company_id}")
    if opened:
        rows.append([opened])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
