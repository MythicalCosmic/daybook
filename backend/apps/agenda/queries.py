"""Read functions of the company calendar, for the API, the bots, other apps and the AI tools.

Who sees an event:

- Holders of `agenda.manage` see every event in their branch scope (company-wide events, the
  ones at their branches) and every event they attend.
- Everyone else sees company-wide events and events at their own branches that are open to the
  whole company, plus every event they are invited to or created.

Times: timed events are instants; all-day events keep their company-local days (`start` holds
local midnight of the first day, `end` local midnight of the last day). Repeating events are
expanded into occurrences on the fly.
"""

from __future__ import annotations

import calendar as pycalendar
import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.agenda.models import Event, EventAttendee
from apps.console.registry import CalendarItem
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

# An all-day event's reminder counts back from this local time on its day.
ALL_DAY_REMINDER_AT = time(9, 0)
# Colour tokens per kind (the dashboard reads them as `var(--c-<token>)`).
KIND_COLORS = {
    Event.Kind.MEETING: "chart-3",
    Event.Kind.TRAINING: "chart-6",
    Event.Kind.INVENTORY: "chart-4",
    Event.Kind.CELEBRATION: "chart-5",
    Event.Kind.DEADLINE: "danger",
    Event.Kind.OTHER: "chart-8",
}
MAX_OCCURRENCES = 400


def can_manage(member: Membership) -> bool:
    return member.has_perm(Perm.AGENDA_MANAGE)


def tz_of(company) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(company.timezone)


def local_day(moment: datetime, company) -> date:
    return timezone.localtime(moment, tz_of(company)).date()


def local_midnight(day: date, company) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=tz_of(company))


def visible_events(member: Membership) -> QuerySet[Event]:
    """Events `member` may see (cancelled ones included; callers filter)."""
    events = Event.objects.for_company(member.company_id)
    branches = scope.branch_ids(member)
    mine = Q(invites__membership=member) | Q(created_by=member)
    if can_manage(member):
        if branches is None:
            return events
        return events.filter(Q(branch__isnull=True) | Q(branch_id__in=branches) | mine).distinct()
    if branches is None:  # an owner-like role without agenda.manage
        open_to_me = Q(visibility=Event.Visibility.COMPANY)
    else:
        open_to_me = Q(visibility=Event.Visibility.COMPANY) & (
            Q(branch__isnull=True) | Q(branch_id__in=branches)
        )
    return events.filter(open_to_me | mine).distinct()


def get_event(member: Membership, event_id: int) -> Event | None:
    return (
        visible_events(member)
        .select_related("branch", "created_by__user")
        .filter(pk=event_id)
        .first()
    )


# Occurrences ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Occurrence:
    event: Event
    start: datetime  # an instant (all-day: local midnight of the first day)
    end: datetime | None
    index: int  # 0 for the first one

    @property
    def key(self) -> str:
        """Unique per occurrence: "12", or "12-20261027" for a repeating event."""
        if self.event.repeat == Event.Repeat.NONE:
            return str(self.event.pk)
        day = local_day(self.start, self.event.company)
        return f"{self.event.pk}-{day:%Y%m%d}"

    def first_day(self) -> date:
        return local_day(self.start, self.event.company)

    def last_day(self) -> date:
        if self.end is None:
            return self.first_day()
        last = local_day(self.end, self.event.company)
        # A timed event ending at midnight belongs to the day before.
        if not self.event.all_day and timezone.localtime(
            self.end, tz_of(self.event.company)
        ).time() == time(0):
            last -= timedelta(days=1)
        return max(last, self.first_day())


def _shift(start_local: datetime, step: int, repeat: str) -> datetime | None:
    if repeat == Event.Repeat.WEEKLY:
        return start_local + timedelta(days=7 * step)
    month = start_local.month - 1 + step
    year = start_local.year + month // 12
    month = month % 12 + 1
    day = min(start_local.day, pycalendar.monthrange(year, month)[1])
    return start_local.replace(year=year, month=month, day=day)


