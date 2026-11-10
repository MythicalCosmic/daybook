"""Job changes (docs/PLAN-OWNER.md §13.4 `JobChange`): a new position, home branch, department or
pay for someone from a day.

- `propose` (hr.manage; pay also needs payroll.manage): what changes and from which day (today or
  later), with the reason. It waits in Needs you for someone who may decide it, unless the
  proposer may and approves it at once.
- `approve` / `reject` (`may_decide`): hr.manage, members.manage for the position, branch or
  department, payroll.manage for pay, the person inside their branch scope (and the new branch),
  never their own job, an owner's only by an owner.
- On its day (Celery every 15 minutes, in the company's time; at once when approved on or after
  it) an approved change applies itself through the owning apps, as the one who approved it:
  `members.services.update_member` for the position (the access a job title brings follows only
  within what the approver may give), the home branch (they move there from their old one) and
  the department; `hr.contracts.amend` for the contract's position; `payroll.services.
  propose_pay_change` for the pay. A refusal (the approver lost the right, the position was
  removed) keeps it approved with the reason until someone presses "Try again" or cancels it.
- `before` keeps what it was when it applied, `after` what it became (the role included): the
  person's history reads them. Pay in them is for payroll.view only.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, pgettext_lazy

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.hr import queries as hr_queries
from apps.inbox import services as inbox
from apps.lifecycle import integrations, tasks
from apps.lifecycle.audit_actions import LifecycleAction
from apps.lifecycle.models import JobChange
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

Status = JobChange.Status
OPEN = (Status.PROPOSED, Status.APPROVED)
CLOSED = (Status.REJECTED, Status.CANCELLED)
PARTS = ("position", "branch", "department", "pay")
# The parts members.services changes (members.manage decides them).
MEMBER_PARTS = ("position", "branch", "department")
PULSE = "lifecycle.changes"
QUEUE = "lifecycle.job_changes"
REQUEST_KIND = "lifecycle.job_change"
MAX_DAYS_AHEAD = 366
MAX_REASON = 1000
UNSET = object()


# Who may -------------------------------------------------------------------------------------


def _is_owner(member: Membership | None) -> bool:
    return member is not None and member.role is not None and member.role.is_owner


def may_propose(member: Membership, person: Membership, *, in_scope: bool = False) -> bool:
    """hr.manage, the person in `member`'s branch scope, never themselves, an owner only by an
    owner. `in_scope`: the caller already limited the people to `member`'s scope."""
    if member.company_id != person.company_id or member.pk == person.pk:
        return False
    if member.status != Membership.Status.APPROVED or not member.has_perm(Perm.HR_MANAGE):
        return False
    if _is_owner(person) and not _is_owner(member):
        return False
    if in_scope:
        return True
    return (
        hr_queries.person(person.company, person.pk, branch_ids=scope.branch_ids(member))
        is not None
    )


def may_decide(member: Membership, change: JobChange, *, in_scope: bool = False) -> bool:
    """Whether `member` may approve, reject or apply `change`: what proposing needs, plus
    members.manage for a position, branch or department, payroll.manage for pay, and a new
    branch inside their scope."""
    if not may_propose(member, change.membership, in_scope=in_scope):
        return False
    parts = set(change.parts or [])
    if parts & set(MEMBER_PARTS) and not member.has_perm(Perm.MEMBERS_MANAGE):
        return False
    if "pay" in parts and not member.has_perm(Perm.PAYROLL_MANAGE):
        return False
    if "branch" in parts and change.branch_id is not None:
        allowed = scope.branch_ids(member)
        if allowed is not None and change.branch_id not in allowed:
            return False
    return True


def _ensure_may_propose(person: Membership, by: Membership) -> None:
    if by.pk == person.pk:
        raise DomainError(_("You can't propose a change to your own job."))
    if not may_propose(by, person):
        raise PermissionDenied(_("You don't have permission to do this."))


def _ensure_may_decide(change: JobChange, by: Membership) -> None:
    if by.pk == change.membership_id:
        raise DomainError(_("You can't decide a change to your own job."))
    if not may_decide(by, change):
        raise PermissionDenied(_("You don't have permission to do this."))


# Proposing and deciding ----------------------------------------------------------------------


