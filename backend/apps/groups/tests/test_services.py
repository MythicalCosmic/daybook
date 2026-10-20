import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import DomainError
from apps.groups import services
from apps.groups.models import DEFAULT_EVENTS, GroupEvent, TelegramGroup
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members.models import Membership
from apps.members.tests.factories import PositionFactory

pytestmark = pytest.mark.django_db

CHAT = -1_001_234
NEW_CHAT = -1_009_999


def test_a_manager_connects_a_group_to_their_company(company, member):
    manager = member(company, "Manager")

    group = services.connect(CHAT, "Shop team", by=manager.user)

    group.refresh_from_db()
    assert group.company == company
    assert group.title == "Shop team"
    assert group.linked_by == manager
    assert group.is_active
    assert group.events == DEFAULT_EVENTS


def test_people_without_the_permission_cannot_connect(company, member):
    worker = member(company)

    with pytest.raises(PermissionDenied):
        services.connect(CHAT, "Shop team", by=worker.user)

    assert not TelegramGroup.objects.exists()


@pytest.mark.parametrize("status", [Membership.Status.PENDING, Membership.Status.BLOCKED])
def test_only_approved_managers_connect(company, member, status):
    manager = member(company, "Manager", status=status)

    with pytest.raises(PermissionDenied):
        services.connect(CHAT, "", by=manager.user)


def test_connecting_uses_the_company_someone_manages(company, other_company, member):
    manager = member(other_company, "Manager")
    member(company, user=manager.user)  # newer, so the bot's usual pick, but no say over groups

    group = services.connect(CHAT, "", by=manager.user)

    assert group.company == other_company


def test_a_group_linked_to_another_company_is_refused(company, other_company, member):
    TelegramGroupFactory(company=other_company, chat_id=CHAT)
    manager = member(company, "Manager")

    with pytest.raises(DomainError):
        services.connect(CHAT, "", by=manager.user)

    assert TelegramGroup.objects.get().company == other_company


def test_a_group_another_company_left_starts_fresh(company, other_company, member):
    TelegramGroupFactory(
        company=other_company, chat_id=CHAT, is_active=False, events=[GroupEvent.MORNING]
    )
    manager = member(company, "Manager")

    group = services.connect(CHAT, "New team", by=manager.user)

    assert group.company == company
    assert group.is_active
    assert group.events == DEFAULT_EVENTS


def test_reconnecting_keeps_the_chosen_events(company, member):
    TelegramGroupFactory(
        company=company, chat_id=CHAT, is_active=False, events=[GroupEvent.MORNING]
    )
    manager = member(company, "Manager")

    group = services.connect(CHAT, "", by=manager.user)

    assert group.is_active
    assert group.events == [GroupEvent.MORNING]


def test_a_manager_turns_events_on_and_off(company, member):
    manager = member(company, "Manager")
    group = TelegramGroupFactory(company=company, events=[GroupEvent.LATE])

    group = services.toggle_event(group, GroupEvent.MORNING, by=manager.user)
    assert group.events == [GroupEvent.LATE, GroupEvent.MORNING]

    group = services.toggle_event(group, GroupEvent.LATE, by=manager.user)
    group.refresh_from_db()
    assert group.events == [GroupEvent.MORNING]


def test_only_its_own_managers_change_a_group(company, other_company, member):
    group = TelegramGroupFactory(company=company)
    outsiders = [member(company).user, member(other_company, "Manager").user]

    for user in outsiders:
        with pytest.raises(PermissionDenied):
            services.toggle_event(group, GroupEvent.MORNING, by=user)
        with pytest.raises(PermissionDenied):
            services.disconnect(group, by=user)

    group.refresh_from_db()
    assert group.is_active
    assert GroupEvent.MORNING not in group.events


def test_disconnecting_stops_the_group(company, member):
    manager = member(company, "Manager")
    group = TelegramGroupFactory(company=company, chat_id=CHAT)

    services.disconnect(group, by=manager.user)

    assert services.find(CHAT) is None


def test_removing_the_bot_switches_the_group_off(company):
    TelegramGroupFactory(company=company, chat_id=CHAT)

    services.bot_removed(CHAT)

    assert services.find(CHAT) is None


def test_an_upgraded_group_keeps_its_settings(company):
    group = TelegramGroupFactory(company=company, chat_id=CHAT, events=[GroupEvent.MORNING])

    services.migrated(CHAT, NEW_CHAT)

    group.refresh_from_db()
    assert group.chat_id == NEW_CHAT
    assert group.events == [GroupEvent.MORNING]
    assert services.find(NEW_CHAT) == group


def test_an_upgrade_replaces_a_link_made_to_the_new_id(company):
    group = TelegramGroupFactory(company=company, chat_id=CHAT, events=[GroupEvent.MORNING])
    TelegramGroupFactory(company=company, chat_id=NEW_CHAT)  # linked again after the upgrade

    services.migrated(CHAT, NEW_CHAT)

    assert list(TelegramGroup.objects.all()) == [group]
    group.refresh_from_db()
    assert group.chat_id == NEW_CHAT


def test_moving_an_unknown_group_does_nothing(company):
    group = TelegramGroupFactory(company=company, chat_id=NEW_CHAT)

    services.migrated(CHAT, NEW_CHAT)

    assert list(TelegramGroup.objects.all()) == [group]


def test_a_manager_narrows_a_group_to_positions(company, member):
    manager = member(company, "Manager")
    group = TelegramGroupFactory(company=company)
    cashier = PositionFactory(company=company)

    services.toggle_position(group, cashier.pk, by=manager.user)
    assert list(group.positions.all()) == [cashier]

    services.toggle_position(group, cashier.pk, by=manager.user)
    assert not group.positions.exists()


def test_positions_come_from_the_groups_own_company(company, other_company, member):
    manager = member(company, "Manager")
    group = TelegramGroupFactory(company=company)

    with pytest.raises(DomainError):
        services.toggle_position(group, PositionFactory(company=other_company).pk, by=manager.user)
    with pytest.raises(PermissionDenied):
        services.toggle_position(
            group, PositionFactory(company=company).pk, by=member(company).user
        )

    assert not group.positions.exists()


def test_a_takeover_drops_the_old_companys_positions(company, other_company, member):
    group = TelegramGroupFactory(company=other_company, chat_id=CHAT, is_active=False)
    group.positions.add(PositionFactory(company=other_company))

    services.connect(CHAT, "", by=member(company, "Manager").user)

    assert not group.positions.exists()
