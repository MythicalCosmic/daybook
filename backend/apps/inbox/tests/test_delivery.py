"""Telegram copies: the right bot, the buttons, blocked bots, and edits after acting."""

import pytest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.inbox import delivery
from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from apps.inbox.services import NotificationAction, notify
from apps.notifications.telegram import BotName

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("handlers")]

APPROVE = NotificationAction("approve", _("Approve"), "primary")
REJECT = NotificationAction("reject", _("Reject"), "danger", needs_reason=True)


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


@pytest.fixture
def owner_bot_on(settings):
    settings.OWNER_BOT_TOKEN = "42:OWNER"


def send(recipients, kind="inbox.claim", **kwargs):
    kwargs.setdefault("title", "Claim from <Ali>")
    [item, *_rest] = notify(recipients, kind, **kwargs)
    delivery.deliver(
        item.pk, photo=kwargs.get("photo"), photo_storage=kwargs.get("photo_storage", "default")
    )
    item.refresh_from_db()
    return item


def test_owner_kinds_use_the_owner_bot_once_started(owner, telegram, owner_bot_on):
    owner.user.owner_bot_started_at = timezone.now()
    owner.user.save()

    item = send([owner])

    assert telegram.sent[0]["bot"] == BotName.OWNER
    assert (item.telegram_bot, item.telegram_chat_id) == ("owner", owner.user.telegram_id)
    assert item.telegram_message_id == telegram.sent[0]["message_id"]
    assert item.telegram_sent_at is not None


def test_without_the_owner_bot_the_employee_bot_delivers(owner, telegram):
    owner.user.owner_bot_started_at = timezone.now()
    owner.user.save()

    send([owner])  # OWNER_BOT_TOKEN is empty in tests

    assert telegram.sent[0]["bot"] == BotName.EMPLOYEE


def test_the_employee_bot_delivers_until_the_owner_bot_is_started(owner, telegram, owner_bot_on):
    send([owner])

    assert telegram.sent[0]["bot"] == BotName.EMPLOYEE


def test_employee_kinds_always_use_the_employee_bot(company, member, telegram, owner_bot_on):
    worker = member(company, user__owner_bot_started_at=timezone.now())

    [item] = notify([worker], "inbox.digest", title="Week")
    delivery.deliver(item.pk)

    assert telegram.sent[0]["bot"] == BotName.EMPLOYEE


def test_a_blocked_owner_bot_falls_back_to_the_employee_bot(owner, telegram, owner_bot_on):
    owner.user.owner_bot_started_at = timezone.now()
    owner.user.save()
    telegram.refuse.add(BotName.OWNER)

    item = send([owner])

    owner.user.refresh_from_db()
    assert owner.user.owner_bot_blocked_at is not None
    assert [message["bot"] for message in telegram.sent] == [BotName.EMPLOYEE]
    assert item.telegram_bot == "employee"


def test_a_blocked_employee_bot_is_recorded_and_cleared_later(owner, telegram):
    telegram.refuse.add(BotName.EMPLOYEE)
    item = send([owner])

    owner.user.refresh_from_db()
    assert owner.user.employee_bot_blocked_at is not None
    assert item.telegram_sent_at is None

    telegram.refuse.clear()
    send([owner], dedupe_key="second")
    owner.user.refresh_from_db()
    assert owner.user.employee_bot_blocked_at is None


def test_the_copy_is_escaped_and_carries_the_buttons(owner, telegram):
    item = send([owner], body="450 000 so'm & a receipt", actions=[APPROVE, REJECT])

    message = telegram.sent[0]
    assert message["text"] == "<b>Claim from &lt;Ali&gt;</b>\n450 000 so'm &amp; a receipt"
    [[button]] = message["markup"]["inline_keyboard"]  # the reason-needing one stays in the app
    assert button["text"] == "Approve"
    assert InboxAction.unpack(button["callback_data"]) == InboxAction(
        notification_id=item.pk, key="approve"
    )


def test_critical_copies_stand_out(owner, telegram):
    send([owner], severity="critical")

    assert telegram.sent[0]["text"].startswith("<b>")


def test_owner_copies_open_the_dashboard(owner, telegram, settings):
    settings.DASHBOARD_URL = "https://app.example.uz/dashboard/"

    send([owner], url="/c/1/finance/claims/7")

    [[button]] = telegram.sent[0]["markup"]["inline_keyboard"]
    assert button["web_app"]["url"] == "https://app.example.uz/dashboard/c/1/finance/claims/7"


def test_employee_copies_open_the_mini_app(company, member, telegram, settings):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example.uz/app/"
    worker = member(company)

    [item] = notify([worker], "inbox.digest", title="Payslip", app_screen="payslip:12")
    delivery.deliver(item.pk)

    [[button]] = telegram.sent[0]["markup"]["inline_keyboard"]
    assert button["web_app"]["url"] == "https://app.example.uz/app/?screen=payslip%3A12"
    assert button["text"] == "Open in app"  # as on the task messages


def test_no_open_button_without_an_https_address(owner, telegram, settings):
    settings.DASHBOARD_URL = "http://localhost:28174/dashboard/"

    send([owner], url="/c/1/x")

    assert telegram.sent[0]["markup"] is None


def test_a_private_photo_rides_along(owner, telegram):
    send([owner], photo="receipts/1/a.jpg", photo_storage="private")

    assert (telegram.sent[0]["photo"], telegram.sent[0]["photo_storage"]) == (
        "receipts/1/a.jpg",
        "private",
    )


def test_a_copy_goes_out_once(owner, telegram):
    item = send([owner])

    delivery.deliver(item.pk)

    assert len(telegram.sent) == 1


def test_nothing_is_sent_to_people_without_telegram(company, member, telegram):
    owner = member(company, "Owner", user__telegram_id=None)

    send([owner])

    assert telegram.sent == []


def test_a_copy_already_acted_on_is_not_sent(owner, telegram):
    [item] = notify([owner], "inbox.claim", title="Claim")
    Notification.objects.filter(pk=item.pk).update(acted_at=timezone.now())

    delivery.deliver(item.pk)

    assert telegram.sent == []


def test_the_task_delivers_through_celery(owner, telegram, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        notify([owner], "inbox.claim", title="Claim")

    assert len(telegram.sent) == 1


def test_someone_who_lost_access_since_hears_nothing(owner, telegram):
    [item] = notify([owner], "inbox.claim", title="Claim")
    owner.status = owner.Status.BLOCKED
    owner.save()

    delivery.deliver(item.pk)

    assert telegram.sent == []


def test_an_outcome_with_its_own_mark_gets_no_second_tick():
    from apps.inbox.bot_messages import outcome_line

    assert outcome_line("Approved", "Dilnoza") == "Approved · Dilnoza"
    assert outcome_line("Approved", "") == "Approved"
    # Tasks settle with marked outcomes; "✅ 🕒 New deadline set" read like a glitch.
    assert outcome_line("New deadline set", "Bekzod") == "New deadline set · Bekzod"
    assert outcome_line(_("More time given"), "Bekzod") == "More time given · Bekzod"
    assert outcome_line("Task cancelled", "") == "Task cancelled"
