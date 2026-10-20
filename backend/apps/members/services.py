from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.models import Company
from apps.core.exceptions import DomainError
from apps.groups import tasks as group_jobs
from apps.members import tasks
from apps.members.callbacks import JoinAction
from apps.members.models import AccessRole, Membership, Position
from apps.members.permissions import Perm
from apps.tasks import services as task_services
from apps.timeoff.models import TimeOff

DEFAULT_ROLES = (
    {"name": "Owner", "is_owner": True},
    {
        "name": "Manager",
        "permissions": [
            Perm.MEMBERS_VIEW,
            Perm.MEMBERS_APPROVE,
            Perm.TASKS_VIEW_ALL,
            Perm.TASKS_ASSIGN,
            Perm.TASKS_TEMPLATES,
            Perm.TASKS_CONFIRM,
            Perm.GROUPS_MANAGE,
            Perm.REPORTS_VIEW,
            Perm.TIME_OFF_APPROVE,
            Perm.ANNOUNCE,
        ],
    },
    {"name": "Employee", "is_default": True},
)


def create_default_roles(company: Company) -> None:
    AccessRole.objects.bulk_create(
        AccessRole(
            company=company,
            name=role["name"],
            permissions=[str(perm) for perm in role.get("permissions", [])],
            is_owner=role.get("is_owner", False),
            is_default=role.get("is_default", False),
        )
        for role in DEFAULT_ROLES
    )


def get_membership(user: User, company: Company) -> Membership | None:
    return Membership.objects.for_company(company).select_related("role").filter(user=user).first()


def can(user: User, company: Company, perm: Perm) -> bool:
    if user.is_platform_admin:
        return True
    membership = get_membership(user, company)
    return membership is not None and membership.has_perm(perm)


def ensure_can(user: User, company: Company, perm: Perm) -> None:
    if not can(user, company, perm):
        raise PermissionDenied(_("You don't have permission to do this."))


def current_membership(user: User) -> Membership | None:
    """The membership the bot acts on: the latest approved one, else the latest of any status."""
    memberships = list(
        Membership.objects.filter(user=user, company__is_active=True)
        .select_related("company", "user", "role", "position")
        .order_by("-updated_at")
    )
    approved = [m for m in memberships if m.status == Membership.Status.APPROVED]
    return (approved or memberships or [None])[0]


def get_join_request(membership_id: int) -> Membership | None:
    return (
        Membership.objects.select_related("company", "user", "position", "decided_by")
        .filter(pk=membership_id)
        .first()
    )


@transaction.atomic
def request_access(user: User, company: Company) -> tuple[Membership, bool]:
    """Ask to join a company. Returns the membership and whether a new request was opened.

    Approvers hear about it once the person has filled in their details (complete_onboarding).
    """
    membership, created = (
        Membership.objects.select_for_update(of=("self",))
        .select_related("company")
        .get_or_create(company=company, user=user)
    )
    if created:
        return membership, True
    if membership.status not in (Membership.Status.REJECTED, Membership.Status.LEFT):
        return membership, False
    available_at = membership.rejoin_available_at
    if available_at is not None and timezone.now() < available_at:
        return membership, False

    membership.status = Membership.Status.PENDING
    # Someone coming back starts over: they get the default role again on approval.
    membership.role = None
    membership.decided_by = None
    membership.decided_at = None
    membership.save()
    if membership.is_onboarded:
        # Their details are on file, so the request goes straight back to the approvers.
        transaction.on_commit(partial(tasks.notify_join_request.delay, membership.pk))
    return membership, True


def decide(membership_id: int, action: JoinAction, *, by: User) -> Membership:
    membership = Membership.objects.filter(pk=membership_id).first()
    if membership is None:
        raise DomainError(_("This request no longer exists."))
    if action == JoinAction.APPROVE:
        return approve(membership, by=by)
    return reject(membership, by=by)


@transaction.atomic
def approve(membership: Membership, *, by: User) -> Membership:
    membership = _lock(membership)
    ensure_can(by, membership.company, Perm.MEMBERS_APPROVE)
    _ensure_status(membership, Membership.Status.PENDING)

    membership.status = Membership.Status.APPROVED
    if membership.role_id is None:
        membership.role = (
            AccessRole.objects.for_company(membership.company).filter(is_default=True).first()
        )
    _record_decision(membership, by)
    membership.save()
    _audit(AuditLog.Action.MEMBER_APPROVED, membership, by)
    transaction.on_commit(partial(tasks.notify_join_decision.delay, membership.pk))
    transaction.on_commit(partial(group_jobs.announce_member.delay, membership.pk))
    return membership


