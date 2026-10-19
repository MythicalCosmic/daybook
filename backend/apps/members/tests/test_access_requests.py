from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.core.exceptions import DomainError
from apps.members import services
from apps.members.callbacks import JoinAction
from apps.members.models import Membership
from apps.members.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def test_first_request_waits_for_the_persons_details(company, django_capture_on_commit_callbacks):
    user = UserFactory()

    with django_capture_on_commit_callbacks() as callbacks:
        membership, requested = services.request_access(user, company)

    assert requested
    assert membership.status == Membership.Status.PENDING
    assert callbacks == []  # approvers are asked once the account is created


def test_creating_the_account_sends_the_request_to_approvers(
    company, django_capture_on_commit_callbacks
):
    user = UserFactory(phone="+998901234567")
    membership, _ = services.request_access(user, company)

    with django_capture_on_commit_callbacks() as callbacks:
        services.complete_onboarding(
            membership, first_name="Ali", last_name="Valiyev", position_id=None
        )

    membership.refresh_from_db()
    assert membership.status == Membership.Status.PENDING
    assert membership.is_onboarded
    assert len(callbacks) == 1


def test_returning_person_with_details_goes_straight_to_approvers(
    company, member, django_capture_on_commit_callbacks
):
    former = member(company, status=Membership.Status.LEFT, onboarded_at=timezone.now())

    with django_capture_on_commit_callbacks() as callbacks:
        services.request_access(former.user, company)

    assert len(callbacks) == 1


def test_repeating_a_pending_request_does_not_ask_again(
    company, django_capture_on_commit_callbacks
):
    user = UserFactory()
    services.request_access(user, company)

    with django_capture_on_commit_callbacks() as callbacks:
        _, requested = services.request_access(user, company)

    assert not requested
    assert callbacks == []
    assert Membership.objects.filter(user=user).count() == 1


@pytest.mark.parametrize("status", [Membership.Status.APPROVED, Membership.Status.BLOCKED])
def test_existing_members_and_blocked_people_are_not_reopened(company, member, status):
    existing = member(company, status=status)

    membership, requested = services.request_access(existing.user, company)

    assert not requested
    assert membership.status == status


def test_rejected_person_waits_for_the_cooldown(company):
    rejected = MembershipFactory(
        company=company, status=Membership.Status.REJECTED, decided_at=timezone.now()
    )

    membership, requested = services.request_access(rejected.user, company)

    assert not requested
    assert membership.status == Membership.Status.REJECTED


def test_rejected_person_can_ask_again_after_the_cooldown(company):
    decided_at = timezone.now() - timedelta(hours=company.rejoin_cooldown_hours + 1)
    rejected = MembershipFactory(
        company=company, status=Membership.Status.REJECTED, decided_at=decided_at
    )

    membership, requested = services.request_access(rejected.user, company)

    assert requested
    assert membership.status == Membership.Status.PENDING
    assert membership.decided_at is None


def test_returning_member_loses_their_old_role(company, member):
    former_owner = member(company, "Owner", status=Membership.Status.LEFT)

    membership, requested = services.request_access(former_owner.user, company)

    assert requested
    assert membership.role is None


def test_current_membership_prefers_an_approved_one(company, other_company, member):
    approved = member(company)
    MembershipFactory(company=other_company, user=approved.user)  # newer, still pending

    assert services.current_membership(approved.user) == approved


def test_current_membership_ignores_inactive_companies(company, member):
    membership = member(company)
    company.is_active = False
    company.save()

    assert services.current_membership(membership.user) is None


def test_decide_approves_by_id(company, member, django_capture_on_commit_callbacks):
    manager = member(company, "Manager")
    request = MembershipFactory(company=company)

    with django_capture_on_commit_callbacks() as callbacks:
        services.decide(request.pk, JoinAction.APPROVE, by=manager.user)

    request.refresh_from_db()
    assert request.status == Membership.Status.APPROVED
    assert len(callbacks) == 1  # the requester hears about it


def test_decide_rejects_unknown_requests(company, member):
    manager = member(company, "Manager")

    with pytest.raises(DomainError):
        services.decide(10**9, JoinAction.APPROVE, by=manager.user)
