from collections.abc import Iterable
from datetime import date, timedelta
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.models import Branch, Company
from apps.core.exceptions import DomainError
from apps.core.signals import send_on_commit
from apps.groups import tasks as group_jobs
from apps.inbox import services as inbox
from apps.members import queries, scope, signals, tasks
from apps.members.audit_actions import MemberAction
from apps.members.callbacks import JoinAction
from apps.members.models import AccessRole, Department, JoinLink, Membership, Position
from apps.members.permissions import DEFAULT_ROLES, Perm
from apps.tasks import services as task_services
from apps.timeoff.models import TimeOff
from apps.timeoff.signals import time_off_cancelled

# A suspended person keeps their record; a blocked or offboarded one has left.
CURRENT = (Membership.Status.APPROVED, Membership.Status.SUSPENDED)
# Join requests reach approvers as this inbox kind (Needs you + a Telegram copy).
JOIN_KIND = "members.join"
APPROVED = gettext_lazy("Approved")
REJECTED = gettext_lazy("Rejected")
# "Leave this field as it is" for update_member's nullable fields.
UNSET = object()


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
    # Someone coming back starts over: they get the default role again on approval, and the
    # team link they once came through and the department they were in no longer apply.
    membership.role = None
    membership.decided_by = None
    membership.decided_at = None
    membership.join_link = None
    membership.joined_by_link = False
    membership.department = None
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
def approve(
    membership: Membership,
    *,
    by: User,
    role: AccessRole | None = None,
    position: Position | None = None,
    branches: list[Branch] | None = None,
    home_branch: Branch | None = None,
    via: JoinLink | None = None,
    welcome: bool = True,
) -> Membership:
    """Let a person in: `role` if the approver may give it (rule 3), else the role set on the
    request, else the default one; `position` replaces the one they picked; `branches` and
    `home_branch` say where they work (the company's branch when it has exactly one). A request
    that came through a team link takes the link's role and branch when the approver names
    none and may give them.

    `via` is a team link letting the person in by itself (`admit`): `by` is the link's maker,
    whose right to give its role and branch is checked as for any approval; the person hears a
    welcome instead of a decision (unless `welcome` is False: the caller answers them itself),
    and approvers and groups hear about a burst of joins at once.

    Every approver's copy of the request, in the bot and in Needs you, shows the outcome."""
    membership = _lock(membership)
    ensure_can(by, membership.company, Perm.MEMBERS_APPROVE)
    _ensure_status(membership, Membership.Status.PENDING)
    actor = _actor(by, membership.company)
    company = membership.company
    link = via or (membership.join_link if membership.join_link_id else None)

    chosen_role = role
    if (
        role is None
        and membership.role_id is None
        and link is not None
        and link.role_id
        and (via is not None or by.is_platform_admin or may_assign_role(actor, link.role))
    ):
        role = link.role
    if role is not None:
        if role.company_id != company.pk:
            raise DomainError(_("Pick a role of this company."))
        membership.role = role
    if membership.role_id is None:
        membership.role = AccessRole.objects.for_company(company).filter(is_default=True).first()
    elif not by.is_platform_admin:
        ensure_may_assign_role(actor, membership.role)
    if position is not None:
        if position.company_id != company.pk or not position.is_active:
            raise DomainError(_("Pick a position of this company."))
        membership.position = position
    chosen = _valid_branches(company, branches, home_branch, actor=actor)
    if chosen is None and link is not None:
        chosen = _link_branches(company, link, actor=actor, strict=via is not None)
    if chosen is None:
        only_branch = _only_active_branch(company)
        chosen = ([only_branch], only_branch) if only_branch is not None else None
    if chosen is not None:
        membership.home_branch = chosen[1]
    membership.status = Membership.Status.APPROVED
    membership.joined_by_link = via is not None
    _record_decision(membership, by)
    membership.save()
    if chosen is not None:
        membership.branches.set(chosen[0])
    # What the approver chose is recorded; defaults (the request's role, the only branch) aren't.
    chose = {}
    if chosen_role is not None:
        chose["role"] = membership.role.name
    if branches is not None and chosen is not None:
        chose["branches"] = [branch.name for branch in chosen[0]]
    if via is not None:
        chose["link"] = via.name
    _audit(AuditLog.Action.MEMBER_APPROVED, membership, by, **chose)
    inbox.settle(membership, outcome=APPROVED, by=actor, kind=JOIN_KIND)
    if via is None:
        transaction.on_commit(partial(tasks.notify_join_decision.delay, membership.pk))
        transaction.on_commit(partial(group_jobs.announce_member.delay, membership.pk))
    else:
        if welcome:
            transaction.on_commit(partial(tasks.notify_joined.delay, membership.pk))
        transaction.on_commit(partial(tasks.queue_link_report, via.pk))
    pulses = ["members.pending", "members.people"]
    if membership.join_link_id is not None:
        pulses.append("members.links")
    transaction.on_commit(partial(_bump, company.pk, *pulses))
    send_on_commit(signals.member_approved, sender=Membership, membership=membership, by=actor)
    return membership


