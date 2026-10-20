"""publish(author, text, position_ids=(), *, branch_ids=()): who gets an announcement."""

import pytest
from django.utils import timezone

from apps.announcements import services
from apps.announcements.models import Announcement
from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.members.tests.factories import PositionFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def recipients(announcement) -> set[int]:
    return set(announcement.receipts.values_list("membership_id", flat=True))


def in_branches(member, company, *branches, **kwargs):
    person = member.registered(company, **kwargs)
    person.branches.set(branches)
    return person


def test_branches_narrow_the_audience(company, member, manager):
    here = company.branches.get()
    there = BranchFactory(company=company)
    local = in_branches(member, company, here)
    both = in_branches(member, company, here, there)
    in_branches(member, company, there)
    in_branches(member, company)  # no branch at all

    announcement = services.publish(manager, "Stock count tonight.", branch_ids=[here.pk])

    assert recipients(announcement) == {local.pk, both.pk}
    assert list(announcement.branches.all()) == [here]


def test_positions_and_branches_both_apply(company, member, manager):
    here = company.branches.get()
    there = BranchFactory(company=company)
    cashier = PositionFactory(company=company)
    target = in_branches(member, company, here, position=cashier)
    in_branches(member, company, there, position=cashier)
    in_branches(member, company, here)

    announcement = services.publish(
        manager, "Cashiers: new till.", [cashier.pk], branch_ids=[here.pk]
    )

    assert recipients(announcement) == {target.pk}


def test_without_filters_everyone_registered_gets_it(company, member, manager):
    people = {member.registered(company).pk for _ in range(2)}
    member(company)  # approved but not registered yet

    announcement = services.publish(manager, "Hello team")

    assert recipients(announcement) == people


def test_another_companys_branch_is_ignored(company, other_company, member, manager):
    foreign = BranchFactory(company=other_company)
    person = member.registered(company)

    announcement = services.publish(manager, "Hello", branch_ids=[foreign.pk])

    assert not announcement.branches.exists()
    assert recipients(announcement) == {person.pk}


def test_a_published_announcement_is_sent_now(company, manager):
    before = timezone.now()

    announcement = services.publish(manager, "Hello")

    assert announcement.status == Announcement.Status.SENT
    assert announcement.sent_at >= before
    entry = AuditLog.objects.get(action=AuditLog.Action.ANNOUNCEMENT_SENT)
    assert entry.details["branches"] == []
