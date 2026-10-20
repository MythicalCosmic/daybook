from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.announcements import services
from apps.announcements.callbacks import AnnounceAction, AnnounceCallback
from apps.announcements.models import Announcement, Receipt
from apps.announcements.notifications import follow_up
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.members.tests.factories import PositionFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager", first_name="Mona")


def to(sent_messages, member) -> list[dict]:
    return [m for m in sent_messages if m["chat_id"] == member.user.telegram_id]


def publish(author, text="Shop closes at 18:00 today.", positions=(), *, capture):
    with capture(execute=True):
        return services.publish(author, text, [position.pk for position in positions])


def test_everyone_registered_gets_it_with_a_read_button(
    company, member, manager, sent_messages, django_capture_on_commit_callbacks
):
    ali = member.registered(company, first_name="Ali")
    vali = member.registered(company, first_name="Vali")
    member(company, status=Membership.Status.PENDING)  # not part of the team yet

    announcement = publish(manager, capture=django_capture_on_commit_callbacks)

    assert set(announcement.receipts.values_list("membership", flat=True)) == {ali.pk, vali.pk}
    [copy] = to(sent_messages, ali)
    assert "Announcement" in copy["text"] and "Mona" in copy["text"]
    assert "Shop closes at 18:00 today." in copy["text"]
    [[button]] = copy["reply_markup"]["inline_keyboard"]
    assert AnnounceCallback.unpack(button["callback_data"]) == AnnounceCallback(
        action=AnnounceAction.READ, announcement_id=announcement.pk
    )
    assert not to(sent_messages, manager)  # not to the author
    entry = AuditLog.objects.get()
    assert (entry.action, entry.details["recipients"]) == (AuditLog.Action.ANNOUNCEMENT_SENT, 2)


def test_an_announcement_can_go_to_some_positions_only(
    company, member, manager, sent_messages, django_capture_on_commit_callbacks
):
    cashier, cook = PositionFactory(company=company), PositionFactory(company=company)
    cashiers = [member.registered(company, position=cashier) for _ in range(2)]
    member.registered(company, position=cook)

    announcement = publish(manager, positions=[cashier], capture=django_capture_on_commit_callbacks)

    assert list(announcement.positions.all()) == [cashier]
    assert {m["chat_id"] for m in sent_messages} == {person.user.telegram_id for person in cashiers}


def test_only_announcers_publish_and_the_text_must_fit(company, member, manager):
    with pytest.raises(PermissionDenied):
        services.publish(member.registered(company), "Hello")
    with pytest.raises(DomainError):
        services.publish(manager, "   ")
    with pytest.raises(DomainError):
        services.publish(manager, "x" * (services.MAX_LENGTH + 1))
    assert not Announcement.objects.exists()


def test_reading_is_recorded_once(company, member, manager, django_capture_on_commit_callbacks):
    ali = member.registered(company)
    announcement = publish(manager, capture=django_capture_on_commit_callbacks)

    first = services.mark_read(announcement.pk, ali.user)
    read_at = first.read_at
    again = services.mark_read(announcement.pk, ali.user)

    assert read_at is not None
    assert again.read_at == read_at
    assert services.mark_read(announcement.pk, manager.user) is None  # the author got no copy


def test_who_has_read_it(company, member, manager, django_capture_on_commit_callbacks):
    ali = member.registered(company, first_name="Ali")
    vali = member.registered(company, first_name="Vali")
    announcement = publish(manager, capture=django_capture_on_commit_callbacks)
    services.mark_read(announcement.pk, ali.user)

    assert services.readers(announcement.pk, manager.user) == ([ali], [vali])
    owner = member.registered(company, "Owner")
    assert services.readers(announcement.pk, owner.user) == ([ali], [vali])
    with pytest.raises(PermissionDenied):
        services.readers(announcement.pk, vali.user)


def test_people_who_havent_read_it_are_reminded_then_the_author_hears(
    company, member, manager, sent_messages, django_capture_on_commit_callbacks
):
    ali = member.registered(company, first_name="Ali")
    vali = member.registered(company, first_name="Vali")
    announcement = publish(manager, capture=django_capture_on_commit_callbacks)
    services.mark_read(announcement.pk, ali.user)
    sent_messages.clear()
    sent_at = announcement.created_at

    follow_up(sent_at + timedelta(hours=2))
    assert sent_messages == []  # too soon

    follow_up(sent_at + timedelta(hours=3, minutes=5))
    follow_up(sent_at + timedelta(hours=4))
    [reminder] = sent_messages
    assert reminder["chat_id"] == vali.user.telegram_id
    assert "Reminder" in reminder["text"]

    sent_messages.clear()
    follow_up(sent_at + timedelta(days=1, minutes=5))
    follow_up(sent_at + timedelta(days=1, hours=1))
    [summary] = sent_messages
    assert summary["chat_id"] == manager.user.telegram_id
    assert "1 of 2" in summary["text"]
    assert "Vali" in summary["text"]


def test_suspended_people_get_no_reminder_and_a_suspended_author_no_summary(
    company, member, manager, sent_messages, django_capture_on_commit_callbacks
):
    vali = member.registered(company, first_name="Vali")
    announcement = publish(manager, capture=django_capture_on_commit_callbacks)
    Membership.objects.filter(pk__in=[vali.pk, manager.pk]).update(
        status=Membership.Status.SUSPENDED
    )
    sent_messages.clear()
    sent_at = announcement.created_at

    follow_up(sent_at + timedelta(hours=3, minutes=5))
    follow_up(sent_at + timedelta(days=1, minutes=5))

    assert sent_messages == []


def test_old_or_fully_read_announcements_are_left_alone(
    company, member, manager, sent_messages, django_capture_on_commit_callbacks
):
    ali = member.registered(company)
    announcement = publish(manager, capture=django_capture_on_commit_callbacks)
    sent_messages.clear()
    Announcement.objects.filter(pk=announcement.pk).update(
        created_at=timezone.now() - timedelta(days=4)
    )

    follow_up(timezone.now())
    assert sent_messages == []

    Announcement.objects.filter(pk=announcement.pk).update(
        created_at=timezone.now() - timedelta(days=1, hours=1)
    )
    Receipt.objects.filter(membership=ali).update(
        read_at=timezone.now(), reminded_at=timezone.now()
    )
    follow_up(timezone.now())
    assert sent_messages == []  # everyone has read it: no summary needed
