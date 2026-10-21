"""What the company calendar gives the shared registries: palette search and the briefing
section with today's events."""

from __future__ import annotations

from datetime import date, datetime

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.agenda import bot_messages, queries
from apps.agenda.models import Event
from apps.console.registry import SearchHit
from apps.members.models import Membership


def search(member: Membership, q: str, limit: int) -> list[SearchHit]:
    q = (q or "").strip()
    if len(q) < 2:
        return []
    now = timezone.now()
    events = (
        queries.visible_events(member)
        .filter(cancelled_at__isnull=True)
        .filter(Q(title__icontains=q) | Q(place__icontains=q))
        .select_related("company", "branch")
    )
    upcoming = list(events.filter(start__gte=now).order_by("start")[:limit])
    rest = limit - len(upcoming)
    past = list(events.filter(start__lt=now).order_by("-start")[:rest]) if rest > 0 else []
    return [
        SearchHit(
            type="agenda.event",
            id=event.pk,
            title=f"{bot_messages.mark(event)} {event.title}",
            subtitle=bot_messages.event_line(event),
            url=bot_messages.dashboard_url(event),
        )
        for event in upcoming + past
    ]


def today_section(company, day: date, now: datetime, branch_ids: list[int] | None) -> dict | None:
    """Briefings and the owner bot's /today: the events of the day, in the reader's scope."""
    # Briefings reach several people: private (invited-only) events stay out.
    events = (
        Event.objects.for_company(company)
        .filter(cancelled_at__isnull=True, visibility=Event.Visibility.COMPANY)
        .annotate(attendee_count=Count("invites"))
    )
    if branch_ids is not None:
        events = events.filter(Q(branch__isnull=True) | Q(branch_id__in=branch_ids))
    found = queries.occurrences_between(events.select_related("company", "branch"), day, day)
    if not found:
        return None
    items = []
    for occurrence in found:
        event = occurrence.event
        items.append(
            {
                "id": event.pk,
                "title": event.title,
                "kind": event.kind,
                "all_day": event.all_day,
                "time": None
                if event.all_day
                else timezone.localtime(occurrence.start, queries.tz_of(company)).strftime("%H:%M"),
                "place": event.place or (event.branch.name if event.branch else ""),
                "attendees": event.attendee_count,
            }
        )
    lines = [
        f"{item['time'] or _('all day')} · {item['title']}"
        + (f" · {item['place']}" if item["place"] else "")
        for item in items
    ]
    return {"title": _("Today's events"), "count": len(items), "items": items, "lines": lines}