def occurrences(event: Event, first: date, last: date) -> list[Occurrence]:
    """Occurrences of `event` touching the company-local days `first`..`last` (inclusive)."""
    company = event.company
    zone = tz_of(company)
    duration = (event.end - event.start) if event.end else None
    start_local = timezone.localtime(event.start, zone)
    found: list[Occurrence] = []
    step = 0
    if event.repeat != Event.Repeat.NONE:
        # Jump close to the window instead of walking from the first occurrence.
        gap = (first - start_local.date()).days
        if gap > 0:
            step = (
                max(0, gap // 7 - 1)
                if event.repeat == Event.Repeat.WEEKLY
                else max(0, gap // 31 - 1)
            )
    while len(found) < MAX_OCCURRENCES:
        moment = _shift(start_local, step, event.repeat) if step else start_local
        if moment is None:
            break
        day = moment.date()
        if event.repeat_until and step and day > event.repeat_until:
            break
        if day > last:
            break
        occurrence = Occurrence(
            event,
            moment.astimezone(zone),
            (moment + duration).astimezone(zone) if duration is not None else None,
            step,
        )
        if occurrence.last_day() >= first:
            found.append(occurrence)
        if event.repeat == Event.Repeat.NONE:
            break
        step += 1
    return found


def occurrences_between(events, first: date, last: date) -> list[Occurrence]:
    found = []
    for event in events:
        found += occurrences(event, first, last)
    found.sort(key=lambda occurrence: (occurrence.start, occurrence.event.pk))
    return found


def in_window(member: Membership, first: date, last: date) -> QuerySet[Event]:
    """Visible, not cancelled events that may have an occurrence in the window."""
    company = member.company
    window_end = local_midnight(last + timedelta(days=1), company)
    window_start = local_midnight(first, company)
    single = Q(repeat=Event.Repeat.NONE, start__lt=window_end) & (
        Q(end__gte=window_start) | Q(end__isnull=True, start__gte=window_start - timedelta(days=1))
    )
    repeating = (
        ~Q(repeat=Event.Repeat.NONE)
        & Q(start__lt=window_end)
        & (Q(repeat_until__isnull=True) | Q(repeat_until__gte=first))
    )
    return (
        visible_events(member)
        .filter(cancelled_at__isnull=True)
        .filter(single | repeating)
        .select_related("company", "branch")
    )


def calendar_item(occurrence: Occurrence) -> CalendarItem:
    event = occurrence.event
    if event.all_day:
        start: date | datetime = occurrence.first_day()
        end: date | datetime | None = occurrence.last_day()
    else:
        start, end = occurrence.start, occurrence.end
    return CalendarItem(
        id=occurrence.key,
        kind="agenda.event",
        title=event.title,
        start=start,
        end=end,
        all_day=event.all_day,
        color=KIND_COLORS.get(event.kind, "chart-3"),
        url=f"/c/{event.company_id}/calendar?event={event.pk}",
    )


def calendar_items(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    """The calendar source `agenda.events`: the events `member` may see."""
    if member.company_id != company.pk:
        return []
    return [
        calendar_item(occurrence)
        for occurrence in occurrences_between(in_window(member, start, end), start, end)
    ]


def upcoming(member: Membership, *, now: datetime | None = None, days: int = 7, mine: bool = False):
    """Occurrences from now for `days` days (`mine`: only events `member` attends)."""
    now = now or timezone.now()
    first = local_day(now, member.company)
    last = first + timedelta(days=days)
    events = in_window(member, first, last)
    if mine:
        events = events.filter(invites__membership=member).exclude(
            invites__membership=member, invites__response=EventAttendee.Response.DECLINED
        )
    found = occurrences_between(events, first, last)
    return [
        occurrence
        for occurrence in found
        if (occurrence.end or occurrence.start) >= now
        or (occurrence.event.all_day and occurrence.last_day() >= first)
    ]


def responses(event: Event) -> dict[str, int]:
    counts = {choice: 0 for choice in EventAttendee.Response.values}
    for row in event.invites.values_list("response", flat=True):
        counts[row] += 1
    return counts


def my_invite(member: Membership, event: Event) -> EventAttendee | None:
    return EventAttendee.objects.filter(event=event, membership=member).first()


def reminder_time(occurrence: Occurrence) -> datetime | None:
    """When the attendees hear about this occurrence, or None without a reminder."""
    event = occurrence.event
    if event.remind_before is None:
        return None
    base = occurrence.start
    if event.all_day:
        base = datetime.combine(
            occurrence.first_day(), ALL_DAY_REMINDER_AT, tzinfo=tz_of(event.company)
        )
    return base - timedelta(minutes=event.remind_before)


def people(member: Membership) -> QuerySet[Membership]:
    """Approved members `member` may invite: the ones in their branch scope."""
    rows = Membership.objects.filter(
        company_id=member.company_id, status=Membership.Status.APPROVED
    ).select_related("user", "position", "home_branch")
    return scope.restrict(rows, scope.branch_ids(member), field="branches").order_by(
        "first_name", "last_name", "pk"
    )
