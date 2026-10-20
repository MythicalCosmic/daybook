from collections.abc import Iterable
from datetime import date
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.models import Branch, Company
from apps.core.exceptions import DomainError
from apps.core.signals import send_on_commit
from apps.groups import tasks as group_jobs
from apps.members import signals, tasks
from apps.members.audit_actions import MemberAction
from apps.members.callbacks import JoinAction
from apps.members.models import AccessRole, Membership, Position
from apps.members.permissions import DEFAULT_ROLES, Perm
from apps.tasks import services as task_services
from apps.timeoff.models import TimeOff
from apps.timeoff.signals import time_off_cancelled

# A suspended person keeps their record; a blocked or offboarded one has left.
CURRENT = (Membership.Status.APPROVED, Membership.Status.SUSPENDED)


def create_default_roles(company: Company) -> None:
    """The roles of DEFAULT_ROLES the company doesn't have yet (by name)."""
    existing = set(AccessRole.objects.for_company(company).values_list("name", flat=True))
    has_default = AccessRole.objects.for_company(company).filter(is_default=True).exists()
    AccessRole.objects.bulk_create(
        AccessRole(
            company=company,
            name=role["name"],
            permissions=[str(perm) for perm in role.get("permissions", [])],
            is_owner=role.get("is_owner", False),
            is_default=role.get("is_default", False) and not has_default,
        )
        for role in DEFAULT_ROLES
        if role["name"] not in existing
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


# Who may hand out which role (docs/PLAN-OWNER.md §5, anti-escalation rules).


def may_grant(actor: Membership | None, permissions: Iterable[str]) -> bool:
    """Rule 2: a non-owner puts in a role's bundle only permissions they hold themselves."""
    if actor is None:
        return True  # the system or a platform admin
    if _is_owner_member(actor):
        return True
    return all(actor.has_perm(Perm(perm)) for perm in permissions)


def may_assign_role(
    actor: Membership | None, role: AccessRole, *, target: Membership | None = None
) -> bool:
    """Rules 1 and 2: only owners give or take away the Owner role; anyone else assigns only
    roles whose permissions they hold all of. (Rule 3: approving uses the same check.)"""
    if actor is None or _is_owner_member(actor):
        return True
    if role.company_id != actor.company_id or role.is_owner:
        return False
    if target is not None and target.role is not None and target.role.is_owner:
        return False
    return may_grant(actor, role.permissions)


def may_edit_role(actor: Membership | None, role: AccessRole) -> bool:
    """Rule 1: only owners edit the Owner role or a role they hold themselves."""
    if actor is None or _is_owner_member(actor):
        return True
    return not role.is_owner and role.pk != actor.role_id and may_grant(actor, role.permissions)


def ensure_may_assign_role(
    actor: Membership | None, role: AccessRole, *, target: Membership | None = None
) -> None:
    if not may_assign_role(actor, role, target=target):
        raise PermissionDenied(_("You can only give a role whose permissions you have yourself."))


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
    """Let a person in: the default role (or the one set on the request, if the approver may
    give it), and the company's branch when it has exactly one."""
    membership = _lock(membership)
    ensure_can(by, membership.company, Perm.MEMBERS_APPROVE)
    _ensure_status(membership, Membership.Status.PENDING)
    actor = _actor(by, membership.company)

    membership.status = Membership.Status.APPROVED
    if membership.role_id is None:
        membership.role = (
            AccessRole.objects.for_company(membership.company).filter(is_default=True).first()
        )
    elif not by.is_platform_admin:
        ensure_may_assign_role(actor, membership.role)
    only_branch = _only_active_branch(membership.company)
    if only_branch is not None:
        membership.home_branch = only_branch
    _record_decision(membership, by)
    membership.save()
    if only_branch is not None:
        membership.branches.set([only_branch])
    _audit(AuditLog.Action.MEMBER_APPROVED, membership, by)
    transaction.on_commit(partial(tasks.notify_join_decision.delay, membership.pk))
    transaction.on_commit(partial(group_jobs.announce_member.delay, membership.pk))
    send_on_commit(signals.member_approved, sender=Membership, membership=membership, by=actor)
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
    if _holds_owner_role(membership) and not _is_owner(by, membership.company):
        raise PermissionDenied(_("Only owners can block an owner."))
    if membership.status == Membership.Status.BLOCKED:
        raise DomainError(_("This member is already blocked."))
    _ensure_not_last_owner(membership)
    was_member = membership.status in CURRENT
    actor = _actor(by, membership.company)

    membership.status = Membership.Status.BLOCKED
    membership.suspended_until = None
    _record_decision(membership, by)
    membership.save()
    _wind_down(membership, by=actor)
    _audit(AuditLog.Action.MEMBER_BLOCKED, membership, by)
    if was_member:
        send_on_commit(
            signals.member_left,
            sender=Membership,
            membership=membership,
            reason="blocked",
            by=actor,
            details={},
            terminated_on=_today(membership.company),
        )
    return membership


@transaction.atomic
def offboard(
    membership: Membership,
    *,
    by: User,
    terminated_on: date | None = None,
    details: dict | None = None,
) -> Membership:
    """Someone leaves the company: access ends now and their open work is handed back.

    `terminated_on` is their last day (today when not given; never in the future), and
    `details` the offboarding wizard's answers per step key; both reach `member_left`.
    """
    membership = _lock(membership)
    ensure_can(by, membership.company, Perm.MEMBERS_MANAGE)
    if membership.user_id == by.pk:
        raise DomainError(_("You can't offboard yourself."))
    if _holds_owner_role(membership) and not _is_owner(by, membership.company):
        raise PermissionDenied(_("Only owners can offboard an owner."))
    if membership.status not in CURRENT:
        raise DomainError(_("Only current members can be offboarded."))
    today = _today(membership.company)
    terminated_on = terminated_on or today
    if terminated_on > today:
        raise DomainError(_("The last day can't be in the future."))
    _ensure_not_last_owner(membership)
    actor = _actor(by, membership.company)

    membership.status = Membership.Status.LEFT
    membership.suspended_until = None
    _record_decision(membership, by)
    membership.save()
    _wind_down(membership, by=actor)
    _audit(AuditLog.Action.MEMBER_LEFT, membership, by, terminated_on=terminated_on.isoformat())
    transaction.on_commit(partial(tasks.notify_offboarded.delay, membership.pk))
    send_on_commit(
        signals.member_left,
        sender=Membership,
        membership=membership,
        reason="left",
        by=actor,
        details=dict(details or {}),
        terminated_on=terminated_on,
    )
    return membership


@transaction.atomic
def suspend(
    membership: Membership, *, by: Membership | None, until: date | None, reason: str
) -> Membership:
    """Pause someone's access (discipline, an investigation) until `until` (their last
    suspended day) or until reinstated. Their record and work stay; the bot, the app and the
    reminders leave them alone, and they get no routine tasks meanwhile."""
    membership = _lock(membership)
    _ensure_may_suspend(membership, by)
    if membership.status != Membership.Status.APPROVED:
        raise DomainError(_("Only current members can be suspended."))
    reason = reason.strip()
    if not reason:
        raise DomainError(_("Say why they are suspended."))
    today = _today(membership.company)
    if until is not None and until < today:
        raise DomainError(_("The suspension can't end in the past."))
    _ensure_not_last_owner(membership)

    membership.status = Membership.Status.SUSPENDED
    membership.suspended_until = until
    membership.save(update_fields=["status", "suspended_until", "updated_at"])
    task_services.cancel_routine_tasks(membership, since=today)
    audit.record(
        MemberAction.SUSPENDED,
        company_id=membership.company_id,
        actor=by.user if by else None,
        target=membership,
        required_perm=Perm.HR_VIEW,
        until=until.isoformat() if until else None,
        reason=reason[:300],
    )
    transaction.on_commit(partial(tasks.notify_suspended.delay, membership.pk))
    send_on_commit(
        signals.member_suspended,
        sender=Membership,
        membership=membership,
        by=by,
        until=until,
        reason=reason,
    )
    return membership


@transaction.atomic
def reinstate(membership: Membership, *, by: Membership | None) -> Membership:
    """End a suspension: access comes back as it was."""
    membership = _lock(membership)
    _ensure_may_suspend(membership, by)
    if membership.status != Membership.Status.SUSPENDED:
        raise DomainError(_("This member isn't suspended."))

    membership.status = Membership.Status.APPROVED
    membership.suspended_until = None
    membership.save(update_fields=["status", "suspended_until", "updated_at"])
    audit.record(
        MemberAction.REINSTATED,
        company_id=membership.company_id,
        actor=by.user if by else None,
        target=membership,
        required_perm=Perm.HR_VIEW,
    )
    transaction.on_commit(partial(tasks.notify_reinstated.delay, membership.pk))
    send_on_commit(signals.member_reinstated, sender=Membership, membership=membership, by=by)
    return membership


def _wind_down(membership: Membership, *, by: Membership | None) -> None:
    """Hand their work back and drop time off they won't be taking, one row at a time so
    `time_off_cancelled` reaches the apps that keep balances."""
    task_services.hand_back_work(membership)
    cancelled = (
        TimeOff.objects.select_for_update()
        .filter(
            membership=membership,
            status__in=(TimeOff.Status.PENDING, TimeOff.Status.APPROVED),
            last_day__gte=_today(membership.company),
        )
        .order_by("first_day")
    )
    for time_off in cancelled:
        time_off.status = TimeOff.Status.CANCELLED
        time_off.save(update_fields=["status", "updated_at"])
        send_on_commit(time_off_cancelled, sender=TimeOff, time_off=time_off, by=by)


def _lock(membership: Membership) -> Membership:
    return (
        Membership.objects.select_for_update(of=("self",))
        .select_related("company", "role", "user")
        .get(pk=membership.pk)
    )


def _audit(action: str, membership: Membership, by: User, **details) -> None:
    audit.record(action, company_id=membership.company_id, actor=by, target=membership, **details)


def _ensure_status(membership: Membership, expected: Membership.Status) -> None:
    if membership.status != expected:
        raise DomainError(
            _("This request is already %(status)s.")
            % {"status": membership.get_status_display().lower()}
        )


def _ensure_may_suspend(membership: Membership, by: Membership | None) -> None:
    if by is None:
        return  # the system: a scheduled reinstatement
    if by.company_id != membership.company_id or not by.has_perm(Perm.HR_SUSPEND):
        raise PermissionDenied(_("You don't have permission to do this."))
    if by.pk == membership.pk:
        raise DomainError(_("You can't suspend or reinstate yourself."))
    if _holds_owner_role(membership) and not _is_owner_member(by):
        raise PermissionDenied(_("Only owners can suspend or reinstate an owner."))


def _ensure_not_last_owner(membership: Membership) -> None:
    """Rule 4: a company always keeps at least one approved owner."""
    if not (_holds_owner_role(membership) and membership.status == Membership.Status.APPROVED):
        return
    owners = list(
        Membership.objects.select_for_update(of=("self",))
        .filter(
            company_id=membership.company_id,
            status=Membership.Status.APPROVED,
            role__is_owner=True,
        )
        .values_list("pk", flat=True)
    )
    if not set(owners) - {membership.pk}:
        raise DomainError(_("This is the company's only owner. Make someone else an owner first."))


def _holds_owner_role(membership: Membership) -> bool:
    return membership.role is not None and membership.role.is_owner


def _is_owner_member(member: Membership) -> bool:
    return member.status == Membership.Status.APPROVED and _holds_owner_role(member)


def _is_owner(user: User, company: Company) -> bool:
    if user.is_platform_admin:
        return True
    actor = get_membership(user, company)
    return actor is not None and _is_owner_member(actor)


def _actor(user: User, company: Company) -> Membership | None:
    """The membership acting for `user` in `company`, for signals (None: a platform admin)."""
    member = get_membership(user, company)
    return member if member is not None and member.status == Membership.Status.APPROVED else None


def _only_active_branch(company: Company) -> Branch | None:
    branches = list(Branch.objects.filter(company=company, is_active=True)[:2])
    return branches[0] if len(branches) == 1 else None


def _record_decision(membership: Membership, by: User) -> None:
    membership.decided_by = by
    membership.decided_at = timezone.now()


def _today(company: Company) -> date:
    return timezone.localdate(timezone=ZoneInfo(company.timezone))