def admit(
    membership: Membership, *, welcome: bool = True, count_refusal: bool = True
) -> Membership | None:
    """Someone created their account through a team link, or opened one while their request
    waits: count them against the link and, when it lets them in (`link_lets_in`), approve them
    on its maker's authority.

    Returns the approved membership, or None when they stay a join request. A place is used by
    finishing an account through the link; `count_refusal=False` (opening a link while already
    waiting) uses one only if the link lets them in, so switching between links takes none.
    Runs inside the caller's transaction; the link's row lock gives the last place to one."""
    if membership.status != Membership.Status.PENDING or not membership.is_onboarded:
        return None
    link = (
        JoinLink.objects.select_for_update(of=("self",))
        .select_related("company", "branch", "role", "created_by__role", "created_by__user")
        .filter(pk=membership.join_link_id)
        .first()
    )
    if link is None or link.status_at(timezone.now()) != JoinLink.Status.ACTIVE:
        return None
    admitted = None
    if link_lets_in(membership, link):
        role = link.role or _default_role(link.company)
        try:
            with transaction.atomic():  # a refusal leaves the request as it was
                admitted = approve(
                    membership, by=link.created_by.user, role=role, via=link, welcome=welcome
                )
        except DomainError, PermissionDenied:
            admitted = None
    if admitted is not None or count_refusal:
        link.uses += 1
        link.save(update_fields=["uses", "updated_at"])
        transaction.on_commit(partial(_bump, link.company_id, "members.links"))
    return admitted


def link_lets_in(membership: Membership, link: JoinLink | None) -> bool:
    """Whether `link` lets `membership` in by itself once their account is made: it works and
    adds people straight away; its maker may still approve, and give its role (the default one
    when it names none) and its branch (a link without one only while the company has a single
    branch); and the person never left, was blocked or was turned down here: they come back
    through an approver. The bot promises "no waiting" only when this holds."""
    if link is None or not link.auto_approve:
        return False
    if link.status_at(timezone.now()) != JoinLink.Status.ACTIVE:
        return False
    maker = link.created_by
    if maker is None or not maker.has_perm(Perm.MEMBERS_APPROVE):
        return False
    role = link.role or _default_role(link.company)
    if role is None or role.is_owner or not may_assign_role(maker, role):
        return False
    if link.branch_id is None:
        if Branch.objects.filter(company_id=link.company_id, is_active=True).count() > 1:
            return False
    elif not link.branch.is_active or not scope.allows(scope.branch_ids(maker), link.branch_id):
        return False
    return not _turned_away(membership)


def _turned_away(membership: Membership) -> bool:
    """Whether the person left, was blocked or was turned down in this company before."""
    return AuditLog.objects.filter(
        company_id=membership.company_id,
        target_type="membership",
        target_id=membership.pk,
        action__in=(
            AuditLog.Action.MEMBER_LEFT,
            AuditLog.Action.MEMBER_BLOCKED,
            AuditLog.Action.MEMBER_REJECTED,
        ),
    ).exists()


def _default_role(company: Company) -> AccessRole | None:
    return AccessRole.objects.for_company(company).filter(is_default=True).first()


def decide_many(
    company: Company,
    *,
    by: Membership,
    ids: list[int],
    approve_them: bool,
    role: AccessRole | None = None,
    position: Position | None = None,
    branches: list[Branch] | None = None,
    home_branch: Branch | None = None,
    reason: str = "",
) -> list[dict]:
    """Approve or reject several join requests, each on its own, so one refusal doesn't stop
    the rest: `{"id", "ok", "detail"}` per id, in the order given. Approving names one role and
    branch for all, or none, and then each person gets their team link's (else the defaults)."""
    found = {row.pk: row for row in queries.join_requests(company).filter(pk__in=ids)}
    decided: dict[int, dict] = {}
    results = []
    for pk in ids:
        if pk not in decided:  # an id sent twice gets the first answer again
            decided[pk] = _decide_one(
                found.get(pk),
                pk,
                by=by,
                approve_them=approve_them,
                role=role,
                position=position,
                branches=branches,
                home_branch=home_branch,
                reason=reason,
            )
        results.append(dict(decided[pk]))
    return results


