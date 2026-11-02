"""What the bots say about payroll: `/pay` in the employee bot.

Every function renders in the active language (callers wrap them in the person's
`translation.override`) and returns `(text, markup)`. Bonuses, fines, advances and payslips
reach people as inbox notifications (`notify.py`); the payslip's PDF follows its message.
"""

from datetime import date
from decimal import Decimal

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils.translation import gettext as _

from apps.members.bot_messages import BotMessage, miniapp_url
from apps.members.models import Membership
from apps.payroll import queries
from apps.payroll.models import Payslip

WALLET = "wallet"


def _money(amount, currency: str) -> str:
    return html.quote(queries.money_text(Decimal(amount), currency))


def _open_button() -> InlineKeyboardMarkup | None:
    """The mini app's wallet, when the app has an https address (Telegram needs one)."""
    if not settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):
        return None
    button = InlineKeyboardButton(
        text=_("Open my pay"), web_app=WebAppInfo(url=miniapp_url(WALLET))
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def module_off() -> BotMessage:
    return _("Payroll isn't switched on for this company."), None


def my_pay(member: Membership, earnings: dict, last: Payslip | None) -> BotMessage:
    """`/pay`: this month so far, the month's estimate, bonuses and fines, the last payslip."""
    currency = earnings["currency"]
    month = queries.month_label(date.fromisoformat(earnings["period"]))
    lines = [f"<b>{html.quote(_('My pay'))}</b>"]
    if not earnings["has_pay_setup"]:
        lines.append(html.quote(_("Your pay isn't set up yet. Ask your manager.")))
    else:
        so_far = earnings["so_far"]
        estimate = earnings["estimate"]
        lines.append(
            html.quote(_("Earned so far in %(month)s:") % {"month": month})
            + f" <b>{_money(so_far['net'], currency)}</b>"
        )
        lines.append(
            html.quote(_("Estimate for the month:")) + " " + _money(estimate["net"], currency)
        )
        bonuses = Decimal(estimate["bonuses"])
        fines = -Decimal(estimate["fines"])
        if bonuses or fines:
            lines.append(
                html.quote(_("Bonuses: %(bonuses)s · Fines: %(fines)s"))
                % {"bonuses": _money(bonuses, currency), "fines": _money(fines, currency)}
            )
        if earnings["proposed"]:
            lines.append(
                html.quote(_("Waiting for approval: %(count)s"))
                % {"count": len(earnings["proposed"])}
            )
    if last is not None:
        state = {
            Payslip.Status.PAID: _("paid"),
            Payslip.Status.PUBLISHED: _("not paid yet"),
        }.get(last.status, "")
        lines += [
            "",
            html.quote(
                _("Last payslip: %(month)s, %(amount)s")
                % {
                    "month": queries.month_label(last.run.period),
                    "amount": queries.money_text(last.net, last.currency),
                }
            )
            + (f" ({html.quote(state)})" if state else ""),
        ]
    return "\n".join(lines), _open_button()