@transaction.atomic
def reject(membership: Membership, *, by: User) -> Membership:
    membership = _lock(membership)
    ensure_can(by, membership.company, Perm.MEMBERS_APPROVE)
    _ensure_status(membership, Membership.Status.PENDING)

    membership.status = Membership.Status.REJECTED
    _record_decision(membership, by)
    membership.save()
    _audit(AuditLog.Action.MEMBER_REJECTED, membership, by)
    transaction.on_commit(partial(tasks.notify_join_decision.delay, membership.pk))
    return membership


@transaction.atomic
def complete_onboarding(
    membership: Membership, *, first_name: str, last_name: str, position_id: int | None
) -> Membership:
    """Fill in name, phone and position: the join request (pending) or the profile (approved)."""
    membership = _lock(membership)
    if membership.status not in (Membership.Status.PENDING, Membership.Status.APPROVED):
        raise PermissionDenied(_("You don't have permission to do this."))
    if membership.is_onboarded:
        raise DomainError(_("You've already completed registration."))
    if not membership.user.phone:
        raise DomainError(_("Share your phone number in the bot first."))

    positions = Position.objects.for_company(membership.company).filter(is_active=True)
    if position_id is None:
        if positions.exists():
            raise DomainError(_("Choose your position."))
        position = None
    else:
        position = positions.filter(pk=position_id).first()
        if position is None:
            raise DomainError(_("Choose a position from the list."))

    membership.first_name = first_name
    membership.last_name = last_name
    membership.position = position
    membership.onboarded_at = timezone.now()
    membership.save()
    if membership.status == Membership.Status.PENDING:
        notify = tasks.notify_join_request  # now approvers have something to decide on
    else:
        notify = tasks.notify_onboarding_complete
    transaction.on_commit(partial(notify.delay, membership.pk))
    return membership


@transaction.atomic
def block(membership: Membership, *, by: User) -> Membership:
    membership = _lock(membership)
    ensure_can(by, membership.company, Perm.MEMBERS_MANAGE)
    if membership.user_id == by.pk:
        raise DomainError(_("You can't block yourself."))
    if (
        membership.role is not None
        and membership.role.is_owner
        and not _is_owner(by, membership.company)
    ):
        raise PermissionDenied(_("Only owners can block an owner."))
    if membership.status == Membership.Status.BLOCKED:
        raise DomainError(_("This member is already blocked."))

    membership.status = Membership.Status.BLOCKED
    _record_decision(membership, by)
    membership.save()
    _wind_down(membership)
    _audit(AuditLog.Action.MEMBER_BLOCKED, membership, by)
    return membership


@transaction.atomic
def offboard(membership: Membership, *, by: User) -> Membership:
    """Someone leaves the company: access ends now and their open work is handed back."""
    membership = _lock(membership)
    ensure_can(by, membership.company, Perm.MEMBERS_MANAGE)
    if membership.user_id == by.pk:
        raise DomainError(_("You can't offboard yourself."))
    if (
        membership.role is not None
        and membership.role.is_owner
        and not _is_owner(by, membership.company)
    ):
        raise PermissionDenied(_("Only owners can offboard an owner."))
    if membership.status != Membership.Status.APPROVED:
        raise DomainError(_("Only current members can be offboarded."))

    membership.status = Membership.Status.LEFT
    _record_decision(membership, by)
    membership.save()
    _wind_down(membership)
    _audit(AuditLog.Action.MEMBER_LEFT, membership, by)
    transaction.on_commit(partial(tasks.notify_offboarded.delay, membership.pk))
    return membership


def _wind_down(membership: Membership) -> None:
    """Hand their work back and drop time off they won't be taking."""
    task_services.hand_back_work(membership)
    TimeOff.objects.filter(
        membership=membership,
        status__in=(TimeOff.Status.PENDING, TimeOff.Status.APPROVED),
        last_day__gte=timezone.localdate(),
    ).update(status=TimeOff.Status.CANCELLED)


def _lock(membership: Membership) -> Membership:
    return (
        Membership.objects.select_for_update(of=("self",))
        .select_related("company", "role")
        .get(pk=membership.pk)
    )


def _audit(action: AuditLog.Action, membership: Membership, by: User) -> None:
    audit.record(action, company_id=membership.company_id, actor=by, target=membership)


def _ensure_status(membership: Membership, expected: Membership.Status) -> None:
    if membership.status != expected:
        raise DomainError(
            _("This request is already %(status)s.")
            % {"status": membership.get_status_display().lower()}
        )


def _is_owner(user: User, company: Company) -> bool:
    if user.is_platform_admin:
        return True
    actor = get_membership(user, company)
    return (
        actor is not None
        and actor.status == Membership.Status.APPROVED
        and actor.role is not None
        and actor.role.is_owner
    )


def _record_decision(membership: Membership, by: User) -> None:
    membership.decided_by = by
    membership.decided_at = timezone.now()