def _decide_one(
    membership: Membership | None, pk: int, *, by: Membership, approve_them: bool, **choices
) -> dict:
    if membership is None:
        return {"id": pk, "ok": False, "detail": _("This request no longer exists.")}
    if approve_them and not membership.is_onboarded:
        return {"id": pk, "ok": False, "detail": _("They haven't filled in their details yet.")}
    reason = choices.pop("reason")
    try:
        if approve_them:
            approve_request(membership, by=by, **choices)
        else:
            reject_request(membership, by=by, reason=reason)
    except (DomainError, PermissionDenied) as exc:
        return {"id": pk, "ok": False, "detail": str(exc)}
    return {"id": pk, "ok": True, "detail": ""}


@transaction.atomic
def reject(membership: Membership, *, by: User, reason: str = "") -> Membership:
    membership = _lock(membership)
    ensure_can(by, membership.company, Perm.MEMBERS_APPROVE)
    _ensure_status(membership, Membership.Status.PENDING)

    membership.status = Membership.Status.REJECTED
    _record_decision(membership, by)
    membership.save()
    reason = (reason or "").strip()[:300]
    if reason:
        _audit(AuditLog.Action.MEMBER_REJECTED, membership, by, reason=reason)
    else:
        _audit(AuditLog.Action.MEMBER_REJECTED, membership, by)
    actor = _actor(by, membership.company)
    inbox.settle(membership, outcome=REJECTED, by=actor, kind=JOIN_KIND)
    transaction.on_commit(partial(tasks.notify_join_decision.delay, membership.pk))
    transaction.on_commit(partial(_bump, membership.company_id, "members.pending"))
    return membership


def approve_request(
    membership: Membership,
    *,
    by: Membership,
    role: AccessRole | None = None,
    position: Position | None = None,
    branches: list[Branch] | None = None,
    home_branch: Branch | None = None,
) -> Membership:
    """`approve` for a dashboard user acting in their company (by: Membership)."""
    _ensure_same_company(membership, by)
    return approve(
        membership,
        by=by.user,
        role=role,
        position=position,
        branches=branches,
        home_branch=home_branch,
    )


def reject_request(membership: Membership, *, by: Membership, reason: str = "") -> Membership:
    _ensure_same_company(membership, by)
    return reject(membership, by=by.user, reason=reason)


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
    if membership.join_link_id is not None:
        admitted = admit(membership)
        if admitted is not None:
            return admitted
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
    today = _today(membership.company)
    if was_member:
        _audit(AuditLog.Action.MEMBER_BLOCKED, membership, by, terminated_on=today.isoformat())
        send_on_commit(
            signals.member_left,
            sender=Membership,
            membership=membership,
            reason="blocked",
            by=actor,
            details={},
            terminated_on=today,
        )
    else:
        _audit(AuditLog.Action.MEMBER_BLOCKED, membership, by)
    inbox.settle(membership, outcome=REJECTED, by=actor, kind=JOIN_KIND)
    transaction.on_commit(
        partial(_bump, membership.company_id, "members.people", "members.pending")
    )
    return membership


@transaction.atomic
def offboard(
    membership: Membership,
    *,
    by: User | None,
    terminated_on: date | None = None,
    details: dict | None = None,
    reason: str = "",
) -> Membership:
    """Someone leaves the company: access ends now and their open work is handed back.

    `terminated_on` is their last day (today when not given; never in the future), and
    `details` the offboarding wizard's answers per step key; both reach `member_left`.
    `by=None` is the system (a termination scheduled for that day); `reason` is the
    wizard's reason code, kept in the audit log.
    """
    membership = _lock(membership)
    if by is not None:
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
    actor = _actor(by, membership.company) if by is not None else None

    membership.status = Membership.Status.LEFT
    membership.suspended_until = None
    _record_decision(membership, by)
    membership.save()
    _wind_down(membership, by=actor)
    extra = {"reason": reason} if reason else {}
    _audit(
        AuditLog.Action.MEMBER_LEFT,
        membership,
        by,
        terminated_on=terminated_on.isoformat(),
        **extra,
    )
    transaction.on_commit(partial(tasks.notify_offboarded.delay, membership.pk))
    transaction.on_commit(partial(_bump, membership.company_id, "members.people"))
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
    task_services.resume_reminders(membership)
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


