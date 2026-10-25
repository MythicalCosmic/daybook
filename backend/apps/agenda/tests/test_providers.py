"""What the calendar gives the registries: its source, search, briefing section, AI, buttons."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.agenda import providers, queries
from apps.agenda.models import EventAttendee
from apps.agenda.tests.factories import AttendeeFactory, EventFactory
from apps.ai.tools.testing import call_tool
from apps.console import registry
from apps.inbox.models import Notification
from apps.inbox.services import run_action

pytestmark = pytest.mark.django_db


def test_registrations():
    assert "agenda.events" in registry.CALENDAR_SOURCES
    assert "agenda.event" in registry.SEARCH
    assert "agenda.today" in registry.BRIEF_SECTIONS
    assert "agenda.events" in registry.PULSE


def test_search_finds_upcoming_events_first(company, owner):
    EventFactory(company=company, title="Kassa training")
    EventFactory(
        company=company,
        title="Kassa audit",
        start=timezone.now() - timedelta(days=5),
        end=timezone.now() - timedelta(days=5, hours=-1),
    )

    hits = providers.search(owner, "kassa", 5)

    assert [hit.title for hit in hits] == ["Kassa training", "Kassa audit"]  # no kind icon
    assert hits[0].url.startswith(f"/c/{company.pk}/calendar?event=")


def test_briefing_section_lists_todays_events_in_scope(company, chilonzor, yunusobod):
    now = timezone.now()
    day = queries.local_day(now, company)
    EventFactory(company=company, title="Here", branch=chilonzor, start=now + timedelta(minutes=5))
    EventFactory(company=company, title="There", branch=yunusobod, start=now + timedelta(minutes=5))

    everything = providers.today_section(company, day, now, None)
    scoped = providers.today_section(company, day, now, [chilonzor.pk])

    assert {item["title"] for item in everything["items"]} == {"Here", "There"}
    assert [item["title"] for item in scoped["items"]] == ["Here"]
    assert providers.today_section(company, day + timedelta(days=30), now, None) is None


def test_invite_buttons_answer_for_the_person(company, owner, alisher):
    from apps.agenda import services

    event = services.create_event(
        company,
        by=owner,
        title="Training",
        start=timezone.now() + timedelta(days=1),
        attendee_ids=[alisher.pk],
    )
    note = Notification.objects.get(kind="agenda.event_invite", recipient=alisher)

    message = run_action(note.pk, "going", by=alisher)

    assert message == "You said you'll come."
    assert EventAttendee.objects.get(event=event, membership=alisher).response == "going"


def test_ai_tool_lists_upcoming_events(company, owner, alisher):
    event = EventFactory(
        company=company, title="Planning", start=timezone.now() + timedelta(days=2)
    )
    AttendeeFactory(event=event, membership=alisher)

    result = call_tool("agenda_upcoming", owner, days=7)

    assert [row["title"] for row in result["rows"]] == ["Planning"]
    assert result["rows"][0]["attendees"] == 1
