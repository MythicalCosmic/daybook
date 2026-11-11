"""The organization's admin hears every scan in Telegram, with the photo, their own included
(docs/DAVOMAT.md §1.5): they link their own Telegram with a one-time link (which counts as
pressing Start in the bot), and Face ID's "who came" then goes to them through the one bot,
whoever scanned. End to end: the terminal's real payload, the inbox, the Telegram copy."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from apps.davomat import services
from apps.davomat.models import DavomatSettings
from apps.faceid import hikvision
from apps.faceid import services as face
from apps.faceid.models import FaceDevice, FaceEvent, FaceIdSettings
from apps.faceid.tests import samples as hik
from apps.inbox.models import Notification
from apps.notifications import telegram as bots
from apps.notifications.telegram import BotName

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 11, 12)
TOKEN = "7701234567:AAFakeTokenForTestsOnly-abcdefghijkl"
ADMIN_CHAT = 99_001
Action = FaceEvent.Action


def at(hour, minute=0) -> datetime:
    return datetime.combine(DAY, time(hour, minute), tzinfo=TZ)


@pytest.fixture
def freeze(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def bot(org):
    """The organization's bot, connected in the Telegram settings (getMe already answered)."""
    DavomatSettings.objects.filter(company=org.company).update(
        bot_token=TOKEN, bot_username="namuna_davomat_bot", bot_status="ok"
    )


@pytest.fixture
def terminal(org, freeze) -> FaceDevice:
    freeze(at(6))
    return FaceDevice.objects.create(company=org.company, branch=org.main, name="Kirish")


@pytest.fixture
def scan(terminal, freeze, django_capture_on_commit_callbacks):
    """`scan(hour, minute, number=, name=)`: the terminal posts a scan with its snapshot."""
    serials = iter(range(50585, 59999))

    def post(hour, minute=0, *, number, name):
        moment = at(hour, minute)
        wall = moment.replace(tzinfo=None).isoformat() + "+08:00"
        data = hik.k1t341amf(number=number, name=name, serial=next(serials), at=wall)
        content_type, body = hik.multipart(data, part="event_log", picture=hik.jpeg())
        freeze(moment)
        with django_capture_on_commit_callbacks(execute=True):
            stored = face.receive(terminal, hikvision.parse(content_type, body))
        return stored[0]

    return post


@pytest.fixture
def admin_linked(org, owner_api, bot, settings):
    """The admin links their own Telegram from the web app ("Link my Telegram" in
    the Telegram settings), and opens the link in the bot (`/start link_<code>`)."""
    settings.TELEGRAM_DRY_RUN = False
    made = owner_api(org.owner).post(org.url(f"users/{org.owner.pk}/telegram-link/"))
    assert made.status_code == 201, made.content
    services.claim_link(made.json()["code"], ADMIN_CHAT, "dilnoza", "Dilnoza")
    org.owner.user.refresh_from_db()
    return org.owner


def copies_to(sent_messages, chat_id: int) -> list[dict]:
    return [message for message in sent_messages if message["chat_id"] == chat_id]


def test_linking_counts_as_pressing_start(admin_linked):
    user = admin_linked.user
    assert user.telegram_id == ADMIN_CHAT
    assert user.owner_bot_started_at is not None and user.owner_bot_blocked_at is None


def test_the_admin_hears_their_own_scan_with_the_photo(org, admin_linked, scan, sent_messages):
    services.add_face_number(org.owner, by=org.owner, number="00000007")

    event = scan(8, 2, number="00000007", name="Dilnoza")

    assert event.membership_id == org.owner.pk and event.action == Action.CHECKED_IN
    notification = Notification.objects.get(kind="faceid.scan", recipient=org.owner)
    assert notification.actor_id == org.owner.pk  # their own scan, not skipped
    # Their own "You came in" (attendance's), and "who came" with the snapshot (Face ID's).
    own, copy = copies_to(sent_messages, ADMIN_CHAT)
    assert own["text"] == "You came in: 08:02, Main."
    assert copy["bot"] == BotName.OWNER
    assert copy["photo"] and copy["photo_storage"] == "private"
    assert "Dilnoza Karimova · 08:02 · Kirish" in copy["text"]
    # In Davomat both bot names are the organization's one bot.
    assert bots._token(BotName.OWNER) == bots._token(BotName.EMPLOYEE) == TOKEN


def test_the_admin_hears_an_employee_arrive(org, admin_linked, scan, sent_messages):
    jasur = org.employee("Jasur", "Karimov", face_numbers=["00000002"])

    event = scan(8, 5, number="00000002", name="Jasur")

    assert event.membership_id == jasur.pk
    assert Notification.objects.filter(kind="faceid.scan", recipient=org.owner).count() == 1
    [copy] = copies_to(sent_messages, ADMIN_CHAT)
    assert "Jasur" in copy["text"] and copy["photo"]


def test_an_unknown_number_made_an_employee_reaches_the_admin_too(
    org, admin_linked, scan, sent_messages
):
    # auto_create_employees (on): the terminal's name becomes the employee.
    scan(8, 10, number="00000031", name="Gulirano")

    [copy] = copies_to(sent_messages, ADMIN_CHAT)
    assert "Gulirano" in copy["text"]


def test_every_web_user_who_sees_attendance_hears_it_admins_first(
    org, admin_linked, scan, sent_messages
):
    viewer = org.user("viewer", "madina")
    viewer.user.telegram_id = 99_002
    viewer.user.save(update_fields=["telegram_id"])
    elsewhere = org.user("manager", "bobur", branches=[org.second])
    elsewhere.user.telegram_id = 99_003
    elsewhere.user.save(update_fields=["telegram_id"])
    org.employee("Jasur", face_numbers=["00000002"])

    scan(8, 5, number="00000002", name="Jasur")

    chats = [message["chat_id"] for message in sent_messages]
    assert chats[:2] == [ADMIN_CHAT, 99_002]  # the admin first; the viewer too
    assert 99_003 not in chats  # a manager of another location doesn't see this one


def test_a_separate_face_id_bot_never_takes_the_messages_in_davomat(
    org, admin_linked, scan, sent_messages, monkeypatch
):
    """A token pasted on Face ID's own settings page (Daybook's Face ID bot) must not divert
    the messages away from the bot the admin linked to."""
    FaceIdSettings.objects.update_or_create(
        company=org.company,
        defaults={"bot_token": "1:OTHER", "bot_username": "other_bot", "bot_status": "ok"},
    )
    diverted = []
    monkeypatch.setattr(bots, "send_with_token", lambda *args, **kwargs: diverted.append(args))
    org.employee("Jasur", face_numbers=["00000002"])

    scan(8, 5, number="00000002", name="Jasur")

    assert diverted == []
    assert copies_to(sent_messages, ADMIN_CHAT)