def reinstate_finished_suspensions(now=None) -> int:
    """Reinstate everyone whose suspension is over: its last day (`suspended_until`) is before
    today in their company's timezone. Celery beat runs it (apps.members.schedule); returns
    how many came back."""
    now = now or timezone.now()
    candidates = list(
        Membership.objects.filter(
            status=Membership.Status.SUSPENDED,
            suspended_until__isnull=False,
            suspended_until__lt=timezone.localtime(now).date() + timedelta(days=1),
            company__is_active=True,
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    reinstated = 0
    for membership_id in candidates:
        with transaction.atomic():
            membership = (
                Membership.objects.select_for_update(of=("self",))
                .select_related("company")
                .filter(pk=membership_id, status=Membership.Status.SUSPENDED)
                .first()
            )
            if membership is None or membership.suspended_until is None:
                continue  # reinstated or dismissed a moment ago
            if membership.suspended_until >= _local_date(membership.company, now):
                continue  # still their last suspended day where they are
            reinstate(membership, by=None)
            reinstated += 1
    return reinstated


# Owner console: people, roles, positions, offboarding (by: Membership) ------------------


def block_member(membership: Membership, *, by: Membership) -> Membership:
    """`block` for a dashboard user: access ends for good and they can't ask to join again."""
    _ensure_same_company(membership, by)
    return block(membership, by=by.user)


@transaction.atomic
def unblock(membership: Membership, *, by: Membership) -> Membership:
    """Lift a block: they count as a former member again and may ask to join with the invite
    link (a new request is approved like anyone's)."""
    _ensure_same_company(membership, by)
    membership = _lock(membership)
    if not by.has_perm(Perm.MEMBERS_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))
    if membership.status != Membership.Status.BLOCKED:
        raise DomainError(_("This person isn't blocked."))
    membership.status = Membership.Status.LEFT
    membership.save(update_fields=["status", "updated_at"])
    audit.record(
        MemberAction.UNBLOCKED, company_id=membership.company_id, actor=by.user, target=membership
    )
    transaction.on_commit(partial(_bump, membership.company_id, "members.people"))
    return membership


@transaction.atomic
def update_member(
    membership: Membership,
    *,
    by: Membership,
    first_name: str | None = None,
    last_name: str | None = None,
    position: Position | object | None = UNSET,
    branches: list[Branch] | None = None,
    home_branch: Branch | object | None = UNSET,
    department: Department | object | None = UNSET,
) -> Membership:
    """Change someone's name, position, branches, home branch or department (members.manage).
    Someone who sees only some branches can hand out only those, and keeps the others as they
    were."""
    _ensure_same_company(membership, by)
    membership = _lock(membership)
    if not by.has_perm(Perm.MEMBERS_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))
    if membership.status not in CURRENT:
        raise DomainError(_("Only current members can be changed."))
    if _holds_owner_role(membership) and not _is_owner_member(by) and by.pk != membership.pk:
        raise PermissionDenied(_("Only owners can change an owner."))
    company = membership.company
    changes: dict[str, list] = {}

    for field, value in (("first_name", first_name), ("last_name", last_name)):
        if value is None:
            continue
        value = value.strip()[:100]
        if field == "first_name" and not value:
            raise DomainError(_("A first name is required."))
        if value != getattr(membership, field):
            changes[field] = [getattr(membership, field), value]
            setattr(membership, field, value)

    if position is not UNSET:
        if position is not None and (position.company_id != company.pk or not position.is_active):
            raise DomainError(_("Pick a position of this company."))
        if (position.pk if position else None) != membership.position_id:
            changes["position"] = [
                membership.position.name if membership.position else None,
                position.name if position else None,
            ]
            membership.position = position

    if department is not UNSET:
        if department is not None and department.company_id != company.pk:
            raise DomainError(_("Pick a department of this company."))
        if (department.pk if department else None) != membership.department_id:
            changes["department"] = [
                membership.department.name if membership.department_id else None,
                department.name if department else None,
            ]
            membership.department = department
            bump_on_commit(company.pk, "members.departments")  # the org chart's counts

    new_branches = None
    if branches is not None:
        if any(b.company_id != company.pk or not b.is_active for b in branches):
            raise DomainError(_("Pick branches of this company."))
        current = list(membership.branches.all())
        allowed = scope.branch_ids(by)
        if allowed is not None and any(branch.pk not in allowed for branch in branches):
            raise PermissionDenied(_("You can only give the branches you manage."))
        kept = [b for b in current if allowed is not None and b.pk not in allowed]
        new_branches = _dedupe([*kept, *branches])
        if {b.pk for b in new_branches} != {b.pk for b in current}:
            changes["branches"] = [
                sorted(b.name for b in current),
                sorted(b.name for b in new_branches),
            ]

    if home_branch is not UNSET:
        if home_branch is not None and home_branch.company_id != company.pk:
            raise DomainError(_("Pick a branch of this company."))
        if (home_branch.pk if home_branch else None) != membership.home_branch_id:
            changes["home_branch"] = [
                membership.home_branch.name if membership.home_branch else None,
                home_branch.name if home_branch else None,
            ]
            membership.home_branch = home_branch

    final = new_branches if new_branches is not None else list(membership.branches.all())
    final_ids = {b.pk for b in final}
    if (
        membership.home_branch_id is not None
        and final
        and membership.home_branch_id not in final_ids
    ):
        if home_branch is not UNSET:
            raise DomainError(_("The home branch must be one of their branches."))
        # Their home branch was taken away: the first remaining branch becomes it.
        changes["home_branch"] = [membership.home_branch.name, final[0].name]
        membership.home_branch = final[0]
    if membership.home_branch_id is None and final and new_branches is not None:
        membership.home_branch = final[0]
        changes.setdefault("home_branch", [None, final[0].name])

    if not changes:
        return membership
    membership.save()
    if new_branches is not None:
        membership.branches.set(new_branches)
    audit.record(
        MemberAction.CHANGED,
        company_id=membership.company_id,
        actor=by.user,
        target=membership,
        changes=changes,
    )
    transaction.on_commit(partial(_bump, membership.company_id, "members.people"))
    return membership


