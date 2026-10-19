from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.companies.models import Company
from apps.core.exceptions import DomainError
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm

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
    return membership


@transaction.atomic
def reject(membership: Membership, *, by: User) -> Membership:
    membership = _lock(membership)
    ensure_can(by, membership.company, Perm.MEMBERS_APPROVE)
    _ensure_status(membership, Membership.Status.PENDING)

    membership.status = Membership.Status.REJECTED
    _record_decision(membership, by)
    membership.save()
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
    return membership


def _lock(membership: Membership) -> Membership:
    return (
        Membership.objects.select_for_update(of=("self",))
        .select_related("company", "role")
        .get(pk=membership.pk)
    )


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
