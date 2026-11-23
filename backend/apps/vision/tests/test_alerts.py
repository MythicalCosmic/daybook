"""Alerts (docs/KOZ.md §5.8, §7): the lifecycle from the boxes' events, idempotency, the cooldown,
"I'll go", the bot texts and the edits of every copy, who hears (on shift, managers, nobody
twice), boxes going offline and alerts with no news."""

from datetime import timedelta

import pytest
from django.core.cache import cache

from apps.attendance.models import AttendanceRecord
from apps.vision import services
from apps.vision.models import Alert, AlertMessage, Camera, VisionSettings
from apps.vision.tests.conftest import DAY, buttons, local
from apps.vision.tests.helpers import DEVICE, event, jpeg, post_event

pytestmark = pytest.mark.django_db

START = "2026-10-21T13:31:05Z"  # 18:31:05 in Tashkent


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def evening(freeze):
    return freeze(local(DAY, 18, 32))


@pytest.fixture
def on_shift(people, chilonzor, yunusobod):
    """Ali is checked in at Chilonzor, Sara at Yunusobod."""
    for person, branch in ((people.ali, chilonzor), (people.sara, yunusobod)):
        AttendanceRecord.objects.create(
            company=person.company,
            membership=person,
            date=DAY,
            status=AttendanceRecord.Status.OPEN,
            check_in_at=local(DAY, 9, 0),
            branch=branch,
        )
    return people


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    """Call the device API and run what it left for after commit (Telegram)."""

    def call(function, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return function(*args, **kwargs)

    return call


def texts_for(outbox, person) -> list[str]:
    return [sent["text"] for sent in outbox.sent if sent["chat_id"] == person.user.telegram_id]


def edits_for(outbox, person) -> list[dict]:
    return [edit for edit in outbox.edits if edit["chat_id"] == person.user.telegram_id]


# The lifecycle -----------------------------------------------------------------------------


def test_a_queue_opens_announces_and_ends(device, cameras, on_shift, freeze, outbox, run):
    people = on_shift
    freeze(local(DAY, 18, 32))
    started = event(event_id="1b9e0000-0000-4000-8000-000000000001", at=START, started_at=START)
    response = run(post_event, device, started, jpeg(1280, 720))

    assert response.status_code == 200
    alert = Alert.objects.get()
    assert response.json() == {"alert_id": alert.pk, "state": "open"}
    assert (alert.kind, alert.state, alert.camera, alert.branch_id) == (
        "queue",
        "open",
        cameras.counter,
        cameras.counter.branch_id,
    )
    assert alert.started_at == local(DAY, 18, 31) + timedelta(seconds=5)
    assert (alert.queue, alert.wait_s, alert.staff, alert.peak_queue, alert.peak_wait_s) == (
        3,
        130,
        1,
        3,
        130,
    )
    assert alert.photo.name.startswith(f"vision/photos/{alert.company_id}/")
    assert alert.announced_at is not None

    # Ali (on shift) and everyone who sees Chilonzor's Ko‘z: one copy each.
    heard = {copy.member_id: copy.reason for copy in AlertMessage.objects.filter(alert=alert)}
    assert heard == {
        people.ali.pk: "on_shift",
        people.manager.pk: "manager",
        people.head.pk: "manager",
        people.reader.pk: "manager",
        people.owner.pk: "manager",
    }
    [ali] = [sent for sent in outbox.sent if sent["chat_id"] == people.ali.user.telegram_id]
    assert ali["text"] == (
        "<b>Queue · Kassa 1 (Chilonzor)</b>\n"
        "3 customers waiting, the longest 2 min 10 s.\n"
        "At the counter: 1 pharmacist"
    )
    assert buttons(ali["reply_markup"]) == ["I'll go"]
    assert (ali["photo"], ali["photo_storage"], ali["bot"]) == (
        alert.photo.name,
        "private",
        "employee",
    )

    freeze(local(DAY, 18, 33))
    later = event(
        incident_id=started["incident_id"],
        phase="update",
        at="2026-10-21T13:32:05Z",
        queue=4,
        wait_s=190,
        staff=1,
        peak_queue=4,
        peak_wait_s=190,
    )
    assert run(post_event, device, later).json() == {"alert_id": alert.pk, "state": "open"}
    freeze(local(DAY, 18, 35))
    ended = event(
        incident_id=started["incident_id"],
        phase="end",
        at="2026-10-21T13:34:45Z",
        queue=1,
        wait_s=20,
        staff=2,
        peak_queue=4,
        peak_wait_s=190,
    )
    assert run(post_event, device, ended).json() == {"alert_id": alert.pk, "state": "resolved"}

    alert.refresh_from_db()
    assert (alert.state, alert.ending, alert.peak_queue, alert.peak_wait_s) == (
        "resolved",
        "ended",
        4,
        190,
    )
    assert alert.duration_s == 220
    # Every copy now says how it ended, without the button.
    assert len(outbox.edits) == 5
    [edit] = edits_for(outbox, people.ali)
    assert edit["message_id"] == ali["message_id"]
    assert edit["text"] == (
        "<b>Queue · Kassa 1 (Chilonzor)</b>\nQueue over · lasted 3 min 40 s · at most 4 people"
    )
    assert buttons(edit["reply_markup"]) == []


def test_the_same_event_twice_changes_nothing(device, cameras, on_shift, evening, outbox, run):
    started = event(at=START, started_at=START)

    first = run(post_event, device, started).json()
    second = run(post_event, device, started).json()

    assert first == second
    assert Alert.objects.count() == 1
    assert len(outbox.sent) == 5


def test_an_update_or_end_of_an_unknown_incident_does_nothing(device, cameras, evening, outbox):
    for phase in ("update", "end"):
        response = post_event(device, event(phase=phase))
        assert response.json() == {"alert_id": None}
    assert not Alert.objects.exists()


def test_an_unknown_camera_is_refused(device, cameras, evening):
    response = post_event(device, event(key="nvr:9"))

    assert (response.status_code, response.json()["code"]) == (404, "unknown_camera")


def test_only_counter_cameras_with_the_zones_a_rule_needs_raise_alerts(
    device, cameras, evening, outbox
):
    floor = post_event(device, event(key="nvr:5"))
    Camera.objects.filter(pk=cameras.counter.pk).update(zones=cameras.counter.zones[:1])
    no_staff_zone = post_event(device, event(kind="unattended"))
    Camera.objects.filter(pk=cameras.counter.pk).update(enabled=False)
    switched_off = post_event(device, event())

    assert [r.json() for r in (floor, no_staff_zone, switched_off)] == [{"alert_id": None}] * 3
    assert not Alert.objects.exists()


def test_a_bad_event_is_refused(device, cameras, evening):
    response = post_event(device, event(kind="fire"))

    assert (response.status_code, response.json()["code"]) == (400, "invalid")


# Nobody at the counter --------------------------------------------------------------------


def test_nobody_at_the_counter_and_how_it_ends(device, cameras, on_shift, freeze, outbox, run):
    people = on_shift
    freeze(local(DAY, 18, 34))
    first = event(kind="unattended", queue=2, wait_s=100, staff=0, at=START, started_at=START)
    run(post_event, device, first)

    [text] = texts_for(outbox, people.ali)
    assert text == (
        "<b>Nobody at the counter · Kassa 1 (Chilonzor)</b>\n"
        "2 customers have been waiting 1 min 40 s."
    )
    run(
        post_event,
        device,
        event(
            incident_id=first["incident_id"],
            kind="unattended",
            phase="end",
            at="2026-10-21T13:33:05Z",
            queue=2,
            staff=1,
        ),
    )
    [edit] = edits_for(outbox, people.ali)
    assert edit["text"].endswith("\nA pharmacist came to the counter · lasted 2 min")

    left = event(kind="unattended", queue=1, wait_s=95, staff=0, at=START, started_at=START)
    VisionSettings.objects.filter(company=cameras.counter.company).update(cooldown_s=0)
    run(post_event, device, left)
    run(
        post_event,
        device,
        event(
            incident_id=left["incident_id"],
            kind="unattended",
            phase="end",
            at="2026-10-21T13:32:05Z",
            queue=0,
            staff=0,
        ),
    )
    assert edits_for(outbox, people.ali)[-1]["text"].endswith("\nThe customers left · lasted 1 min")


# The cooldown ------------------------------------------------------------------------------


def test_an_alert_opens_every_time_but_is_announced_once_per_cooldown(
    device, cameras, on_shift, freeze, outbox, run
):
    freeze(local(DAY, 18, 32))
    first = event(at=START, started_at=START)
    run(post_event, device, first)
    run(post_event, device, event(incident_id=first["incident_id"], phase="end"))
    freeze(local(DAY, 18, 33))  # one minute later: still inside the 2 minutes
    second = run(post_event, device, event(at="2026-10-21T13:33:00Z")).json()
    freeze(local(DAY, 18, 35))
    third = run(post_event, device, event(at="2026-10-21T13:35:00Z")).json()

    quiet = Alert.objects.get(pk=second["alert_id"])
    loud = Alert.objects.get(pk=third["alert_id"])
    assert quiet.state == "open" and quiet.announced_at is None
    assert not quiet.messages.exists()
    assert loud.announced_at is not None and loud.messages.count() == 5
    assert Alert.objects.count() == 3
    # The other kind on the same camera has its own cooldown.
    freeze(local(DAY, 18, 35))
    other = run(post_event, device, event(kind="unattended", staff=0)).json()
    assert Alert.objects.get(pk=other["alert_id"]).announced_at is not None


# I'll go ---------------------------------------------------------------------------------


def test_the_first_who_goes_is_shown_on_every_copy(device, cameras, on_shift, freeze, outbox, run):
    people = on_shift
    freeze(local(DAY, 18, 32))
    alert_id = run(post_event, device, event(at=START, started_at=START)).json()["alert_id"]
    freeze(local(DAY, 18, 42))

    answer = run(services.acknowledge_from_bot, alert_id, user=people.ali.user)

    assert answer.ok is True
    alert = Alert.objects.get(pk=alert_id)
    assert alert.acknowledged_by == people.ali
    assert len(outbox.edits) == 5
    for edit in outbox.edits:
        assert "\nAli is going · 18:42" in edit["text"]
        assert "I'll go" not in buttons(edit["reply_markup"])
    late = run(services.acknowledge_from_bot, alert_id, user=people.manager.user)
    assert (late.ok, late.message) == (False, "Ali is already going.")
    stranger = run(services.acknowledge_from_bot, alert_id, user=people.sara.user)
    assert (stranger.ok, stranger.message) == (False, "You don't have access to this.")
    assert len(outbox.edits) == 5

    # When it ends, the copies keep who went.
    incident = alert.incident_id
    run(post_event, device, event(incident_id=str(incident), phase="end", peak_queue=3))
    assert outbox.edits[-1]["text"].split("\n")[1] == "Ali is going · 18:42"
    over = run(services.acknowledge_from_bot, alert_id, user=people.ali.user)
    assert over.ok is False


# Who hears ---------------------------------------------------------------------------------


def test_nobody_hears_twice(device, cameras, on_shift, evening, outbox, run, chilonzor):
    people = on_shift
    AttendanceRecord.objects.create(
        company=people.manager.company,
        membership=people.manager,
        date=DAY,
        status=AttendanceRecord.Status.OPEN,
        check_in_at=local(DAY, 9, 0),
        branch=chilonzor,
    )

    run(post_event, device, event(at=START, started_at=START))

    assert len(texts_for(outbox, people.manager)) == 1
    copy = AlertMessage.objects.get(member=people.manager)
    assert copy.reason == "on_shift"
    assert len(outbox.sent) == 5


def test_the_settings_say_who_hears(device, cameras, on_shift, evening, outbox, run):
    people = on_shift
    company = cameras.counter.company
    VisionSettings.objects.filter(company=company).update(notify_managers=False)
    run(post_event, device, event(at=START, started_at=START))
    assert {sent["chat_id"] for sent in outbox.sent} == {people.ali.user.telegram_id}

    outbox.sent.clear()
    VisionSettings.objects.filter(company=company).update(
        notify_managers=True, notify_on_shift=False, cooldown_s=0
    )
    run(post_event, device, event(at=START, started_at=START))
    assert people.ali.user.telegram_id not in {sent["chat_id"] for sent in outbox.sent}
    assert len(outbox.sent) == 4


def test_without_attendance_only_the_managers_hear(device, cameras, on_shift, evening, outbox, run):
    company = cameras.counter.company
    company.features = ["sales", "vision"]
    company.save(update_fields=["features"])

    run(post_event, device, event(at=START, started_at=START))

    assert set(AlertMessage.objects.values_list("reason", flat=True)) == {"manager"}


def test_no_photo_when_the_settings_say_so(device, cameras, on_shift, evening, outbox, run):
    VisionSettings.objects.filter(company=cameras.counter.company).update(alert_photo=False)

    run(post_event, device, event(at=START, started_at=START), jpeg())

    alert = Alert.objects.get()
    assert not alert.photo
    assert all(sent["photo"] is None for sent in outbox.sent)


def test_managers_hear_through_the_owner_bot_once_they_started_it(
    device, cameras, on_shift, evening, outbox, run, settings
):
    from django.utils import timezone

    settings.OWNER_BOT_TOKEN = "123:owner"
    owner = on_shift.owner
    owner.user.owner_bot_started_at = timezone.now()
    owner.user.save(update_fields=["owner_bot_started_at"])

    run(post_event, device, event(at=START, started_at=START))

    bots = {sent["chat_id"]: sent["bot"] for sent in outbox.sent}
    assert bots[owner.user.telegram_id] == "owner"
    assert bots[on_shift.ali.user.telegram_id] == "employee"
    assert AlertMessage.objects.get(member=owner).bot == "owner"


def test_the_alert_speaks_the_readers_language(device, cameras, on_shift, evening, outbox, run):
    people = on_shift
    people.ali.user.language = "uz"
    people.ali.user.save(update_fields=["language"])
    people.manager.user.language = "ru"
    people.manager.user.save(update_fields=["language"])

    run(post_event, device, event(at=START, started_at=START))

    [uz] = texts_for(outbox, people.ali)
    assert uz == (
        "<b>Navbat · Kassa 1 (Chilonzor)</b>\n"
        "3 mijoz kutmoqda, eng uzog‘i 2 daq 10 s.\n"
        "Kassada: 1 farmatsevt"
    )
    [ru] = texts_for(outbox, people.manager)
    assert ru.startswith("<b>Очередь · Kassa 1 (Chilonzor)</b>\n3 покупателя ждут")


# Boxes going quiet, alerts with no news ----------------------------------------------------


def test_a_quiet_box_alerts_the_managers_and_its_return_too(
    device, box, cameras, on_shift, freeze, outbox, run
):
    people = on_shift
    freeze(local(DAY, 18, 0))
    device.post(f"{DEVICE}live/", {"cameras": []}, format="json")
    freeze(local(DAY, 18, 6))

    assert run(services.check_offline) == 1
    assert run(services.check_offline) == 0  # once

    alert = Alert.objects.get(kind="agent_offline")
    assert (alert.agent, alert.camera, alert.started_at) == (box, None, local(DAY, 18, 0))
    assert not Camera.objects.filter(agent=box, online=True).exists()
    reasons = set(AlertMessage.objects.filter(alert=alert).values_list("reason", flat=True))
    assert reasons == {"manager"}  # not the people on shift
    [text] = texts_for(outbox, people.manager)
    assert text == (
        "<b>Ko‘z box offline · Chilonzor (for 6 min)</b>\nBox: Asosiy qutisi\nLast report: 18:00"
    )

    freeze(local(DAY, 18, 13))
    cache.clear()  # more than a minute since the last write
    run(device.post, f"{DEVICE}live/", {"cameras": []}, format="json")

    alert.refresh_from_db()
    assert (alert.state, alert.ending) == ("resolved", "back")
    [edit] = edits_for(outbox, people.manager)
    assert edit["text"] == "<b>Ko‘z box back online · Chilonzor</b>\nOffline: 13 min"


def test_a_demo_box_never_alerts(box, people, freeze, run):
    freeze(local(DAY, 18, 0))
    box.last_seen_at = local(DAY, 17, 0)
    box.demo = True
    box.save()

    assert run(services.check_offline) == 0


def test_open_alerts_with_no_news_for_two_hours_close(
    device, cameras, on_shift, freeze, outbox, run
):
    people = on_shift
    freeze(local(DAY, 18, 32))
    alert_id = run(post_event, device, event(at=START, started_at=START)).json()["alert_id"]

    freeze(local(DAY, 20, 31))
    assert run(services.resolve_stale) == 0
    freeze(local(DAY, 20, 33))
    assert run(services.resolve_stale) == 1

    alert = Alert.objects.get(pk=alert_id)
    assert (alert.state, alert.ending, alert.resolved_at) == (
        "resolved",
        "stale",
        local(DAY, 18, 32),
    )
    [edit] = edits_for(outbox, people.ali)
    assert edit["text"].endswith("\nClosed: no news from the box for 2 hours")


def test_switching_koz_off_stops_the_announcements(device, cameras, on_shift, evening, outbox):
    alert = Alert.objects.create(
        company=cameras.counter.company,
        kind="queue",
        branch=cameras.counter.branch,
        agent=cameras.counter.agent,
        camera=cameras.counter,
        started_at=local(DAY, 18, 31),
        last_event_at=local(DAY, 18, 31),
    )
    company = alert.company
    company.features = ["sales", "attendance"]
    company.save(update_fields=["features"])

    from apps.vision import tasks

    assert tasks.announce_alert(alert.pk) == 0
    assert outbox.sent == []


def test_a_dry_run_sends_nothing_and_keeps_who_would_hear(
    device, cameras, on_shift, evening, run, settings, caplog
):
    """With TELEGRAM_DRY_RUN (local runs) the texts are only logged: every copy is still kept,
    without a message id, and nothing is edited later."""
    settings.TELEGRAM_DRY_RUN = True
    started = event(at=START, started_at=START)

    with caplog.at_level("INFO", logger="apps.notifications.telegram"):
        run(post_event, device, started)
        run(post_event, device, event(incident_id=started["incident_id"], phase="end"))

    copies = AlertMessage.objects.filter(alert__incident_id=started["incident_id"])
    assert copies.count() == 5
    assert not copies.filter(message_id__isnull=False).exists()
    assert "Queue · Kassa 1 (Chilonzor)" in caplog.text