@transaction.atomic
def change_role(membership: Membership, *, by: Membership, role: AccessRole) -> Membership:
    """Give someone another role, by the anti-escalation rules (§5): only owners give or take
    the Owner role; anyone else gives only roles whose permissions they hold all of; the last
    owner can't be demoted."""
    _ensure_same_company(membership, by)
    membership = _lock(membership)
    if not by.has_perm(Perm.ROLES_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))
    if role.company_id != membership.company_id:
        raise DomainError(_("Pick a role of this company."))
    if membership.status not in CURRENT:
        raise DomainError(_("Only current members can be changed."))
    if membership.role_id == role.pk:
        return membership
    ensure_may_assign_role(by, role, target=membership)
    # Rule 2 both ways: a non-owner moves someone only out of a role they could have given.
    if membership.role is not None and not may_assign_role(by, membership.role, target=membership):
        raise PermissionDenied(
            _("You can only change the role of someone whose role you could give yourself.")
        )
    if _holds_owner_role(membership) and not role.is_owner:
        _ensure_not_last_owner(membership)
    before = membership.role.name if membership.role else None
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    audit.record(
        MemberAction.ROLE_CHANGED,
        company_id=membership.company_id,
        actor=by.user,
        target=membership,
        changes={"role": [before, role.name]},
    )
    transaction.on_commit(partial(_bump, membership.company_id, "members.people"))
    return membership