@transaction.atomic
def propose(
    membership: Membership,
    *,
    by: Membership,
    effective_on: date,
    reason: str,
    position=UNSET,
    branch=UNSET,
    department=UNSET,
    pay_amount=None,
    pay_type: str = "",
    approve: bool = False,
    review: bool = False,
) -> JobChange:
    """Propose a new position, home branch, department and/or pay from `effective_on`. With
    `approve`, someone who may decide it approves it in the same step (otherwise it waits).
    `review`: a performance review's outcome, proposed by its reviewer (apps.lifecycle.reviews
    checked they may); it always waits for someone who may decide it."""
    if not review:
        _ensure_may_propose(membership, by)
    membership = _lock_member(membership)
    if membership.status not in hr_queries.CURRENT:
        raise DomainError(_("Only people who work here can have their job changed."))
    company = membership.company
    today = hr_queries.today(company)
    if not isinstance(effective_on, date):
        raise DomainError(_("Pick the day it starts."))
    if effective_on < today:
        raise DomainError(_("A change starts today or later."))
    if effective_on > today + timedelta(days=MAX_DAYS_AHEAD):
        raise DomainError(_("Pick a day within a year."))
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise DomainError(_("Say why it changes."))
    if len(reason) > MAX_REASON:
        raise DomainError(_("Keep it under %(limit)s characters.") % {"limit": MAX_REASON})

    change = JobChange(
        company_id=company.pk,
        membership=membership,
        effective_on=effective_on,
        reason=reason,
        status=Status.PROPOSED,
        proposed_by=by,
    )
    parts: list[str] = []
    if position is not UNSET:
        if position is not None and (position.company_id != company.pk or not position.is_active):
            raise DomainError(_("Pick a position of this company."))
        if (position.pk if position else None) != membership.position_id:
            parts.append("position")
            change.position = position
    if branch is not UNSET:
        if branch is None:
            raise DomainError(_("Pick the branch they move to."))
        if branch.company_id != company.pk or not branch.is_active:
            raise DomainError(_("Pick a branch of this company."))
        allowed = scope.branch_ids(by)
        if allowed is not None and branch.pk not in allowed:
            raise PermissionDenied(_("You can only move people to the branches you manage."))
        if branch.pk != membership.home_branch_id:
            parts.append("branch")
            change.branch = branch
    if department is not UNSET:
        if department is not None and department.company_id != company.pk:
            raise DomainError(_("Pick a department of this company."))
        if (department.pk if department else None) != membership.department_id:
            parts.append("department")
            change.department = department
    wants_pay = pay_amount not in (None, "") or bool(pay_type)
    if wants_pay and _pay_part(change, by=by, amount=pay_amount, pay_type=pay_type, checked=review):
        parts.append("pay")
    if not parts:
        raise DomainError(_("Nothing changes: pick a new position, branch, department or pay."))
    change.parts = [part for part in PARTS if part in parts]
    _check_overlap(membership, change.parts)
    change.before = snapshot(membership, on=effective_on)
    change.after = _target(change, change.before)
    change.save()
    _audit(LifecycleAction.CHANGE_PROPOSED, change, by, **_shown(change))
    if approve and not review and may_decide(by, change):
        _approve(change, by=by)
    else:
        transaction.on_commit(partial(tasks.notify_change_proposed.delay, change.pk))
    bump(change.company_id, queue=True)
    return change


def _pay_part(
    change: JobChange, *, by: Membership, amount, pay_type: str, checked: bool = False
) -> bool:
    """Fill the pay of `change`; False when it is the pay they already have. `checked`: the
    caller checked who proposes it (a review's raise)."""
    membership = change.membership
    company = membership.company
    if not integrations.payroll_on(company):
        raise DomainError(_("Payroll is off for this company, so the pay can't change here."))
    if not checked and not by.has_perm(Perm.PAYROLL_MANAGE):
        raise PermissionDenied(_("Only people who manage pay can change someone's pay."))
    current = integrations.current_pay(membership, on=change.effective_on)
    pay_type = pay_type or (current["pay_type"] if current else "monthly")
    if pay_type not in integrations.pay_types():
        raise DomainError(_("Pick how the pay is counted."))
    if amount in (None, ""):
        if current is None:
            raise DomainError(_("Enter the new pay."))
        amount = current["amount"]
    try:
        amount = Decimal(str(amount).strip().replace(" ", "").replace(",", ".")).quantize(
            Decimal("0.01")
        )
    except InvalidOperation, ValueError:
        raise DomainError(_("Enter an amount of money.")) from None
    if not amount.is_finite() or amount <= 0:
        raise DomainError(_("Enter an amount of money."))
    currency = current["currency"] if current else integrations.payroll_currency(company)
    if current is not None and (
        Decimal(current["amount"]) == amount and current["pay_type"] == pay_type
    ):
        return False
    change.pay_amount = amount
    change.pay_type = pay_type
    change.pay_currency = currency
    return True


