"""The membership signals other apps build on, the branch default on approval, and the
anti-escalation rules (docs/PLAN-OWNER.md §2.5, §3.2, §5)."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.members import services
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.members.signals import member_approved, member_left
from apps.members.tests.factories import MembershipFactory
from apps.timeoff.models import TimeOff
from apps.timeoff.signals import time_off_cancelled

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner")


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def heard():
    calls = []

    def approved(sender, membership, by, **kwargs):
        calls.append(("approved", membership.pk, by))

    def left(sender, membership, reason, by, details, terminated_on, **kwargs):
        calls.append(("left", membership.pk, reason, by, details, terminated_on))

    def cancelled(sender, time_off, by, **kwargs):
        calls.append(("time_off_cancelled", time_off.pk, time_off.status, by))

    member_approved.connect(approved, dispatch_uid="t-approved")
    member_left.connect(left, dispatch_uid="t-left")
    time_off_cancelled.connect(cancelled, dispatch_uid="t-cancelled")
    yield calls
    member_approved.disconnect(dispatch_uid="t-approved")
    member_left.disconnect(dispatch_uid="t-left")
    time_off_cancelled.disconnect(dispatch_uid="t-cancelled")


def today(company):
    return timezone.localdate(timezone=ZoneInfo(company.timezone))


def time_off(member, start, end, status=TimeOff.Status.APPROVED) -> TimeOff:
    return TimeOff.objects.create(
        company=member.company, membership=member, first_day=start, last_day=end, status=status
    )


def test_approval_is_announced_on_commit_with_the_acting_member(
    company, manager, heard, django_capture_on_commit_callbacks
):
    request = MembershipFactory(company=company)

    with django_capture_on_commit_callbacks() as callbacks:
        services.approve(request, by=manager.user)
    assert heard == []

    for callback in callbacks:
        callback()
    assert ("approved", request.pk, manager) in heard


def test_a_platform_admin_approves_as_nobody(company, heard, django_capture_on_commit_callbacks):
    from apps.accounts.tests.factories import UserFactory

    admin = UserFactory(is_superuser=True)
    request = MembershipFactory(company=company)

    with django_capture_on_commit_callbacks(execute=True):
        services.approve(request, by=admin)

    assert ("approved", request.pk, None) in heard


def test_approval_assigns_the_only_branch(company, manager):
    request = MembershipFactory(company=company)

    services.approve(request, by=manager.user)

    branch = company.branches.get()
    request.refresh_from_db()
    assert request.home_branch == branch
    assert list(request.branches.all()) == [branch]


def test_with_several_branches_the_approver_picks_later(company, manager):
    BranchFactory(company=company)
    request = MembershipFactory(company=company)

    services.approve(request, by=manager.user)

    request.refresh_from_db()
    assert request.home_branch is None
    assert not request.branches.exists()


def test_inactive_branches_do_not_count(company, manager):
    BranchFactory(company=company, is_active=False)
    request = MembershipFactory(company=company)

    services.approve(request, by=manager.user)

    request.refresh_from_db()
    assert request.home_branch == company.branches.get(is_active=True)


def test_offboarding_announces_the_wizard_answers_and_last_day(
    company, owner, worker, heard, django_capture_on_commit_callbacks
):
    last_day = today(company) - timedelta(days=2)
    answers = {"hr": {"reason": "resigned"}, "payroll": {"final_payslip": True}}

    with django_capture_on_commit_callbacks(execute=True):
        services.offboard(worker, by=owner.user, terminated_on=last_day, details=answers)

    assert ("left", worker.pk, "left", owner, answers, last_day) in heard
    entry = AuditLog.objects.get(action=AuditLog.Action.MEMBER_LEFT)
    assert entry.details == {"terminated_on": last_day.isoformat()}


def test_the_last_day_defaults_to_today_and_is_never_in_the_future(
    company, owner, worker, heard, django_capture_on_commit_callbacks
):
    with pytest.raises(DomainError, match="future"):
        services.offboard(worker, by=owner.user, terminated_on=today(company) + timedelta(days=1))

    with django_capture_on_commit_callbacks(execute=True):
        services.offboard(worker, by=owner.user)

    assert ("left", worker.pk, "left", owner, {}, today(company)) in heard


def test_blocking_a_member_announces_they_left(
    company, owner, worker, heard, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        services.block(worker, by=owner.user)

    assert ("left", worker.pk, "blocked", owner, {}, today(company)) in heard


def test_blocking_someone_who_never_joined_announces_nothing(
    company, owner, heard, django_capture_on_commit_callbacks
):
    stranger = MembershipFactory(company=company)  # a pending request

    with django_capture_on_commit_callbacks(execute=True):
        services.block(stranger, by=owner.user)

    assert not [call for call in heard if call[0] == "left"]


def test_time_off_is_cancelled_row_by_row_so_balances_hear_about_it(
    company, owner, worker, heard, django_capture_on_commit_callbacks
):
    day = today(company)
    coming = time_off(worker, day + timedelta(days=3), day + timedelta(days=4))
    asked = time_off(
        worker, day + timedelta(days=10), day + timedelta(days=11), TimeOff.Status.PENDING
    )
    past = time_off(worker, day - timedelta(days=10), day - timedelta(days=9))

    with django_capture_on_commit_callbacks(execute=True):
        services.offboard(worker, by=owner.user)

    cancelled = [call for call in heard if call[0] == "time_off_cancelled"]
    assert cancelled == [
        ("time_off_cancelled", coming.pk, TimeOff.Status.CANCELLED, owner),
        ("time_off_cancelled", asked.pk, TimeOff.Status.CANCELLED, owner),
    ]
    past.refresh_from_db()
    assert past.status == TimeOff.Status.APPROVED


def test_nothing_is_announced_when_the_change_rolls_back(
    company, owner, worker, heard, django_capture_on_commit_callbacks
):
    class Undo(Exception):
        pass

    with (
        django_capture_on_commit_callbacks(execute=True) as callbacks,
        pytest.raises(Undo),
        transaction.atomic(),
    ):
        services.offboard(worker, by=owner.user)
        raise Undo

    assert callbacks == []
    assert heard == []
    worker.refresh_from_db()
    assert worker.status == Membership.Status.APPROVED


@pytest.mark.parametrize("action", ["block", "offboard"])
def test_the_last_owner_stays(company, member, owner, action):
    from apps.accounts.tests.factories import UserFactory

    admin = UserFactory(is_superuser=True)  # even a platform admin can't remove them

    with pytest.raises(DomainError, match="only owner"):
        getattr(services, action)(owner, by=admin)

    second = member.registered(company, "Owner")
    getattr(services, action)(second, by=owner.user)  # another owner remains: fine


def test_only_owners_remove_an_owner(company, member, owner):
    second = member.registered(company, "Owner")
    remover = AccessRole.objects.create(
        company=company, name="People admin", permissions=[Perm.MEMBERS_MANAGE]
    )
    admin = member.registered(company, "People admin")
    assert admin.role == remover

    with pytest.raises(PermissionDenied):
        services.block(second, by=admin.user)
    with pytest.raises(PermissionDenied):
        services.offboard(second, by=admin.user)


def test_roles_are_given_only_within_what_the_giver_holds(company, manager, owner):
    roles = {role.name: role for role in AccessRole.objects.filter(company=company)}
    narrow = AccessRole.objects.create(
        company=company, name="Checker", permissions=[Perm.TASKS_CONFIRM]
    )
    wide = AccessRole.objects.create(
        company=company, name="Payroll", permissions=[Perm.TASKS_CONFIRM, Perm.PAYROLL_VIEW]
    )

    assert services.may_assign_role(manager, narrow)
    assert services.may_assign_role(manager, roles["Employee"])
    assert not services.may_assign_role(manager, wide)  # payroll.view isn't theirs to give
    assert not services.may_assign_role(manager, roles["Owner"])
    assert services.may_assign_role(owner, roles["Owner"])
    assert services.may_assign_role(owner, wide)
    assert services.may_grant(manager, [Perm.TASKS_ASSIGN])
    assert not services.may_grant(manager, [Perm.ROLES_MANAGE])
    assert services.may_grant(None, [Perm.ROLES_MANAGE])  # the system


def test_nobody_but_an_owner_takes_the_owner_role_away(company, member, manager, owner):
    second_owner = member.registered(company, "Owner")
    employee = AccessRole.objects.get(company=company, name="Employee")

    assert not services.may_assign_role(manager, employee, target=second_owner)
    assert services.may_assign_role(owner, employee, target=second_owner)


def test_only_owners_edit_their_own_role_or_the_owner_role(company, manager, owner):
    manager_role = manager.role
    owner_role = owner.role
    checker = AccessRole.objects.create(
        company=company, name="Checker", permissions=[Perm.TASKS_CONFIRM]
    )

    assert not services.may_edit_role(manager, manager_role)
    assert not services.may_edit_role(manager, owner_role)
    assert services.may_edit_role(manager, checker)
    assert services.may_edit_role(owner, owner_role)


def test_approving_with_a_preset_role_follows_the_same_rule(company, manager, owner):
    payroll = AccessRole.objects.create(
        company=company, name="Payroll", permissions=[Perm.PAYROLL_VIEW]
    )
    request = MembershipFactory(company=company, role=payroll)

    with pytest.raises(PermissionDenied):
        services.approve(request, by=manager.user)

    services.approve(request, by=owner.user)
    request.refresh_from_db()
    assert request.status == Membership.Status.APPROVED
    assert request.role == payroll


def test_default_roles_are_only_added_where_missing(company):
    services.create_default_roles(company)

    assert AccessRole.objects.filter(company=company).count() == 5
    assert AccessRole.objects.filter(company=company, is_default=True).count() == 1
