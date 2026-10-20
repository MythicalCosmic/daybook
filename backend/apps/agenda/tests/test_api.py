"""Calendar endpoints: the aggregated calendar, events, answers; owner and mini app."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.agenda.models import Event
from apps.agenda.tests.factories import AttendeeFactory, EventFactory
from apps.console import registry
from apps.console.registry import CalendarItem
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Asia/Tashkent")
TODAY = timezone.now().astimezone(TZ).date()
TOMORROW = TODAY + timedelta(days=1)


def owner_url(company, path="") -> str:
    return f"/api/v1/owner/companies/{company.pk}/calendar/{path}"


def app_url(company, path="") -> str:
    return f"/api/v1/companies/{company.pk}/calendar/{path}"


def at(day: date, hour: int) -> str:
    return datetime.combine(day, time(hour), tzinfo=TZ).isoformat()


@pytest.fixture
def sources(isolated_registries):
    """Two more modules' sources: holidays for everyone, payroll dates behind a permission."""

    def holidays(company, start, end, member):
        return [
            CalendarItem(
                "h1", "timeoff.holiday", "Mustaqillik kuni", TOMORROW, None, True, "danger", ""
            )
        ]

    def payroll(company, start, end, member):
        return [
            CalendarItem("p1", "payroll.payday", "Pay day", TOMORROW, None, True, "success", "")
        ]

    def broken(company, start, end, member):
        raise RuntimeError("down")

    registry.CALENDAR_SOURCES.add(
        registry.CalendarSource("timeoff.holidays", "timeoff", None, None, "Holidays", holidays)
    )
    registry.CALENDAR_SOURCES.add(
        registry.CalendarSource(
            "payroll.dates", "payroll", Perm.PAYROLL_VIEW, None, "Payroll", payroll
        )
    )
    registry.CALENDAR_SOURCES.add(
        registry.CalendarSource("hr.broken", "hr", None, None, "Broken", broken)
    )


# The aggregated calendar ----------------------------------------------------------------


def test_calendar_merges_every_source_the_caller_may_see(
    company, owner, manager, owner_api, sources
):
    EventFactory(company=company, title="Planning", start=timezone.now() + timedelta(days=1))
    params = {"from": TODAY.isoformat(), "to": (TODAY + timedelta(days=6)).isoformat()}

    as_owner = owner_api(owner).get(owner_url(company), params).data
    as_manager = owner_api(manager).get(owner_url(company), params).data

    assert {s["key"] for s in as_owner["sources"]} == {
        "agenda.events",
        "timeoff.holidays",
        "payroll.dates",
        "hr.broken",
    }
    assert {item["title"] for item in as_owner["items"]} == {
        "Planning",
        "Mustaqillik kuni",
        "Pay day",
    }
    # The manager can't see payroll; a failing source is simply left out.
    assert "payroll.dates" not in {s["key"] for s in as_manager["sources"]}
    assert "Pay day" not in {item["title"] for item in as_manager["items"]}
    holiday = next(item for item in as_owner["items"] if item["source"] == "timeoff.holidays")
    assert holiday == {
        "id": "timeoff.holidays:h1",
        "source": "timeoff.holidays",
        "kind": "timeoff.holiday",
        "title": "Mustaqillik kuni",
        "start": TOMORROW.isoformat(),
        "end": None,
        "all_day": True,
        "color": "danger",
        "url": "",
    }


def test_calendar_source_toggles(company, owner, owner_api, sources):
    EventFactory(company=company, title="Planning")

    data = owner_api(owner).get(owner_url(company), {"sources": "timeoff.holidays"}).data

    assert {item["source"] for item in data["items"]} == {"timeoff.holidays"}


