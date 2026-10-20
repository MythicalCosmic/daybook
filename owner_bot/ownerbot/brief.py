"""`/today`: one company's day in one message (sync; handlers call it through sync_to_async).

Built from what the owner may see there:

- branch status (`apps.console.queries.branches_today`: opened or not, plus the sales,
  attendance and task facts their modules provide);
- every brief section the modules registered (`register_brief_section`), in their order;
- how many approvals wait in "Needs you".

A brief section's `build` returns a dict; `/today` shows `{"title": str, "lines": [str],
"emoji": str}` (each optional), or `{"text": str}`, and falls back to "key: value" lines.
"""

import zoneinfo
from datetime import datetime
from decimal import Decimal, InvalidOperation

from aiogram import html
from django.utils import timezone
from django.utils.translation import get_language, ngettext
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.console import queries as console
from apps.console import registry
from apps.core.money import format_money
from apps.members import scope
from apps.members.models import Membership
from ownerbot import bot_messages

STATUS_ICONS = {"open": "🟢", "not_opened": "🔴", "closed": "⚪", "day_off": "💤"}


def memberships(user: User) -> list[Membership]:
    """Every company where `user` may open the dashboard, by name."""
    return console.owner_memberships(user)


def companies_summary(user: User) -> list[dict]:
    """For `/start`: each company's name and how much waits for the person there."""
    return [
        {
            "id": member.company_id,
            "name": member.company.name,
            "waiting": registry.queue_total(member),
        }
        for member in memberships(user)
    ]


def membership(user: User, company_id: int) -> Membership | None:
    return next((m for m in memberships(user) if m.company_id == company_id), None)


def _status(card: dict) -> str:
    labels = {
        "open": _("open"),
        "not_opened": _("not opened yet"),
        "closed": _("closed"),
        "day_off": _("day off"),
    }
    text = labels.get(card["status"], card["status"])
    sales = card.get("sales") or {}
    if card["status"] == "open" and sales.get("opened_at"):
        opened = sales["opened_at"][11:16]
        who = (sales.get("opened_by") or {}).get("name")
        text = (
            _("opened at %(time)s by %(name)s") % {"time": opened, "name": who}
            if who
            else _("opened at %(time)s") % {"time": opened}
        )
    elif card["status"] == "not_opened" and card.get("opens_at"):
        text = _("not opened yet (opens %(time)s)") % {"time": card["opens_at"]}
    return text


def _money(amount: str, currency: str) -> str:
    try:
        return format_money(Decimal(amount), currency, get_language() or "uz")
    except InvalidOperation, TypeError, ValueError:
        return str(amount)


def branch_lines(cards: list[dict], currency: str) -> list[str]:
    lines = []
    for card in cards:
        parts = [f"{STATUS_ICONS.get(card['status'], '•')} <b>{html.quote(card['name'])}</b>"]
        parts.append(html.quote(_status(card)))
        facts = []
        if sales := card.get("sales"):
            facts.append("💰 " + _money(sales.get("net", "0"), currency))
        if attendance := card.get("attendance"):
            facts.append(f"👥 {attendance.get('checked_in', 0)}/{attendance.get('rostered', 0)}")
        if tasks := card.get("tasks"):
            done = f"✅ {tasks.get('done', 0)}/{tasks.get('total', 0)}"
            if tasks.get("late"):
                done += " · ⏰ " + str(tasks["late"])
            facts.append(done)
        line = " — ".join(parts)
        if facts:
            line += "\n    " + html.quote(" · ".join(facts))
        lines.append(line)
    return lines


def section_lines(data: dict) -> list[str]:
    title = data.get("title")
    emoji = data.get("emoji") or "•"
    body = data.get("lines")
    if body is None and data.get("text"):
        body = [data["text"]]
    out = []
    if title:
        out.append(f"{emoji} <b>{html.quote(str(title))}</b>")
    out += [f"    {html.quote(str(line))}" for line in body or ()]
    if not out:
        out = [html.quote(f"{key}: {value}") for key, value in data.items()]
    return out


def today(member: Membership, now: datetime | None = None) -> bot_messages.BotMessage:
    now = now or timezone.now()
    company = member.company
    local = timezone.localtime(now, zoneinfo.ZoneInfo(company.timezone))
    lines = [f"📊 <b>{html.quote(company.name)}</b> · {local:%d.%m.%Y %H:%M}"]
    cards = console.branches_today(member, now)
    if cards:
        lines += [
            "",
            "🏪 <b>" + html.quote(_("Branches")) + "</b>",
            *branch_lines(cards, company.base_currency),
        ]
    for _key, data in registry.collect_brief_sections(
        member, local.date(), now, branch_ids=scope.branch_ids(member)
    ):
        lines += ["", *section_lines(data)]
    waiting = registry.queue_total(member)
    lines.append("")
    if waiting:
        lines.append(
            "📥 "
            + html.quote(
                ngettext(
                    "%(count)d decision waits for you.",
                    "%(count)d decisions wait for you.",
                    waiting,
                )
                % {"count": waiting}
            )
        )
    else:
        lines.append("📥 " + html.quote(_("Nothing waits for your decision.")))
    return "\n".join(lines), bot_messages.today_keyboard(company.pk, waiting)
