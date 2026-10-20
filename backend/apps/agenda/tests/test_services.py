"""Calendar services: events, invitations and answers, changes, cancellations, reminders."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.agenda import queries, services
from apps.agenda.models import Event, EventAttendee
from apps.agenda.tests.factories import AttendeeFactory, EventFactory
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Asia/Tashkent")


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


TOMORROW = (timezone.now().astimezone(TZ) + timedelta(days=1)).date()


def test_create_event_invites_people_with_answer_buttons(company, owner, alisher, nigora):
    event = services.create_event(
        company,
        by=owner,
        title="  Weekly planning  ",
        start=at(TOMORROW, 9),
        end=at(TOMORROW, 9, 30),
        place="Office",
        attendee_ids=[owner.pk, alisher.pk, nigora.pk],
    )

    assert event.title == "Weekly planning"
    invites = {invite.membership_id: invite.response for invite in event.invites.all()}
    assert invites == {owner.pk: "going", alisher.pk: "pending", nigora.pk: "pending"}
    notes = Notification.objects.filter(kind="agenda.event_invite")
    assert set(notes.values_list("recipient", flat=True)) == {alisher.pk, nigora.pk}
    note = notes.first()
    assert "Weekly planning" in note.title and "Office" in note.body
    assert [action["key"] for action in note.actions] == ["going", "decline"]
    assert note.app_screen == f"agenda.event:{event.pk}"
    assert AuditLog.objects.filter(action="agenda.event_created", target_id=event.pk).exists()


def test_new_events_take_the_companys_default_reminder(company, owner):
    from apps.agenda.conf import get_settings

    row = get_settings(company)
    row.default_remind_before = 15
    row.save()

    event = services.create_event(company, by=owner, title="Call", start=at(TOMORROW, 11))
    quiet = services.create_event(
        company, by=owner, title="No reminder", start=at(TOMORROW, 12), remind_before=None
    )

    assert event.remind_before == 15 and quiet.remind_before is None


def test_only_calendar_managers_add_events(company, manager):
    with pytest.raises(PermissionDenied):
        services.create_event(company, by=manager, title="X", start=at(TOMORROW, 9))


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"title": " "}, "name"),
        ({"end": "before"}, "end after"),
        ({"end": "long"}, "two weeks"),
        ({"remind_before": 20000}, "week"),
        ({"repeat": "weekly", "repeat_until": "past"}, "repeating"),
    ],
)
def test_event_validation(company, owner, fields, message):
    values = {"title": "Meeting", "start": at(TOMORROW, 10)}
    values |= fields
    if values.get("end") == "before":
        values["end"] = at(TOMORROW, 9)
    if values.get("end") == "long":
        values["end"] = at(TOMORROW + timedelta(days=20), 9)
    if values.get("repeat_until") == "past":
        values["repeat_until"] = TOMORROW - timedelta(days=3)

    with pytest.raises(DomainError, match=message):
        services.create_event(company, by=owner, **values)


def test_all_day_events_keep_their_days(company, owner):
    event = services.create_event(
        company,
        by=owner,
        title="Inventory",
        start=TOMORROW,
        end=TOMORROW + timedelta(days=1),
        all_day=True,
    )

    [occurrence] = queries.occurrences(event, TOMORROW, TOMORROW + timedelta(days=3))
    assert (occurrence.first_day(), occurrence.last_day()) == (
        TOMORROW,
        TOMORROW + timedelta(days=1),
    )
    item = queries.calendar_item(occurrence)
    assert (item.start, item.end, item.all_day) == (TOMORROW, TOMORROW + timedelta(days=1), True)


def test_a_branch_planner_only_works_in_their_branches(
    company, planner, alisher, nigora, yunusobod
):
    with pytest.raises(DomainError, match="own branches"):
        services.create_event(
            company,
            by=planner,
            title="Yunusobod inventory",
            start=TOMORROW,
            all_day=True,
            branch=yunusobod.pk,
        )
    with pytest.raises(DomainError, match="can see"):
        services.create_event(
            company, by=planner, title="Meeting", start=at(TOMORROW, 9), attendee_ids=[nigora.pk]
        )
    ok = services.create_event(
        company, by=planner, title="Meeting", start=at(TOMORROW, 9), attendee_ids=[alisher.pk]
    )
    assert ok.invites.count() == 1


def test_moving_an_event_tells_the_attendees_and_resets_reminders(company, owner, alisher, nigora):
    event = services.create_event(
        company,
        by=owner,
        title="Training",
        start=at(TOMORROW, 15),
        end=at(TOMORROW, 17),
        attendee_ids=[alisher.pk, nigora.pk],
    )
    EventAttendee.objects.filter(event=event).update(reminded_for=event.start)
    services.respond(event, by=nigora, response="declined")

    services.update_event(event, by=owner, start=at(TOMORROW, 16), end=at(TOMORROW, 18))

    moved = Notification.objects.filter(kind="agenda.event_changed")
    assert list(moved.values_list("recipient", flat=True)) == [alisher.pk]  # not who declined
    assert not EventAttendee.objects.filter(event=event, reminded_for__isnull=False).exists()


def test_renaming_alone_doesnt_notify(company, owner, alisher):
    event = services.create_event(
        company, by=owner, title="Training", start=at(TOMORROW, 15), attendee_ids=[alisher.pk]
    )

    services.update_event(event, by=owner, title="Kassa training", description="Bring a pen")

    assert not Notification.objects.filter(kind="agenda.event_changed").exists()


def test_changing_attendees_invites_and_removes(company, owner, alisher, nigora):
    event = services.create_event(
        company, by=owner, title="Training", start=at(TOMORROW, 15), attendee_ids=[alisher.pk]
    )

    services.update_event(event, by=owner, attendee_ids=[nigora.pk])

    assert list(event.invites.values_list("membership_id", flat=True)) == [nigora.pk]
    assert Notification.objects.filter(kind="agenda.event_invite", recipient=nigora).exists()


def test_cancel_tells_who_was_coming(company, owner, alisher):
    event = services.create_event(
        company,
        by=owner,
        title="Cleaning day",
        start=TOMORROW,
        all_day=True,
        attendee_ids=[alisher.pk],
    )

    services.cancel_event(event, by=owner, reason="Moved to next week")

    event.refresh_from_db()
    assert event.cancelled_at is not None
    note = Notification.objects.get(kind="agenda.event_changed")
    assert "Moved to next week" in note.body and note.severity == "warning"
    with pytest.raises(DomainError):
        services.respond(event, by=alisher, response="going")


def test_respond_only_when_invited(company, owner, alisher, nigora):
    event = EventFactory(company=company)
    AttendeeFactory(event=event, membership=alisher)

    invite = services.respond(event, by=alisher, response="going")

    assert invite.response == "going" and invite.responded_at is not None
    with pytest.raises(PermissionDenied):
        services.respond(event, by=nigora, response="going")
    with pytest.raises(DomainError):
        services.respond(event, by=alisher, response="maybe")


# Visibility -----------------------------------------------------------------------------


def test_who_sees_which_event(company, owner, planner, alisher, nigora, chilonzor, yunusobod):
    open_all = EventFactory(company=company, title="All")
    at_chilonzor = EventFactory(company=company, title="Chilonzor", branch=chilonzor)
    at_yunusobod = EventFactory(company=company, title="Yunusobod", branch=yunusobod)
    private = EventFactory(company=company, title="Private", visibility="attendees")
    AttendeeFactory(event=private, membership=nigora)

    def titles(member):
        return set(queries.visible_events(member).values_list("title", flat=True))

    assert titles(owner) == {"All", "Chilonzor", "Yunusobod", "Private"}
    assert titles(alisher) == {open_all.title, at_chilonzor.title}
    assert titles(nigora) == {"All", "Yunusobod", "Private"}
    # A branch planner sees their branch and company-wide ones, private ones included.
    assert titles(planner) == {"All", "Chilonzor", "Private"}
    assert at_yunusobod.title not in titles(planner)


# Occurrences ----------------------------------------------------------------------------


def test_weekly_events_repeat_until_their_last_day(company, owner):
    monday = TOMORROW - timedelta(days=TOMORROW.weekday())
    event = services.create_event(
        company,
        by=owner,
        title="Planning",
        start=at(monday, 9),
        end=at(monday, 9, 30),
        repeat="weekly",
        repeat_until=monday + timedelta(days=14),
    )

    found = queries.occurrences(event, monday, monday + timedelta(days=60))

    assert [o.first_day() for o in found] == [monday + timedelta(days=7 * n) for n in range(3)]
    assert found[1].key == f"{event.pk}-{monday + timedelta(days=7):%Y%m%d}"


def test_monthly_events_clamp_to_the_last_day_of_short_months(company, owner):
    event = services.create_event(
        company, by=owner, title="Month end", start=at(date(2027, 1, 31), 18), repeat="monthly"
    )

    days = [o.first_day() for o in queries.occurrences(event, date(2027, 1, 1), date(2027, 4, 30))]

    assert days == [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)]


def test_a_far_window_of_a_repeating_event_is_quick_and_complete(company, owner):
    event = services.create_event(
        company, by=owner, title="Planning", start=at(date(2026, 1, 5), 9), repeat="weekly"
    )

    found = queries.occurrences(event, date(2030, 3, 1), date(2030, 3, 31))

    assert [o.first_day().day for o in found] == [4, 11, 18, 25]
    assert all(o.first_day().weekday() == 0 for o in found)


# Reminders ------------------------------------------------------------------------------


def test_reminders_go_once_per_person_and_occurrence(company, owner, alisher, nigora):
    start = timezone.now() + timedelta(minutes=50)
    event = services.create_event(
        company,
        by=owner,
        title="Briefing",
        start=start,
        remind_before=60,
        attendee_ids=[alisher.pk, nigora.pk],
    )
    services.respond(event, by=nigora, response="declined")

    assert services.send_due_reminders() == 1
    assert services.send_due_reminders() == 0
    [note] = Notification.objects.filter(kind="agenda.event_reminder")
    assert note.recipient == alisher and "Briefing" in note.title


def test_no_reminder_before_its_time_or_after_the_start(company, owner, alisher):
    services.create_event(
        company,
        by=owner,
        title="Later",
        start=timezone.now() + timedelta(hours=3),
        remind_before=60,
        attendee_ids=[alisher.pk],
    )
    services.create_event(
        company,
        by=owner,
        title="Started",
        start=timezone.now() - timedelta(minutes=5),
        remind_before=60,
        attendee_ids=[alisher.pk],
    )

    assert services.send_due_reminders() == 0


def test_each_week_of_a_repeating_event_gets_its_own_reminder(company, owner, alisher):
    first = timezone.now() + timedelta(minutes=30)
    event = services.create_event(
        company,
        by=owner,
        title="Planning",
        start=first,
        remind_before=60,
        repeat="weekly",
        attendee_ids=[alisher.pk],
    )

    assert services.send_due_reminders(now=timezone.now()) == 1
    next_week = timezone.now() + timedelta(days=7)
    assert services.send_due_reminders(now=next_week) == 1
    invite = EventAttendee.objects.get(event=event, membership=alisher)
    assert invite.reminded_for == first + timedelta(days=7)


def test_all_day_reminders_come_in_the_morning(company, owner, alisher):
    event = services.create_event(
        company,
        by=owner,
        title="Inventory",
        start=TOMORROW,
        all_day=True,
        remind_before=24 * 60,
        attendee_ids=[alisher.pk],
    )
    [occurrence] = queries.occurrences(event, TOMORROW, TOMORROW)

    assert queries.reminder_time(occurrence) == at(TOMORROW, 9) - timedelta(days=1)


def test_remind_now_and_cancelled_events(company, owner, alisher):
    event = services.create_event(
        company, by=owner, title="Training", start=at(TOMORROW, 15), attendee_ids=[alisher.pk]
    )

    assert services.remind_now(event, by=owner) == 1
    services.cancel_event(event, by=owner)
    with pytest.raises(DomainError):
        services.remind_now(event, by=owner)
    assert services.send_due_reminders(now=at(TOMORROW, 14, 30)) == 0


def test_cancelled_events_leave_the_calendar(company, owner):
    event = EventFactory(company=company, title="Gone")
    Event.objects.filter(pk=event.pk).update(cancelled_at=timezone.now())

    items = queries.calendar_items(
        company, TOMORROW - timedelta(days=1), TOMORROW + timedelta(days=1), owner
    )

    assert "Gone" not in {item.title for item in items}
