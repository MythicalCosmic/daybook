"""Edge cases found in review: tenancy on every endpoint, list query counts, reminders "at the
start", private events in briefings, branch planners editing wider events, "mine" filters."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.agenda import providers, queries, services
from apps.agenda.models import Event, EventAttendee
from apps.agenda.tests.factories import AttendeeFactory, EventFactory
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Asia/Tashkent")
TODAY = timezone.now().astimezone(TZ).date()
TOMORROW = TODAY + timedelta(days=1)


def at(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=TZ)


def owner_url(company, path="") -> str:
    return f"/api/v1/owner/companies/{company.pk}/calendar/{path}"


def app_url(company, path="") -> str:
    return f"/api/v1/companies/{company.pk}/calendar/{path}"


# Tenancy ----------------------------------------------------------------------------------


def test_every_endpoint_hides_another_companys_events(
    company, other_company, owner, alisher, owner_api, api_as, member
):
    stranger = member(other_company)
    event = EventFactory(company=other_company, title="Their meeting")
    AttendeeFactory(event=event, membership=stranger)
    client = owner_api(owner)

    assert client.get(owner_url(company, f"events/{event.pk}/")).status_code == 404
    for method, path, body in [
        ("patch", f"events/{event.pk}/", {"title": "Mine now"}),
        ("post", f"events/{event.pk}/cancel/", {}),
        ("post", f"events/{event.pk}/remind/", {}),
        ("post", f"events/{event.pk}/respond/", {"response": "going"}),
    ]:
        response = getattr(client, method)(owner_url(company, path), body, format="json")
        assert response.status_code == 404, path
    assert client.get(owner_url(other_company, "")).status_code == 404
    assert client.get(owner_url(other_company, "events/")).status_code == 404

    app = api_as(alisher)
    assert app.get(app_url(company, f"events/{event.pk}/")).status_code == 404
    assert (
        app.post(app_url(company, f"events/{event.pk}/respond/"), {"response": "going"}).status_code
        == 404
    )
    assert app.get(app_url(other_company, "")).status_code == 404

    # Another company's people and branches inside a payload are refused.
    their_branch = other_company.branches.first()
    for body in ({"attendee_ids": [stranger.pk]}, {"branch": their_branch.pk}):
        response = client.post(
            owner_url(company, "events/"),
            {"title": "Sneaky", "start": at(TOMORROW, 9).isoformat(), **body},
            format="json",
        )
        assert response.status_code == 400, body
    event.refresh_from_db()
    assert event.title == "Their meeting" and event.cancelled_at is None


# Query counts -----------------------------------------------------------------------------


def _events(company, people, n):
    for index in range(n):
        event = EventFactory(company=company, start=timezone.now() + timedelta(days=1, hours=index))
        for person in people:
            AttendeeFactory(
                event=event,
                membership=person,
                response=EventAttendee.Response.GOING if index % 2 else "pending",
            )


def test_event_list_queries_dont_grow_with_rows(
    company, owner, alisher, nigora, owner_api, django_assert_max_num_queries
):
    client = owner_api(owner)
    _events(company, [owner, alisher, nigora], 2)
    with django_assert_max_num_queries(40) as few:
        assert client.get(owner_url(company, "events/")).status_code == 200
    _events(company, [owner, alisher, nigora], 12)
    with django_assert_max_num_queries(len(few.captured_queries)):
        response = client.get(owner_url(company, "events/"))
    rows = response.data["results"]
    assert len(rows) == 14
    for row in rows:
        event = Event.objects.get(pk=row["id"])
        assert row["responses"] == queries.responses(event)
        assert row["my_response"] == queries.my_invite(owner, event).response
    assert {row["responses"]["going"] for row in rows} == {0, 3}


def test_calendar_queries_dont_grow_with_rows(
    company, owner, alisher, owner_api, django_assert_max_num_queries
):
    client = owner_api(owner)
    _events(company, [alisher], 2)
    query = {"from": TODAY.isoformat(), "to": (TODAY + timedelta(days=6)).isoformat()}
    with django_assert_max_num_queries(40) as few:
        client.get(owner_url(company), query)
    _events(company, [alisher], 12)
    with django_assert_max_num_queries(len(few.captured_queries)):
        response = client.get(owner_url(company), query)
    assert len(response.data["items"]) == 14


# Reminders "at the start" ---------------------------------------------------------------


def test_a_reminder_at_the_start_goes_out(company, owner, alisher):
    services.create_event(
        company,
        by=owner,
        title="Stand-up",
        start=timezone.now() - timedelta(seconds=30),
        remind_before=0,
        attendee_ids=[alisher.pk],
    )

    assert services.send_due_reminders() == 1
    assert services.send_due_reminders() == 0
    [note] = Notification.objects.filter(kind=services.KIND_REMINDER)
    assert note.recipient == alisher and "Stand-up" in note.title


def test_a_reminder_at_the_start_doesnt_come_long_after(company, owner, alisher):
    services.create_event(
        company,
        by=owner,
        title="Long gone",
        start=timezone.now() - services.START_GRACE - timedelta(minutes=1),
        remind_before=0,
        attendee_ids=[alisher.pk],
    )

    assert services.send_due_reminders() == 0


# Briefings ------------------------------------------------------------------------------


def test_briefings_leave_out_invited_only_events(company, owner, alisher):
    now = timezone.now()
    services.create_event(
        company, by=owner, title="Team lunch", start=at(TODAY, 13), attendee_ids=[alisher.pk]
    )
    services.create_event(
        company,
        by=owner,
        title="Salary talk with Alisher",
        start=at(TODAY, 15),
        visibility="attendees",
        attendee_ids=[alisher.pk],
    )

    section = providers.today_section(company, TODAY, now, None)

    assert [item["title"] for item in section["items"]] == ["Team lunch"]
    assert section["items"][0]["attendees"] == 1


# Branch planners editing wider events -----------------------------------------------------


def test_a_branch_planner_keeps_people_someone_else_invited(
    company, owner, planner, alisher, nigora
):
    event = services.create_event(
        company,
        by=owner,
        title="All hands",
        start=at(TOMORROW, 9),
        attendee_ids=[alisher.pk, nigora.pk, planner.pk],
    )

    services.update_event(
        event, by=planner, title="All hands (moved)", attendee_ids=[alisher.pk, nigora.pk]
    )

    assert set(event.invites.values_list("membership_id", flat=True)) == {alisher.pk, nigora.pk}
    with pytest.raises(Exception, match="can see"):
        services.update_event(event, by=planner, attendee_ids=[alisher.pk, nigora.pk, owner.pk])


# "Mine" -----------------------------------------------------------------------------------


def test_my_upcoming_events_keep_those_someone_else_declined(company, owner, alisher, nigora):
    event = services.create_event(
        company,
        by=owner,
        title="Training",
        start=timezone.now() + timedelta(hours=3),
        attendee_ids=[alisher.pk, nigora.pk],
    )
    services.respond(event, by=alisher, response="going")
    services.respond(event, by=nigora, response="declined")

    assert [o.event.pk for o in queries.upcoming(alisher, mine=True)] == [event.pk]
    assert queries.upcoming(nigora, mine=True) == []