@transaction.atomic
def approve(change: JobChange, *, by: Membership) -> JobChange:
    """Approve a proposed change: it applies on its day (at once when that is today)."""
    change = _lock(change)
    _ensure_may_decide(change, by)
    if change.status != Status.PROPOSED:
        raise DomainError(_("Only a change waiting for approval can be approved."))
    _approve(change, by=by)
    bump(change.company_id, queue=True)
    return change


def _approve(change: JobChange, *, by: Membership) -> None:
    change.status = Status.APPROVED
    change.decided_by = by
    change.decided_at = timezone.now()
    change.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    inbox.settle(change, outcome=gettext_lazy("Approved"), by=by, kind=REQUEST_KIND)
    _audit(
        LifecycleAction.CHANGE_APPROVED, change, by, effective_on=change.effective_on.isoformat()
    )
    if change.proposed_by_id and change.proposed_by_id != by.pk:
        transaction.on_commit(partial(tasks.notify_change_decided.delay, change.pk))
    if change.effective_on <= hr_queries.today(change.company):
        _apply(change, actor=by)


@transaction.atomic
def reject(change: JobChange, *, by: Membership, reason: str) -> JobChange:
    """Turn a proposed change down, with the reason the proposer reads."""
    change = _lock(change)
    _ensure_may_decide(change, by)
    if change.status != Status.PROPOSED:
        raise DomainError(_("Only a change waiting for approval can be rejected."))
    reason = " ".join(str(reason or "").split())[:300]
    if not reason:
        raise DomainError(_("Say why it is rejected."))
    change.status = Status.REJECTED
    change.decided_by = by
    change.decided_at = timezone.now()
    change.decision_note = reason
    change.save()
    inbox.settle(change, outcome=gettext_lazy("Rejected"), by=by, kind=REQUEST_KIND)
    _audit(LifecycleAction.CHANGE_REJECTED, change, by)
    if change.proposed_by_id and change.proposed_by_id != by.pk:
        transaction.on_commit(partial(tasks.notify_change_decided.delay, change.pk))
    bump(change.company_id, queue=True)
    return change


@transaction.atomic
def cancel(change: JobChange, *, by: Membership, reason: str = "") -> JobChange:
    """Call off a change before it applies: whoever proposed it, or someone who may decide."""
    change = _lock(change)
    if change.status not in OPEN:
        raise DomainError(_("Only a change that hasn't taken effect can be cancelled."))
    proposer = change.proposed_by_id == by.pk and may_propose(by, change.membership)
    if not proposer:
        _ensure_may_decide(change, by)
    was = change.status
    change.status = Status.CANCELLED
    change.decision_note = " ".join(str(reason or "").split())[:300]
    change.error = ""
    change.save()
    inbox.settle(change, outcome=pgettext_lazy("job change", "Cancelled"), by=by, kind=REQUEST_KIND)
    _audit(LifecycleAction.CHANGE_CANCELLED, change, by)
    if change.proposed_by_id and change.proposed_by_id != by.pk:
        transaction.on_commit(partial(tasks.notify_change_decided.delay, change.pk))
    bump(change.company_id, queue=was == Status.PROPOSED)
    return change


def cancel_for_leaver(change: JobChange) -> None:
    """The person left: a change still to come can't apply (inside the caller's transaction)."""
    change.status = Status.CANCELLED
    change.decision_note = str(_("They left before it took effect."))[:300]
    change.error = ""
    change.save()
    inbox.settle(change, outcome=pgettext_lazy("job change", "Cancelled"), kind=REQUEST_KIND)
    _audit(LifecycleAction.CHANGE_CANCELLED, change, None, left=True)
    bump(change.company_id, queue=True)


# Applying ------------------------------------------------------------------------------------


