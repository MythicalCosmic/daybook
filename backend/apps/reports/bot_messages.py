"""The weekly report managers get from the bot."""

from datetime import timedelta

from aiogram import html
from django.utils.translation import gettext as _

from apps.members.bot_messages import BotMessage
from apps.reports.kpis import Score, TeamReport

PEOPLE_LIMIT = 20


def weekly(report: TeamReport) -> BotMessage:
    last_day = report.end - timedelta(days=1)
    totals = report.totals
    lines = [
        _("📊 <b>Last week</b> · %(start)s–%(end)s")
        % {"start": report.start.strftime("%d.%m"), "end": last_day.strftime("%d.%m")},
        "",
        _("On time: <b>%(percent)s</b>, %(on_time)d of %(total)d tasks.")
        % {"percent": _percent(totals), "on_time": totals.on_time, "total": totals.total},
        _("Late: %(late)d · not done: %(missed)d · reminders sent: %(reminders)d")
        % {"late": totals.late, "missed": totals.missed, "reminders": totals.reminders},
        "",
    ]
    people = [(person, score) for person, score in report.rows if score.total]
    for person, score in people[:PEOPLE_LIMIT]:
        lines.append(f"• {html.quote(str(person))}: {_details(score)}")
    if (more := len(people) - PEOPLE_LIMIT) > 0:
        lines.append(_("…and %(count)d more") % {"count": more})
    return "\n".join(lines), None


def _details(score: Score) -> str:
    details = [_percent(score)]
    if score.late:
        details.append(_("%(count)d late") % {"count": score.late})
    if score.missed:
        details.append(_("%(count)d not done") % {"count": score.missed})
    return ", ".join(details)


def _percent(score: Score) -> str:
    return "—" if score.on_time_percent is None else f"{score.on_time_percent}%"