@transaction.atomic
def save_role(
    company: Company,
    *,
    by: Membership,
    role: AccessRole | None = None,
    name: str,
    permissions: Iterable[str],
    is_default: bool | None = None,
) -> AccessRole:
    """Create a role or change one's name, permissions and default flag. Rules (§5): only
    owners edit the Owner role or a role they hold; a non-owner puts in a bundle only
    permissions they hold themselves (and takes out only those too)."""
    if by.company_id != company.pk or not by.has_perm(Perm.ROLES_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))
    name = (name or "").strip()[:100]
    if not name:
        raise DomainError(_("Name the role."))
    codes = sorted({str(code) for code in permissions})
    unknown = [code for code in codes if code not in Perm.values]
    if unknown:
        raise DomainError(_("Unknown permission: %(code)s") % {"code": unknown[0]})
    if role is not None:
        role = AccessRole.objects.select_for_update().get(pk=role.pk, company=company)
        if not may_edit_role(by, role):
            raise PermissionDenied(_("Only owners can change this role."))
    if is_default and role is not None and role.is_owner:
        # Every approved join request would make its person an owner.
        raise DomainError(_("The Owner role can't be the default one."))
    clash = AccessRole.objects.for_company(company).filter(name__iexact=name)
    if role is not None:
        clash = clash.exclude(pk=role.pk)
    if clash.exists():
        raise DomainError(_("There is already a role with that name."))
    before_codes = set(role.permissions) if role is not None else set()
    if role is None or not role.is_owner:
        added = set(codes) - before_codes
        removed = before_codes - set(codes)
        if not may_grant(by, added):
            raise PermissionDenied(_("You can only grant permissions you have yourself."))
        if not may_grant(by, removed):
            raise PermissionDenied(_("You can only take away permissions you have yourself."))

    created = role is None
    if created:
        role = AccessRole(company=company)
    before_name = role.name
    role.name = name
    if not role.is_owner:
        role.permissions = codes
    role.save()
    if is_default and not role.is_default:
        AccessRole.objects.for_company(company).exclude(pk=role.pk).update(is_default=False)
        role.is_default = True
        role.save(update_fields=["is_default", "updated_at"])
    changes = {}
    if before_name != role.name:
        changes["name"] = [before_name or None, role.name]
    if not role.is_owner and sorted(before_codes) != codes:
        changes["permissions"] = [sorted(before_codes), codes]
    if is_default:
        changes["is_default"] = [False, True]
    audit.record(
        MemberAction.ROLE_CREATED if created else MemberAction.ROLE_SAVED,
        company_id=company.pk,
        actor=by.user,
        target=role,
        changes=changes,
    )
    transaction.on_commit(partial(_bump, company.pk, "members.roles", "members.people"))
    return role


@transaction.atomic
def delete_role(role: AccessRole, *, by: Membership) -> None:
    """Remove a role nobody holds (never the Owner role or the default one)."""
    role = AccessRole.objects.select_for_update().get(pk=role.pk)
    if by.company_id != role.company_id or not by.has_perm(Perm.ROLES_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))
    if not may_edit_role(by, role):
        raise PermissionDenied(_("Only owners can change this role."))
    if role.is_owner:
        raise DomainError(_("The Owner role can't be deleted."))
    if role.is_default:
        raise DomainError(_("Make another role the default one first."))
    if Membership.objects.filter(role=role).exists():
        raise DomainError(_("Give the people in this role another role first."))
    audit.record(
        MemberAction.ROLE_DELETED,
        company_id=role.company_id,
        actor=by.user,
        target=role,
        name=role.name,
    )
    role.delete()
    transaction.on_commit(partial(_bump, by.company_id, "members.roles"))


@transaction.atomic
def save_position(
    company: Company,
    *,
    by: Membership,
    position: Position | None = None,
    name: str | None = None,
    is_active: bool | None = None,
) -> Position:
    """Create a position or rename, hide or bring back one (positions.manage)."""
    if by.company_id != company.pk or not by.has_perm(Perm.POSITIONS_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))
    created = position is None
    if created:
        position = Position(company=company, order=_next_order(company))
    else:
        position = Position.objects.select_for_update().get(pk=position.pk, company=company)
    changes = {}
    if name is not None or created:
        clean = (name or "").strip()[:100]
        if not clean:
            raise DomainError(_("Name the position."))
        clash = Position.objects.for_company(company).filter(name__iexact=clean)
        if not created:
            clash = clash.exclude(pk=position.pk)
        if clash.exists():
            raise DomainError(_("There is already a position with that name."))
        if clean != position.name:
            changes["name"] = [position.name or None, clean]
            position.name = clean
    if is_active is not None and is_active != position.is_active:
        changes["is_active"] = [position.is_active, is_active]
        position.is_active = is_active
    if not changes and not created:
        return position
    position.save()
    audit.record(
        MemberAction.POSITION_CREATED if created else MemberAction.POSITION_SAVED,
        company_id=company.pk,
        actor=by.user,
        target=position,
        changes=changes,
    )
    transaction.on_commit(partial(_bump, company.pk, "members.positions"))
    return position


@transaction.atomic
def delete_position(position: Position, *, by: Membership) -> None:
    """Remove a position nobody ever held; one in use is hidden instead (is_active)."""
    position = Position.objects.select_for_update().get(pk=position.pk)
    if by.company_id != position.company_id or not by.has_perm(Perm.POSITIONS_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))
    if Membership.objects.filter(position=position).exists():
        raise DomainError(_("People hold this position: hide it instead of deleting it."))
    audit.record(
        MemberAction.POSITION_DELETED,
        company_id=position.company_id,
        actor=by.user,
        target=position,
        name=position.name,
    )
    try:
        with transaction.atomic():
            position.delete()
    except ProtectedError:
        raise DomainError(
            _("This position is still used elsewhere: hide it instead of deleting it.")
        ) from None
    transaction.on_commit(partial(_bump, by.company_id, "members.positions"))