def test_calendar_window_is_validated(company, owner, owner_api):
    client = owner_api(owner)

    assert client.get(owner_url(company), {"from": "2026-13-01"}).status_code == 400
    assert (
        client.get(owner_url(company), {"from": "2026-10-10", "to": "2026-10-01"}).status_code
        == 400
    )
    assert (
        client.get(owner_url(company), {"from": "2026-01-01", "to": "2026-06-01"}).status_code
        == 400
    )


def test_calendar_needs_dashboard_access_and_the_right_company(
    company, other_company, owner, alisher, owner_api, api_as
):
    assert owner_api(alisher).get(owner_url(company)).status_code == 403
    assert owner_api(owner).get(owner_url(other_company)).status_code == 404
    assert api_as(owner).get(owner_url(company)).status_code == 401


# Events ---------------------------------------------------------------------------------


def test_create_event_and_read_it_back(company, owner, alisher, owner_api):
    response = owner_api(owner).post(
        owner_url(company, "events/"),
        {
            "title": "Kassa training",
            "kind": "training",
            "start": at(TOMORROW, 15),
            "end": at(TOMORROW, 17),
            "place": "Chilonzor",
            "attendee_ids": [alisher.pk],
            "remind_before": 30,
        },
        format="json",
    )

    assert response.status_code == 201
    data = response.data
    assert data["title"] == "Kassa training" and data["color"] == "chart-6"
    assert data["start"].startswith(f"{TOMORROW.isoformat()}T15:00")
    assert data["responses"] == {"pending": 1, "going": 0, "declined": 0}
    assert data["attendees"][0]["member"]["id"] == alisher.pk
    assert data["can_edit"] is True


def test_all_day_event_takes_days(company, owner, owner_api):
    response = owner_api(owner).post(
        owner_url(company, "events/"),
        {
            "title": "Inventory",
            "start": TOMORROW.isoformat(),
            "end": (TOMORROW + timedelta(days=1)).isoformat(),
            "all_day": True,
        },
        format="json",
    )

    assert response.status_code == 201
    assert (response.data["start"], response.data["end"]) == (
        TOMORROW.isoformat(),
        (TOMORROW + timedelta(days=1)).isoformat(),
    )


def test_writing_events_needs_agenda_manage(company, manager, owner_api):
    event = EventFactory(company=company)
    client = owner_api(manager)

    assert (
        client.post(
            owner_url(company, "events/"), {"title": "x", "start": at(TOMORROW, 9)}, format="json"
        ).status_code
        == 403
    )
    assert (
        client.patch(
            owner_url(company, f"events/{event.pk}/"), {"title": "y"}, format="json"
        ).status_code
        == 403
    )
    assert client.post(owner_url(company, f"events/{event.pk}/cancel/")).status_code == 403
    assert client.get(owner_url(company, "people/")).status_code == 403
    assert client.get(owner_url(company, f"events/{event.pk}/")).status_code == 200


def test_update_cancel_and_remind(company, owner, alisher, owner_api):
    event = EventFactory(company=company, title="Planning")
    AttendeeFactory(event=event, membership=alisher)
    client = owner_api(owner)

    changed = client.patch(
        owner_url(company, f"events/{event.pk}/"), {"place": "Ofis"}, format="json"
    )
    assert changed.status_code == 200 and changed.data["place"] == "Ofis"
    reminded = client.post(owner_url(company, f"events/{event.pk}/remind/"))
    assert reminded.data == {"reminded": 1}
    cancelled = client.post(
        owner_url(company, f"events/{event.pk}/cancel/"), {"reason": "Moved"}, format="json"
    )
    assert cancelled.data["cancelled"] is True and cancelled.data["can_edit"] is False
    listed = client.get(owner_url(company, "events/"), {"when": "cancelled"}).data["results"]
    assert [row["id"] for row in listed] == [event.pk]