def apply(change: JobChange, *, by: Membership | None = None) -> JobChange:
    """Make an approved change now, as `by` (someone who may decide it: "Try again") or else
    as the one who approved it (the job on its day). Raises on a refusal; nothing changes then."""
    with transaction.atomic():
        change = _lock(change)
        if change.status != Status.APPROVED:
            raise DomainError(_("Only an approved change can take effect."))
        if by is not None:
            _ensure_may_decide(change, by)
        _apply(change, actor=by or change.decided_by)
        bump(change.company_id)
    return change


def _apply(change: JobChange, *, actor: Membership | None) -> None:
    from apps.members import services as members

    if actor is not None:
        actor = (
            Membership.objects.select_related("company", "role", "user").filter(pk=actor.pk).first()
        )
    if actor is None or actor.status != Membership.Status.APPROVED:
        raise DomainError(
            _("Whoever approved it no longer works here: someone who may should apply it.")
        )
    if not may_decide(actor, change):
        raise PermissionDenied(
            _("%(name)s may no longer make this change: someone who may should apply it.")
            % {"name": actor}
        )
    membership = _lock_member(change.membership)
    if membership.status not in hr_queries.CURRENT:
        raise DomainError(_("They no longer work here."))
    parts = set(change.parts or [])
    before = snapshot(membership, on=change.effective_on)
    fields: dict = {}
    if "position" in parts:
        if change.position_id is None and (change.after or {}).get("position"):
            raise DomainError(_("The new position was removed: cancel this change."))
        fields["position"] = change.position
    if "department" in parts:
        if change.department_id is None and (change.after or {}).get("department"):
            raise DomainError(_("The new department was removed: cancel this change."))
        fields["department"] = change.department
    if "branch" in parts:
        branch = change.branch
        if branch is None or not branch.is_active:
            raise DomainError(_("The branch they move to is closed: cancel this change."))
        current = list(membership.branches.all())
        fields["branches"] = [b for b in current if b.pk != membership.home_branch_id] + [branch]
        fields["home_branch"] = branch
    if fields:
        members.update_member(membership, by=actor, **fields)
    reason = change.reason[:300]
    if "position" in parts:
        integrations.amend_contract_position(
            membership,
            by=actor,
            position=change.position,
            effective_on=change.effective_on,
            reason=reason,
        )
    if "pay" in parts:
        integrations.propose_pay_change(
            membership,
            by=actor,
            setup={"amount": change.pay_amount, "pay_type": change.pay_type},
            effective_on=change.effective_on,
            reason=reason,
        )
    membership = (
        Membership.objects.select_related("position", "home_branch", "department", "role")
        .prefetch_related("branches")
        .get(pk=membership.pk)
    )
    change.membership = membership
    change.before = before
    change.after = snapshot(membership, on=change.effective_on)
    change.status = Status.APPLIED
    change.applied_at = timezone.now()
    change.error = ""
    change.save()
    details = _shown(change)
    if before.get("role") != change.after.get("role"):
        details["role"] = [
            (before.get("role") or {}).get("name"),
            (change.after.get("role") or {}).get("name"),
        ]
    _audit(LifecycleAction.CHANGE_APPLIED, change, actor, **details)
    transaction.on_commit(partial(tasks.notify_change_applied.delay, change.pk))


def apply_due(now: datetime | None = None) -> int:
    """The job (every 15 minutes): apply every approved change whose day has come in its
    company's time. Idempotent: an applied change is left alone, a refused one waits for
    "Try again". Returns how many were applied."""
    now = now or timezone.now()
    rows = (
        JobChange.objects.filter(
            status=Status.APPROVED,
            error="",
            effective_on__lte=timezone.localtime(now).date() + timedelta(days=1),
            company__is_active=True,
        )
        .select_related("company")
        .order_by("effective_on", "pk")
    )
    applied = 0
    for change in rows:
        if change.effective_on > hr_queries.today(change.company, now):
            continue
        try:
            apply(change)
        except (DomainError, PermissionDenied) as exc:
            _failed(change, exc)
        else:
            applied += 1
    return applied


def _failed(change: JobChange, exc: Exception) -> None:
    message = str(getattr(exc, "message", None) or exc)[:300] or _("It couldn't take effect.")
    updated = JobChange.objects.filter(pk=change.pk, status=Status.APPROVED, error="").update(
        error=message, updated_at=timezone.now()
    )
    if updated:
        audit.record(
            LifecycleAction.CHANGE_FAILED,
            company_id=change.company_id,
            actor=None,
            target=change.membership,
            required_perm=Perm.HR_VIEW,
            change=change.pk,
        )
        transaction.on_commit(partial(tasks.notify_change_failed.delay, change.pk))
        bump(change.company_id)


