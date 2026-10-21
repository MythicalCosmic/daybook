"""The company calendar: every calendar source a person may see, in one list.

Modules register sources with `console.registry.register_calendar_source` (holidays and time
off, birthdays and contract ends, shifts, payroll dates, bills, milestones… and this app's own
events, `agenda.events`). A person sees a source when they hold its permission and its module
is on; a source that fails is logged and left out, so the calendar never breaks because of it.
"""

from __future__ import annotations

from datetime import date

from apps.agenda import serializers
from apps.agenda.models import Event
from apps.console import registry
from apps.members.models import Membership

OWN = "agenda.events"


def sources(member: Membership) -> list[dict]:
    """The sources `member` may see, in registration order: `[{key, label}]`."""
    return [
        {"key": source.key, "label": str(source.label)}
        for source in registry.CALENDAR_SOURCES.visible_to(member)
    ]


def items(
    member: Membership, first: date, last: date, *, only: list[str] | None = None
) -> list[dict]:
    """Every item of the visible sources (or of `only`) between the two days, inclusive,
    in start order, as the API sends them (each tagged with its source)."""
    found: list[dict] = []
    for source in registry.CALENDAR_SOURCES.visible_to(member):
        if only is not None and source.key not in only:
            continue
        for item in registry.collect_calendar(member, first, last, sources=[source.key]):
            found.append(serializers.item_json(source.key, item, member.company))
    _add_places(found)
    found.sort(key=lambda row: (row["start"][:10], not row["all_day"], row["start"], row["id"]))
    return found


def _add_places(rows: list[dict]) -> None:
    """A second line for the company's own events: where they happen (other sources: none)."""
    ids = {int(row["id"].split(":", 1)[1].split("-", 1)[0]) for row in rows if row["source"] == OWN}
    places = {
        event.pk: event.place or (event.branch.name if event.branch else "")
        for event in Event.objects.filter(pk__in=ids).select_related("branch")
    }
    for row in rows:
        row["subtitle"] = ""
        if row["source"] == OWN:
            row["subtitle"] = places.get(int(row["id"].split(":", 1)[1].split("-", 1)[0]), "")