def test_event_list_filters(company, owner, owner_api):
    EventFactory(company=company, title="Future")
    EventFactory(
        company=company,
        title="Old",
        start=timezone.now() - timedelta(days=3),
        end=timezone.now() - timedelta(days=3, hours=-1),
    )
    EventFactory(
        company=company, title="Weekly", start=timezone.now() - timedelta(days=30), repeat="weekly"
    )

    upcoming = owner_api(owner).get(owner_url(company, "events/")).data["results"]
    past = owner_api(owner).get(owner_url(company, "events/"), {"when": "past"}).data["results"]

    assert {row["title"] for row in upcoming} == {"Future", "Weekly"}
    assert [row["title"] for row in past] == ["Old"]
    assert upcoming[0]["attendees"] == []  # compact list


def test_branch_scope_hides_other_branches_events_and_people(
    company, planner, nigora, alisher, yunusobod, owner_api
):
    hidden = EventFactory(company=company, title="Yunusobod only", branch=yunusobod)
    client = owner_api(planner)

    assert client.get(owner_url(company, f"events/{hidden.pk}/")).status_code == 404
    people = {row["id"] for row in client.get(owner_url(company, "people/")).data}
    assert alisher.pk in people and nigora.pk not in people
    titles = {
        item["title"]
        for item in client.get(owner_url(company), {"from": TODAY.isoformat()}).data["items"]
    }
    assert "Yunusobod only" not in titles


def test_respond_from_the_dashboard(company, owner, owner_api):
    event = EventFactory(company=company)
    AttendeeFactory(event=event, membership=owner)

    response = owner_api(owner).post(
        owner_url(company, f"events/{event.pk}/respond/"), {"response": "declined"}, format="json"
    )

    assert response.status_code == 200 and response.data["response"] == "declined"


def test_settings(company, owner, manager, owner_api):
    assert (
        owner_api(manager).get(owner_url(company, "settings/")).data["default_remind_before"] == 60
    )
    assert (
        owner_api(manager)
        .patch(owner_url(company, "settings/"), {"notify_invites": False}, format="json")
        .status_code
        == 403
    )
    changed = owner_api(owner).patch(
        owner_url(company, "settings/"), {"default_remind_before": 30}, format="json"
    )
    assert changed.data["default_remind_before"] == 30


# Mini app -------------------------------------------------------------------------------


def test_my_calendar_in_the_app(company, alisher, nigora, api_as, sources):
    mine = EventFactory(company=company, title="Training")
    AttendeeFactory(event=mine, membership=alisher)
    EventFactory(company=company, title="Company dinner")
    private = EventFactory(
        company=company, title="Interview", visibility=Event.Visibility.ATTENDEES
    )
    AttendeeFactory(event=private, membership=nigora)

    data = (
        api_as(alisher)
        .get(
            app_url(company),
            {"from": TODAY.isoformat(), "to": (TODAY + timedelta(days=3)).isoformat()},
        )
        .data
    )

    titles = {item["title"] for item in data["items"]}
    assert {"Training", "Company dinner", "Mustaqillik kuni"} <= titles
    assert "Interview" not in titles and "Pay day" not in titles
    assert data["mine"] == [f"agenda.events:{mine.pk}"]


def test_event_detail_and_answer_in_the_app(company, alisher, nigora, api_as):
    event = EventFactory(company=company, title="Training")
    AttendeeFactory(event=event, membership=alisher)
    private = EventFactory(company=company, visibility=Event.Visibility.ATTENDEES)

    detail = api_as(alisher).get(app_url(company, f"events/{event.pk}/")).data
    assert detail["my_response"] == "pending" and detail["can_edit"] is False

    answered = api_as(alisher).post(
        app_url(company, f"events/{event.pk}/respond/"), {"response": "going"}, format="json"
    )
    assert answered.status_code == 200
    assert (
        api_as(nigora)
        .post(app_url(company, f"events/{event.pk}/respond/"), {"response": "going"}, format="json")
        .status_code
        == 403
    )
    assert api_as(nigora).get(app_url(company, f"events/{private.pk}/")).status_code == 404