# Shapes --------------------------------------------------------------------------------------


def _ref(row) -> dict | None:
    return {"id": row.pk, "name": row.name} if row is not None else None


def snapshot(membership: Membership, *, on: date) -> dict:
    """What the person's job is: position, home branch, branches, department and role (each
    {id, name}), and the pay in force on `on` (None without payroll)."""
    branches = sorted(membership.branches.all(), key=lambda branch: (branch.order, branch.pk))
    return {
        "position": _ref(membership.position),
        "branch": _ref(membership.home_branch),
        "branches": [_ref(branch) for branch in branches],
        "department": _ref(membership.department),
        "role": _ref(membership.role),
        "pay": integrations.current_pay(membership, on=on),
    }


LIVE = ("position", "branch", "department", "role")


def live_names(changes) -> dict[tuple[str, int], str]:
    """The names positions, branches, departments and roles in `changes` have now (one was
    renamed since: the history reads today's name), by (kind, id)."""
    from apps.companies.models import Branch
    from apps.members.models import AccessRole, Department, Position

    ids: dict[str, set[int]] = {kind: set() for kind in LIVE}
    for change in changes:
        for side in (change.before or {}, change.after or {}):
            for kind in LIVE:
                ref = side.get(kind)
                if isinstance(ref, dict) and ref.get("id"):
                    ids[kind].add(ref["id"])
            for ref in side.get("branches") or []:
                if isinstance(ref, dict) and ref.get("id"):
                    ids["branch"].add(ref["id"])
    models = {"position": Position, "branch": Branch, "department": Department, "role": AccessRole}
    names = {}
    for kind, model in models.items():
        if ids[kind]:
            for pk, name in model.objects.filter(pk__in=ids[kind]).values_list("pk", "name"):
                names[(kind, pk)] = name
    return names


def _target(change: JobChange, before: dict) -> dict:
    after = dict(before)
    parts = set(change.parts)
    if "position" in parts:
        after["position"] = _ref(change.position)
    if "branch" in parts:
        after["branch"] = _ref(change.branch)
    if "department" in parts:
        after["department"] = _ref(change.department)
    if "pay" in parts:
        after["pay"] = {
            "amount": f"{change.pay_amount:.2f}",
            "currency": change.pay_currency,
            "pay_type": change.pay_type,
        }
    return after


def _shown(change: JobChange) -> dict:
    """The audit details: the day and the parts by name, never the pay."""
    details = {"change": change.pk, "effective_on": change.effective_on.isoformat()}
    for part in ("position", "branch", "department"):
        if part in change.parts:
            was = (change.before or {}).get(part) or {}
            now = (change.after or {}).get(part) or {}
            details[part] = [was.get("name"), now.get("name")]
    if "pay" in change.parts:
        details["pay"] = True
    return details


def _check_overlap(membership: Membership, parts: list[str]) -> None:
    for other in JobChange.objects.filter(membership=membership, status__in=OPEN):
        shared = [part for part in parts if part in (other.parts or [])]
        if shared:
            raise DomainError(
                _("A change from %(date)s already waits for them: cancel it or change that one.")
                % {"date": other.effective_on.strftime("%d.%m.%Y")}
            )


def _lock(change: JobChange) -> JobChange:
    return (
        JobChange.objects.select_for_update(of=("self",))
        .select_related(
            "membership__company",
            "membership__role",
            "membership__user",
            "company",
            "position",
            "branch",
            "department",
            "decided_by__role",
            "decided_by__company",
        )
        .get(pk=change.pk)
    )


def _lock_member(membership: Membership) -> Membership:
    return (
        Membership.objects.select_for_update(of=("self",))
        .select_related("company", "role", "user", "position", "home_branch", "department")
        .get(pk=membership.pk)
    )


def _audit(action: str, row: JobChange, by: Membership | None, /, **details) -> None:
    details.setdefault("change", row.pk)
    audit.record(
        action,
        company_id=row.company_id,
        actor=by.user if by is not None else None,
        target=row.membership,
        required_perm=Perm.HR_VIEW,
        **details,
    )


def bump(company_id: int, *, queue: bool = False) -> None:
    keys = (PULSE, QUEUE) if queue else (PULSE,)
    transaction.on_commit(partial(pulse.bump, company_id, *keys))