@transaction.atomic
def reorder_positions(company: Company, *, by: Membership, ids: list[int]) -> None:
    """Put positions in this order (the order people see when they register)."""
    if by.company_id != company.pk or not by.has_perm(Perm.POSITIONS_MANAGE):
        raise PermissionDenied(_("You don't have permission to do this."))
    positions = {p.pk: p for p in Position.objects.select_for_update().filter(company=company)}
    if set(ids) - set(positions) or len(set(ids)) != len(ids):
        raise DomainError(_("Send each of the company's positions once."))
    rest = sorted((p for pk, p in positions.items() if pk not in ids), key=lambda p: p.order)
    for index, position in enumerate([positions[pk] for pk in ids] + rest):
        if position.order != index:
            position.order = index
            position.save(update_fields=["order", "updated_at"])
    audit.record(
        MemberAction.POSITIONS_REORDERED,
        company_id=company.pk,
        actor=by.user,
        target=company,
        order=[positions[pk].name for pk in ids],
    )
    transaction.on_commit(partial(_bump, company.pk, "members.positions"))


def offboard_preview(membership: Membership, *, by: Membership | None = None) -> dict:
    """The offboarding wizard for `membership`, in step order: every registered step `by` may
    run with its lines, blockers, questions and default answers (everything for the system).

    A step `by` may not see still blocks: it comes as `restricted` with its label and blockers
    only (no lines, questions or answers), so nobody offboards around, say, cash still held
    just because they can't open Sales."""
    steps = [_as_seen_by(step, by) for step in _offboard_steps(membership, by=by)]
    steps = [step for step in steps if step is not None]
    return {
        "steps": steps,
        "blockers": sum(len(step.get("blockers") or []) for step in steps),
        "can_override": by is None or _is_owner_member(by),
    }


def _offboard_steps(membership: Membership, *, by: Membership | None) -> list[dict]:
    """Every registered step's preview as an owner of the company sees it (`by` when the
    company has no approved owner left to stand in)."""
    from apps.console.registry import collect_offboard_steps

    viewer = (
        Membership.objects.filter(
            company_id=membership.company_id,
            status=Membership.Status.APPROVED,
            role__is_owner=True,
        )
        .select_related("role", "company")
        .first()
    ) or by
    return collect_offboard_steps(membership, by=viewer) if viewer is not None else []


def _may_see_step(step: dict, by: Membership | None) -> bool:
    from apps.console.registry import OFFBOARD_STEPS, usable

    entry = OFFBOARD_STEPS.get(step["key"])
    return by is None or entry is None or usable(entry, by)


def _as_seen_by(step: dict, by: Membership | None) -> dict | None:
    if _may_see_step(step, by):
        return step
    if not step.get("blockers"):
        return None  # nothing in it concerns them
    return step | {"lines": [], "fields": [], "defaults": {}, "restricted": True}


# Why someone leaves (the wizard's first question; package S's Termination kinds match).
OFFBOARD_REASONS = (
    "resignation",
    "mutual_agreement",
    "contract_end",
    "dismissal",
    "probation_failed",
    "redundancy",
    "other",
)


