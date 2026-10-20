"""Announcements: audience by positions and branches, scheduling, pins, expiry, reminders and
the Telegram HTML the composer is turned into."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.announcements import services, telegram_html
from apps.announcements.models import Announcement, Receipt
from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, PositionFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    chilonzor = company.branches.first()
    yunusobod = BranchFactory(company=company, name="Yunusobod")
    cashier = PositionFactory(company=company, name="Cashier")
    cook = PositionFactory(company=company, name="Cook")

    def person(name, branch, position):
        p = member.registered(company, first_name=name, position=position, home_branch=branch)
        p.branches.set([branch])
        return p

    return {
        "owner": member.registered(company, "Owner"),
        "a": person("A", chilonzor, cashier),
        "b": person("B", chilonzor, cook),
        "c": person("C", yunusobod, cashier),
        "chilonzor": chilonzor,
        "yunusobod": yunusobod,
        "cashier": cashier,
    }


def recipients(announcement) -> set[str]:
    return set(announcement.receipts.values_list("membership__first_name", flat=True))


def test_announcements_reach_positions_and_branches(shop):
    only = services.publish(
        shop["owner"],
        "Count the float twice",
        [shop["cashier"].pk],
        branch_ids=[shop["chilonzor"].pk],
    )
    by_position = services.publish(shop["owner"], "Cashiers!", [shop["cashier"].pk])
    everyone = services.publish(shop["owner"], "Hello team")

    assert recipients(only) == {"A"}
    assert recipients(by_position) == {"A", "C"}
    assert recipients(everyone) == {"A", "B", "C"}


def test_a_scheduled_announcement_is_sent_once_at_its_time(
    shop, sent_messages, django_capture_on_commit_callbacks
):
    now = timezone.now()
    announcement = services.publish(
        shop["owner"], "Inventory on Saturday", scheduled_for=now + timedelta(hours=1)
    )
    assert announcement.status == Announcement.Status.SCHEDULED
    assert not Receipt.objects.filter(announcement=announcement).exists()

    assert services.send_due(now) == 0
    with django_capture_on_commit_callbacks(execute=True):
        assert services.send_due(now + timedelta(hours=1, seconds=5)) == 1
    assert services.send_due(now + timedelta(hours=2)) == 0

    announcement.refresh_from_db()
    assert announcement.status == Announcement.Status.SENT
    assert recipients(announcement) == {"A", "B", "C"}
    assert len([m for m in sent_messages if "Inventory on Saturday" in m["text"]]) == 3


def test_a_scheduled_announcement_can_be_changed_or_cancelled(shop):
    now = timezone.now()
    announcement = services.publish(shop["owner"], "Draft", scheduled_for=now + timedelta(days=1))

    services.update_scheduled(
        announcement, by=shop["owner"], text="<b>Final</b>", branch_ids=[shop["yunusobod"].pk]
    )
    announcement.refresh_from_db()
    assert announcement.text == "<b>Final</b>"
    services.cancel_scheduled(announcement, by=shop["owner"])
    assert services.send_due(now + timedelta(days=2)) == 0
    with pytest.raises(DomainError):
        services.cancel_scheduled(announcement, by=shop["owner"])


def test_schedule_and_pin_times_are_checked(shop):
    now = timezone.now()
    with pytest.raises(DomainError):
        services.publish(shop["owner"], "Late", scheduled_for=now - timedelta(minutes=5))
    with pytest.raises(DomainError):
        services.publish(
            shop["owner"],
            "x",
            pinned_until=now + timedelta(days=3),
            expires_at=now + timedelta(days=1),
        )
    with pytest.raises(DomainError):
        services.publish(shop["owner"], "x", expires_at=now - timedelta(hours=1))


def test_remind_unread_reaches_only_unread_people(
    shop, sent_messages, django_capture_on_commit_callbacks
):
    announcement = services.publish(shop["owner"], "Please read")
    services.mark_read(announcement.pk, shop["a"].user)
    sent_messages.clear()

    with django_capture_on_commit_callbacks(execute=True):
        count = services.remind_unread(announcement, by=shop["owner"])

    assert count == 2
    chats = {m["chat_id"] for m in sent_messages}
    assert chats == {shop["b"].user.telegram_id, shop["c"].user.telegram_id}
    assert all("Reminder" in m["text"] for m in sent_messages)


def test_a_branch_manager_announces_only_to_their_branches(company, member, shop):
    role = AccessRoleFactory(company=company, permissions=[Perm.ANNOUNCE])
    lead = member.registered(company, role.name, home_branch=shop["chilonzor"])
    lead.branches.set([shop["chilonzor"]])

    announcement = services.publish(lead, "Chilonzor only")
    assert recipients(announcement) == {"A", "B"}
    with pytest.raises(PermissionDenied):
        services.publish(lead, "Everywhere", branch_ids=[shop["yunusobod"].pk])


def test_the_follow_up_counts_from_when_it_went_out(shop, sent_messages):
    from apps.announcements.notifications import follow_up

    now = timezone.now()
    announcement = services.publish(
        shop["owner"], "Scheduled", scheduled_for=now + timedelta(minutes=2)
    )
    Announcement.objects.filter(pk=announcement.pk).update(created_at=now - timedelta(days=2))
    services.send_due(now + timedelta(minutes=3))
    sent_messages.clear()

    follow_up(now + timedelta(minutes=10))  # written days ago, sent minutes ago: no reminder yet

    assert sent_messages == []


def test_nobody_is_reminded_about_an_expired_announcement(
    shop, sent_messages, django_capture_on_commit_callbacks
):
    from apps.announcements.notifications import follow_up, remind

    now = timezone.now()
    flash = services.publish(shop["owner"], "Today only", expires_at=now + timedelta(hours=1))
    Announcement.objects.filter(pk=flash.pk).update(sent_at=now - timedelta(hours=4))
    lasting = services.publish(shop["owner"], "For the week")
    Announcement.objects.filter(pk=lasting.pk).update(sent_at=now - timedelta(hours=4))
    sent_messages.clear()

    follow_up(now + timedelta(hours=2))  # the first expired an hour ago

    reminded = {m["text"] for m in sent_messages}
    assert reminded and all("For the week" in text for text in reminded)
    # "Remind unread now" queued before it expired doesn't go out after.
    sent_messages.clear()
    Announcement.objects.filter(pk=flash.pk).update(expires_at=now - timedelta(minutes=1))
    remind(flash.pk, list(flash.receipts.values_list("pk", flat=True)))
    assert sent_messages == []


@pytest.mark.parametrize(
    ("html", "telegram"),
    [
        ("<p>Hi <strong>all</strong></p><p></p><p>Bye</p>", "Hi <b>all</b>\n\nBye"),
        ('<p><a href="javascript:alert(1)">x</a></p>', "x"),
        (
            '<p><a href="https://t.me/a?b=1&amp;c=2">ok</a></p>',
            '<a href="https://t.me/a?b=1&amp;c=2">ok</a>',
        ),
        (
            '<p><span class="tg-spoiler">s</span> <code>1 &lt; 2</code></p>',
            "<tg-spoiler>s</tg-spoiler> <code>1 &lt; 2</code>",
        ),
        ("<img src=x onerror=alert(1)><script>alert(1)</script><p>after</p>", "after"),
        ("<p><em>a <strong>b</em> c</strong></p>", "<i>a <b>b</b></i><b> c</b>"),
    ],
)
def test_only_telegram_html_is_kept(html, telegram):
    assert telegram_html.from_editor(html) == telegram


def test_publishing_sanitizes_the_bots_html_too(shop):
    announcement = services.publish(
        shop["owner"], "<b>Bold</b> <img src=x onerror=1> <tg-spoiler>s</tg-spoiler>"
    )

    assert announcement.text == "<b>Bold</b>  <tg-spoiler>s</tg-spoiler>"
    with pytest.raises(DomainError):
        services.publish(shop["owner"], "<p>   </p>")


def test_a_scheduled_one_is_pinned_only_past_its_sending_time(shop):
    later = timezone.now() + timedelta(days=2)
    scheduled = services.publish(shop["owner"], "Inventory", scheduled_for=later)

    with pytest.raises(DomainError):
        services.pin(scheduled, by=shop["owner"], until=later - timedelta(hours=1))
    pinned = services.pin(scheduled, by=shop["owner"], until=later + timedelta(days=1))
    assert pinned.pinned_until == later + timedelta(days=1)
