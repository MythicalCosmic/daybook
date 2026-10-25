"""`/today`: one company's day in one message (sync; handlers call it through sync_to_async).

Built from what the owner may see there:

- branch status (`apps.console.queries.branches_today`: opened or not, plus the sales,
  attendance and task facts their modules provide);
- every brief section the modules registered (`register_brief_section`), in their order;
- how many approvals wait in "Needs you".

A brief section's `build` returns a dict; `/today` shows `{"title": str, "lines": [str]}`
(each optional; the title in bold), or `{"text": str}`. The sections that send figures for the
dashboard (tasks, attendance, finance, people) are put into words here (`FIGURES`); one the bot
has no words for is left out, never shown as raw data. An "emoji" key is ignored: the bots send
no emoji.
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
    """A branch per line, its status in words ("Chilonzor — ochilgan: soat 08:55"), and under it
    what its modules report, each fact with its label ("Savdo: …", "Ishda: 4/5")."""
    lines = []
    for card in cards:
        line = f"<b>{html.quote(card['name'])}</b> — {html.quote(_status(card))}"
        facts = []
        if sales := card.get("sales"):
            facts.append(_("Sales: %(net)s") % {"net": _money(sales.get("net", "0"), currency)})
        if attendance := card.get("attendance"):
            facts.append(
                _("At work: %(present)d/%(rostered)d")
                % {
                    "present": attendance.get("checked_in", 0),
                    "rostered": attendance.get("rostered", 0),
                }
            )
        if tasks := card.get("tasks"):
            done = _("Tasks: %(done)d/%(total)d") % {
                "done": tasks.get("done", 0),
                "total": tasks.get("total", 0),
            }
            if tasks.get("late"):
                done += ", " + _("late: %(count)d") % {"count": tasks["late"]}
            facts.append(done)
        if facts:
            line += "\n    " + html.quote(" · ".join(facts))
        lines.append(line)
    return lines


def section_lines(data: dict, key: str = "", currency: str = "UZS") -> list[str]:
    """A brief section as lines: its own title and lines, or the words for the figures a module
    sends (tasks, attendance, money, people). A section of figures the bot has no words for is
    left out rather than shown as raw data."""
    if key in FIGURES and not any(data.get(field) for field in ("title", "lines", "text")):
        title, body = FIGURES[key](data, currency)
    else:
        title = data.get("title") or SECTION_TITLES.get(key, lambda: None)()
        body = data.get("lines")
        if body is None and data.get("text"):
            body = [data["text"]]
    out = []
    if title:
        out.append(f"<b>{html.quote(str(title))}</b>")
    out += [f"    {html.quote(str(line))}" for line in body or ()]
    return out if body else []


def _names(people: list, limit: int = 5) -> str:
    names = [str(person.get("name", "")) for person in people or [] if isinstance(person, dict)]
    shown = ", ".join(names[:limit])
    if len(names) > limit:
        shown += " " + _("and %(count)d more") % {"count": len(names) - limit}
    return shown


def _tasks(data: dict, currency: str) -> tuple[str, list[str]]:
    lines = [
        _("Done today: %(done)d of %(total)d")
        % {"done": data.get("done", 0), "total": data.get("total", 0)}
    ]
    if data.get("late"):
        lines.append(_("Late: %(count)d") % {"count": data["late"]})
    if data.get("review"):
        lines.append(_("Waiting for check: %(count)d") % {"count": data["review"]})
    if data.get("on_time_7d") is not None:
        lines.append(_("On time over 7 days: %(percent)s%%") % {"percent": data["on_time_7d"]})
    worst = [task for task in data.get("late_tasks") or [] if isinstance(task, dict)][:3]
    if worst:
        lines.append(_("Most overdue:"))
        lines += [
            "    "
            + " · ".join(
                part
                for part in (task.get("title"), (task.get("assignee") or {}).get("name"))
                if part
            )
            for task in worst
        ]
    return _("Tasks"), lines


def _attendance(data: dict, currency: str) -> tuple[str, list[str]]:
    lines = [
        _("At work: %(present)d/%(rostered)d")
        % {"present": data.get("present", 0), "rostered": data.get("rostered", 0)}
    ]
    if data.get("late"):
        lines.append(_("Late: %(names)s") % {"names": _names(data["late"])})
    if data.get("not_in_yet"):
        lines.append(_("Not in yet: %(names)s") % {"names": _names(data["not_in_yet"])})
    if data.get("absent"):
        lines.append(_("Absent: %(names)s") % {"names": _names(data["absent"])})
    return _("Attendance"), lines


def _finance(data: dict, currency: str) -> tuple[str, list[str]]:
    currency = data.get("currency") or currency
    lines = []
    if data.get("cash") is not None:
        lines.append(_("Balance: %(amount)s") % {"amount": _money(data["cash"], currency)})
    if data.get("income_yesterday") is not None or data.get("expense_yesterday") is not None:
        lines.append(
            _("Yesterday: income %(income)s, spending %(spending)s")
            % {
                "income": _money(data.get("income_yesterday") or "0", currency),
                "spending": _money(data.get("expense_yesterday") or "0", currency),
            }
        )
    if data.get("receivable_overdue_count"):
        lines.append(
            _("Overdue to receive: %(amount)s (%(count)d)")
            % {
                "amount": _money(data.get("receivable_overdue") or "0", currency),
                "count": data["receivable_overdue_count"],
            }
        )
    if data.get("payable_overdue_count"):
        lines.append(
            _("Overdue to pay: %(amount)s (%(count)d)")
            % {
                "amount": _money(data.get("payable_overdue") or "0", currency),
                "count": data["payable_overdue_count"],
            }
        )
    if data.get("due_today_count"):
        lines.append(_("Payments due today: %(count)d") % {"count": data["due_today_count"]})
    return _("Finance"), lines


def _people(data: dict, currency: str) -> tuple[str, list[str]]:
    lines = []
    if data.get("headcount") is not None:
        lines.append(_("Team: %(count)d") % {"count": data["headcount"]})
    if data.get("pending_requests"):
        lines.append(_("Join requests: %(count)d") % {"count": data["pending_requests"]})
    if data.get("joined_this_week"):
        lines.append(_("New this week: %(names)s") % {"names": _names(data["joined_this_week"])})
    if data.get("off_today"):
        lines.append(_("Off today: %(names)s") % {"names": _names(data["off_today"])})
    if data.get("suspended"):
        lines.append(_("Access paused: %(count)d") % {"count": data["suspended"]})
    return _("People"), lines


# The sections whose data is figures (the dashboard draws them), in words for the chat.
FIGURES = {
    "tasks": _tasks,
    "attendance": _attendance,
    "finance": _finance,
    "members.people": _people,
}
# A title for the sections that send lines without one.
SECTION_TITLES = {"sales": lambda: _("Sales")}


def today(member: Membership, now: datetime | None = None) -> bot_messages.BotMessage:
    now = now or timezone.now()
    company = member.company
    local = timezone.localtime(now, zoneinfo.ZoneInfo(company.timezone))
    lines = [f"<b>{html.quote(company.name)}</b> · {local:%d.%m.%Y %H:%M}"]
    cards = console.branches_today(member, now)
    if cards:
        lines += [
            "",
            "<b>" + html.quote(_("Branches")) + "</b>",
            *branch_lines(cards, company.base_currency),
        ]
    for key, data in registry.collect_brief_sections(
        member, local.date(), now, branch_ids=scope.branch_ids(member)
    ):
        if section := section_lines(data, key, company.base_currency):
            lines += ["", *section]
    waiting = registry.queue_total(member)
    lines.append("")
    if waiting:
        lines.append(
            html.quote(
                ngettext(
                    "%(count)d decision waits for you.",
                    "%(count)d decisions wait for you.",
                    waiting,
                )
                % {"count": waiting}
            )
        )
    else:
        lines.append(html.quote(_("Nothing waits for your decision.")))
    return "\n".join(lines), bot_messages.today_keyboard(company.pk, waiting)
