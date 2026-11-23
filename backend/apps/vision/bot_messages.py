"""What the bots say about Ko‘z alerts (docs/KOZ.md §7), in the reader's language: call these under
`translation.override`. No emoji (the owner's rule, 25.10.2026): a bold first line says what and
where, the lines under it the numbers.

    Navbat · Kassa 1 (Asosiy)
    3 mijoz kutmoqda, eng uzog‘i 2 daq 10 s.
    Kassada: 1 farmatsevt                                   [Men boraman]

Pressing the button adds "Alimardon boryapti · 16:42" to every copy and takes the button away;
when the alert ends every copy says how it ended instead of the numbers.
"""

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.attendance import clock
from apps.vision.callbacks import KozButton
from apps.vision.models import Alert


def duration(seconds: int | float | None) -> str:
    """ "2 min 10 s", "45 s", "1 h 5 min" in the reader's language."""
    total = max(int(seconds or 0), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return _("%(h)s h %(m)s min") % {"h": hours, "m": minutes}
    if minutes and secs:
        return _("%(m)s min %(s)s s") % {"m": minutes, "s": secs}
    if minutes:
        return _("%(m)s min") % {"m": minutes}
    return _("%(s)s s") % {"s": secs}


def title(alert: Alert) -> str:
    names = {"camera": alert.camera.name if alert.camera else "", "branch": alert.branch.name}
    if alert.kind == Alert.Kind.QUEUE:
        return _("Queue · %(camera)s (%(branch)s)") % names
    if alert.kind == Alert.Kind.UNATTENDED:
        return _("Nobody at the counter · %(camera)s (%(branch)s)") % names
    if alert.state == Alert.State.RESOLVED and alert.ending == Alert.Ending.BACK:
        return _("Ko‘z box back online · %(branch)s") % names
    started = alert.announced_at or alert.last_event_at
    minutes = max(int((started - alert.started_at).total_seconds() // 60), 1)
    return _("Ko‘z box offline · %(branch)s (for %(minutes)s min)") % {
        **names,
        "minutes": minutes,
    }


def numbers(alert: Alert) -> list[str]:
    """The lines under the title while the alert is open."""
    if alert.kind == Alert.Kind.AGENT_OFFLINE:
        return [
            _("Box: %(name)s") % {"name": alert.agent.name},
            _("Last report: %(time)s") % {"time": clock.hhmm(alert.company, alert.started_at)},
        ]
    values = {"count": alert.queue, "wait": duration(alert.wait_s)}
    if alert.kind == Alert.Kind.UNATTENDED:
        return [
            ngettext(
                "%(count)s customer has been waiting %(wait)s.",
                "%(count)s customers have been waiting %(wait)s.",
                alert.queue,
            )
            % values
        ]
    waiting = (
        ngettext(
            "%(count)s customer waiting, the longest %(wait)s.",
            "%(count)s customers waiting, the longest %(wait)s.",
            alert.queue,
        )
        % values
    )
    if alert.staff:
        staff = ngettext(
            "At the counter: %(count)s pharmacist",
            "At the counter: %(count)s pharmacists",
            alert.staff,
        ) % {"count": alert.staff}
    else:
        staff = _("Nobody at the counter")
    return [waiting, staff]


def going(alert: Alert) -> str:
    member = alert.acknowledged_by
    name = (member.first_name or str(member)) if member else ""
    return _("%(name)s is going · %(time)s") % {
        "name": name,
        "time": clock.hhmm(alert.company, alert.acknowledged_at),
    }


def ended(alert: Alert) -> str:
    if alert.ending == Alert.Ending.STALE:
        return _("Closed: no news from the box for 2 hours")
    if alert.ending == Alert.Ending.REMOVED:
        return _("Closed: the box was removed")
    lasted = duration(alert.duration_s)
    if alert.kind == Alert.Kind.AGENT_OFFLINE:
        return _("Offline: %(duration)s") % {"duration": lasted}
    if alert.kind == Alert.Kind.QUEUE:
        return _("Queue over · lasted %(duration)s · at most %(peak)s people") % {
            "duration": lasted,
            "peak": alert.peak_queue,
        }
    if alert.staff:
        return _("A pharmacist came to the counter · lasted %(duration)s") % {"duration": lasted}
    return _("The customers left · lasted %(duration)s") % {"duration": lasted}


def alert_message(alert: Alert, *, manager: bool) -> tuple[str, InlineKeyboardMarkup | None]:
    """A copy of the alert as it is now: open with its numbers and the button, acknowledged,
    or over."""
    lines = [f"<b>{html.quote(title(alert))}</b>"]
    is_open = alert.state == Alert.State.OPEN
    if is_open:
        lines += [html.quote(line) for line in numbers(alert)]
    if alert.acknowledged_by_id is not None:
        lines.append(html.quote(going(alert)))
    if not is_open:
        lines.append(html.quote(ended(alert)))
    rows = []
    if is_open and alert.kind in Alert.CAMERA_KINDS and alert.acknowledged_by_id is None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_("I'll go"), callback_data=KozButton(alert_id=alert.pk).pack()
                )
            ]
        )
    if manager and (button := _open_button(alert)):
        rows.append([button])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _open_button(alert: Alert) -> InlineKeyboardButton | None:
    """Opens Ko‘z in the dashboard (Telegram takes only https Mini App links)."""
    base = settings.DASHBOARD_URL
    if not base.startswith("https://"):
        return None
    url = f"{base.rstrip('/')}/c/{alert.company_id}/vision"
    return InlineKeyboardButton(text=_("Open"), web_app=WebAppInfo(url=url))