@transaction.atomic
def complete_offboarding(
    membership: Membership,
    *,
    by: Membership | None,
    terminated_on: date | None,
    reason: str,
    note: str = "",
    steps: dict | None = None,
    override_blockers: bool = False,
) -> Membership:
    """The offboarding wizard's last step, and what a scheduled termination (package S) calls
    on the person's last day with `by=None`.

    Every registered step's blockers stop it, those of steps `by` can't see included, unless an
    owner overrides them (the system may); each step's required questions must be answered
    (missing answers take the step's defaults; a step `by` can't see keeps its defaults). The
    answers reach `member_left` receivers as `details[step key]`, and the wizard's own as
    `details["members"] = {"reason", "note", "override_blockers"}`."""
    if reason not in OFFBOARD_REASONS:
        raise DomainError(_("Pick why they are leaving."))
    if by is not None:
        _ensure_same_company(membership, by)
        if not by.has_perm(Perm.MEMBERS_MANAGE):
            raise PermissionDenied(_("You don't have permission to do this."))
    every_step = _offboard_steps(membership, by=by)
    blockers = [line for step in every_step for line in step.get("blockers") or []]
    if blockers and not override_blockers:
        raise DomainError(blockers[0])
    if blockers and by is not None and not _is_owner_member(by):
        raise PermissionDenied(_("Only an owner can go ahead despite the blockers."))
    answers = steps or {}
    details: dict[str, dict] = {}
    for step in every_step:
        given = answers.get(step["key"]) or {}
        if not isinstance(given, dict):
            raise DomainError(_("The answers of %(step)s are invalid.") % {"step": step["label"]})
        visible = _may_see_step(step, by)
        merged = {**(step.get("defaults") or {}), **(given if visible else {})}
        for field in step.get("fields") or []:
            if visible and field.get("required") and merged.get(field["name"]) in (None, ""):
                raise DomainError(
                    _("%(step)s: “%(field)s” is required.")
                    % {"step": step["label"], "field": field["label"]}
                )
        details[step["key"]] = merged
    details["members"] = {
        **details.get("members", {}),
        "reason": reason,
        "note": (note or "").strip()[:1000],
        "override_blockers": bool(blockers),
    }
    return offboard(
        membership,
        by=by.user if by is not None else None,
        terminated_on=terminated_on,
        details=details,
        reason=reason,
    )


def _valid_branches(
    company: Company,
    branches: list[Branch] | None,
    home_branch: Branch | None,
    *,
    actor: Membership | None,
) -> tuple[list[Branch], Branch] | None:
    """Checked (branches, home branch) for an approval, or None when none were given."""
    if not branches:
        if home_branch is None:
            return None
        branches = [home_branch]
    if any(branch.company_id != company.pk or not branch.is_active for branch in branches):
        raise DomainError(_("Pick branches of this company."))
    allowed = scope.branch_ids(actor) if actor is not None else None
    if allowed is not None and any(branch.pk not in allowed for branch in branches):
        raise PermissionDenied(_("You can only give the branches you manage."))
    branches = _dedupe(branches)
    if home_branch is None:
        home_branch = branches[0]
    if home_branch.pk not in {branch.pk for branch in branches}:
        raise DomainError(_("The home branch must be one of their branches."))
    return branches, home_branch


def _link_branches(
    company: Company, link: JoinLink, *, actor: Membership | None, strict: bool
) -> tuple[list[Branch], Branch] | None:
    """A team link's branch for an approval that names none. For the link letting someone in
    (`strict`), a closed branch or one its maker no longer manages stops the approval; an
    approver gets the usual default instead."""
    if link.branch_id is None:
        return None
    try:
        return _valid_branches(company, [link.branch], link.branch, actor=actor)
    except DomainError, PermissionDenied:
        if strict:
            raise
        return None


def _dedupe(branches: list[Branch]) -> list[Branch]:
    seen: dict[int, Branch] = {}
    for branch in branches:
        seen.setdefault(branch.pk, branch)
    return list(seen.values())


def _next_order(company: Company) -> int:
    last = Position.objects.for_company(company).order_by("-order").first()
    return (last.order + 1) if last else 0


def _ensure_same_company(membership: Membership, by: Membership) -> None:
    if by.company_id != membership.company_id or by.status != Membership.Status.APPROVED:
        raise PermissionDenied(_("You don't have permission to do this."))


def _bump(company_id: int, *keys: str) -> None:
    from apps.console import pulse

    pulse.bump(company_id, *keys)


def bump_on_commit(company_id: int, *keys: str) -> None:
    """Move pulse keys on once the current transaction commits (open dashboards refetch)."""
    transaction.on_commit(partial(_bump, company_id, *keys))


def _wind_down(membership: Membership, *, by: Membership | None) -> None:
    """Hand their work back, leave the departments they headed without a head, and drop time
    off they won't be taking, one row at a time so `time_off_cancelled` reaches the apps that
    keep balances."""
    task_services.hand_back_work(membership)
    if Department.objects.filter(head=membership).update(head=None):
        bump_on_commit(membership.company_id, "members.departments")
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
        previous_status = time_off.status
        time_off.status = TimeOff.Status.CANCELLED
        time_off.save(update_fields=["status", "updated_at"])
        send_on_commit(
            time_off_cancelled,
            sender=TimeOff,
            time_off=time_off,
            by=by,
            previous_status=previous_status,
        )


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


def _local_date(company: Company, moment) -> date:
    return timezone.localtime(moment, ZoneInfo(company.timezone)).date()
