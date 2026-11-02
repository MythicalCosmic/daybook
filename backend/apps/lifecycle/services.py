"""Business logic of the people lifecycle: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

Disciplinary records are given by holders of `hr.discipline` who reach the person (their
branch scope), never to themselves, and an owner only by an owner. The person reads their
record in the mini app, confirms they were told, and may write an explanation. Suspensions
are `members.services.suspend/reinstate`, used as they are.
"""

from datetime import date, timedelta
from decimal import Decimal
from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core import uploads
from apps.core.exceptions import DomainError
from apps.core.storage import private_storage
from apps.hr import queries as hr_queries
from apps.lifecycle import integrations, tasks
from apps.lifecycle.audit_actions import LifecycleAction
from apps.lifecycle.models import DisciplinaryRecord
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

DISCIPLINE = "lifecycle.discipline"
Kind = DisciplinaryRecord.Kind
# How long a record counts by default, in months (none: until withdrawn).
EXPIRES_AFTER_MONTHS = {
    Kind.VERBAL_WARNING: 3,
    Kind.WRITTEN_WARNING: 6,
    Kind.FINAL_WARNING: 12,
    Kind.REPRIMAND: 12,
}
MAX_TEXT = 2000
EVIDENCE_TYPES = ("pdf", "image")
EDITABLE = ("kind", "category", "incident_on", "issued_on", "description", "expires_on")
UNSET = object()


def default_expiry(kind: str, issued_on: date) -> date | None:
    months = EXPIRES_AFTER_MONTHS.get(kind)
    if months is None:
        return None
    month = issued_on.month - 1 + months
    year, month = issued_on.year + month // 12, month % 12 + 1
    for day in (issued_on.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return issued_on + timedelta(days=30 * months)


@transaction.atomic
def issue(
    membership: Membership,
    *,
    by: Membership,
    kind: str,
    category: str,
    description: str,
    incident_on: date | None = None,
    issued_on: date | None = None,
    expires_on=UNSET,
    evidence=None,
    fine_amount: Decimal | None = None,
) -> DisciplinaryRecord:
    """Give `membership` a warning or a reprimand. With `fine_amount`, a fine is proposed in
    payroll for the same reason (payroll approves it); without payroll the whole thing is
    refused, so HR can give the warning alone."""
    _ensure_may_discipline(membership, by)
    if membership.status not in hr_queries.CURRENT:
        raise DomainError(_("Only people who work here can be given a warning."))
    today = hr_queries.today(membership.company)
    record = DisciplinaryRecord(
        company_id=membership.company_id,
        membership=membership,
        issued_by=by,
        issued_on=issued_on or today,
    )
    values = _clean(
        record,
        {
            "kind": kind,
            "category": category,
            "description": description,
            "incident_on": incident_on or issued_on or today,
        },
        today,
    )
    for name, value in values.items():
        setattr(record, name, value)
    record.expires_on = (
        default_expiry(record.kind, record.issued_on) if expires_on is UNSET else expires_on
    )
    _check_expiry(record)
    if evidence is not None:
        _attach(record, evidence)
    record.save()
    if fine_amount is not None:
        _propose_fine(record, by=by, amount=fine_amount)
    _audit(LifecycleAction.RECORD_ISSUED, record, by)
    transaction.on_commit(partial(tasks.notify_record_issued.delay, record.pk))
    bump(record.company_id)
    return record


@transaction.atomic
def update(record: DisciplinaryRecord, *, by: Membership, evidence=None, **fields):
    _ensure_may_discipline(record.membership, by)
    record = _lock(record)
    if record.status == DisciplinaryRecord.Status.WITHDRAWN:
        raise DomainError(_("This record was withdrawn."))
    today = hr_queries.today(record.company)
    values = _clean(record, {k: v for k, v in fields.items() if k in EDITABLE}, today)
    changed = [name for name, value in values.items() if getattr(record, name) != value]
    for name in changed:
        setattr(record, name, values[name])
    if "kind" in changed and "expires_on" not in fields:
        record.expires_on = default_expiry(record.kind, record.issued_on)
    _check_expiry(record)
    old = record.evidence.name if record.evidence else ""
    if evidence is not None:
        _attach(record, evidence)
        changed.append("evidence")
    if not changed:
        return record
    record.save()
    if "evidence" in changed and old:
        transaction.on_commit(partial(private_storage.delete, old))
    _audit(LifecycleAction.RECORD_CHANGED, record, by, fields=sorted(changed))
    bump(record.company_id)
    return record


@transaction.atomic
def withdraw(record: DisciplinaryRecord, *, by: Membership, reason: str) -> DisciplinaryRecord:
    """Take a record back (given in error, or set aside): it stays on file, marked."""
    _ensure_may_discipline(record.membership, by)
    record = _lock(record)
    if record.status == DisciplinaryRecord.Status.WITHDRAWN:
        raise DomainError(_("This record was withdrawn."))
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise DomainError(_("Say why the record is withdrawn."))
    record.status = DisciplinaryRecord.Status.WITHDRAWN
    record.withdrawn_at = timezone.now()
    record.withdrawn_by = by.user
    record.withdraw_reason = reason[:300]
    record.save(
        update_fields=["status", "withdrawn_at", "withdrawn_by", "withdraw_reason", "updated_at"]
    )
    _audit(LifecycleAction.RECORD_WITHDRAWN, record, by)
    bump(record.company_id)
    return record


@transaction.atomic
def delete(record: DisciplinaryRecord, *, by: Membership) -> None:
    """A record given by mistake goes, while the person hasn't seen it and no fine came of
    it; otherwise it is withdrawn instead."""
    _ensure_may_discipline(record.membership, by)
    record = _lock(record)
    if record.read_at or record.acknowledged_at or record.employee_response or record.fine_id:
        raise DomainError(_("The person has seen this record: withdraw it instead."))
    name = record.evidence.name if record.evidence else ""
    _audit(LifecycleAction.RECORD_REMOVED, record, by)
    record.delete()
    if name:
        transaction.on_commit(partial(private_storage.delete, name))
    bump(record.company_id)


@transaction.atomic
def propose_fine(
    record: DisciplinaryRecord, *, by: Membership, amount: Decimal
) -> DisciplinaryRecord:
    """Propose the fine that goes with a record given earlier (one per record)."""
    _ensure_may_discipline(record.membership, by)
    record = _lock(record)
    if record.status == DisciplinaryRecord.Status.WITHDRAWN:
        raise DomainError(_("This record was withdrawn."))
    _propose_fine(record, by=by, amount=amount)
    _audit(LifecycleAction.FINE_PROPOSED, record, by)
    bump(record.company_id)
    return record


def _propose_fine(record: DisciplinaryRecord, *, by: Membership, amount: Decimal) -> None:
    if record.fine_id:
        raise DomainError(_("A fine was already proposed for this record."))
    if amount is None or amount <= 0:
        raise DomainError(_("Give the fine's amount."))
    reason = f"{record.get_kind_display()}: {record.get_category_display()}"
    fine = integrations.propose_fine(
        record.membership, by=by, amount=amount, reason=reason[:300], source="discipline"
    )
    record.fine_id = fine.pk
    record.save(update_fields=["fine_id", "updated_at"])


# The person themselves ----------------------------------------------------------------------


@transaction.atomic
def mark_read(record: DisciplinaryRecord, *, by: Membership) -> DisciplinaryRecord:
    """The person opened their record."""
    record = _own(record, by)
    if record.read_at is None:
        record.read_at = timezone.now()
        record.save(update_fields=["read_at", "updated_at"])
        bump(record.company_id)
    return record


@transaction.atomic
def acknowledge(record: DisciplinaryRecord, *, by: Membership) -> DisciplinaryRecord:
    """The person confirms they were told (it isn't agreeing: they can still explain)."""
    record = _own(record, by)
    if record.status == DisciplinaryRecord.Status.WITHDRAWN:
        raise DomainError(_("This record was withdrawn."))
    if record.acknowledged_at is None:
        now = timezone.now()
        record.acknowledged_at = now
        record.read_at = record.read_at or now
        record.status = DisciplinaryRecord.Status.ACKNOWLEDGED
        record.save(update_fields=["acknowledged_at", "read_at", "status", "updated_at"])
        _audit(LifecycleAction.RECORD_ACKNOWLEDGED, record, by)
        bump(record.company_id)
    return record


@transaction.atomic
def explain(record: DisciplinaryRecord, *, by: Membership, text: str) -> DisciplinaryRecord:
    """The person's explanation (they can rewrite it while the record stands). The one who
    gave the record hears about it."""
    record = _own(record, by)
    if record.status == DisciplinaryRecord.Status.WITHDRAWN:
        raise DomainError(_("This record was withdrawn."))
    text = str(text or "").strip()
    if not text:
        raise DomainError(_("Write your explanation."))
    if len(text) > MAX_TEXT:
        raise DomainError(_("Keep it under 2000 characters."))
    record.employee_response = text
    record.responded_at = timezone.now()
    record.read_at = record.read_at or record.responded_at
    record.save(update_fields=["employee_response", "responded_at", "read_at", "updated_at"])
    _audit(LifecycleAction.RECORD_EXPLAINED, record, by)
    transaction.on_commit(partial(tasks.notify_explanation.delay, record.pk))
    bump(record.company_id)
    return record


# Helpers -------------------------------------------------------------------------------------


def may_discipline(member: Membership, person: Membership, *, in_scope: bool = False) -> bool:
    """Whether `member` may give `person` a record: hr.discipline, the person in their branch
    scope, not themselves, and an owner only if they are one. `in_scope`: the caller already
    limited the people to `member`'s branch scope."""
    if member.company_id != person.company_id or member.pk == person.pk:
        return False
    if not member.has_perm(Perm.HR_DISCIPLINE):
        return False
    if person.role is not None and person.role.is_owner and not member.role.is_owner:
        return False
    if in_scope:
        return True
    return (
        hr_queries.person(person.company, person.pk, branch_ids=scope.branch_ids(member))
        is not None
    )


def _ensure_may_discipline(person: Membership, by: Membership) -> None:
    if by.pk == person.pk:
        raise DomainError(_("You can't give yourself a warning."))
    if not may_discipline(by, person):
        raise PermissionDenied(_("You don't have permission to do this."))


def _own(record: DisciplinaryRecord, by: Membership) -> DisciplinaryRecord:
    record = _lock(record)
    if record.membership_id != by.pk:
        raise PermissionDenied(_("You don't have permission to do this."))
    return record


def _clean(record: DisciplinaryRecord, fields: dict, today: date) -> dict:
    clean = dict(fields)
    if "kind" in clean and clean["kind"] not in DisciplinaryRecord.Kind.values:
        raise DomainError(_("Pick what kind of record it is."))
    if "category" in clean and clean["category"] not in DisciplinaryRecord.Category.values:
        raise DomainError(_("Pick what it is about."))
    if "description" in clean:
        text = str(clean["description"] or "").strip()
        if not text:
            raise DomainError(_("Write what happened."))
        if len(text) > MAX_TEXT:
            raise DomainError(_("Keep it under 2000 characters."))
        clean["description"] = text
    incident = clean.get("incident_on", record.incident_on)
    issued = clean.get("issued_on", record.issued_on)
    if issued and issued > today:
        raise DomainError(_("A record can't be given in the future."))
    if incident and incident > today:
        raise DomainError(_("What happened can't be in the future."))
    if incident and issued and incident > issued:
        raise DomainError(_("It can't have happened after the record was given."))
    return clean


def _check_expiry(record: DisciplinaryRecord) -> None:
    if record.expires_on is not None and record.expires_on < record.issued_on:
        raise DomainError(_("A record can't stop counting before it was given."))


def _attach(record: DisciplinaryRecord, file) -> None:
    content = uploads.accept_document(file, allowed=EVIDENCE_TYPES)
    record.evidence.save(content.name, content, save=False)


def _lock(record: DisciplinaryRecord) -> DisciplinaryRecord:
    return (
        DisciplinaryRecord.objects.select_for_update(of=("self",))
        .select_related("membership__company", "membership__role", "company")
        .get(pk=record.pk)
    )


def _audit(action: str, record: DisciplinaryRecord, by: Membership | None, **details) -> None:
    # The person's file: on their membership, with what kind of record it is (never the text).
    audit.record(
        action,
        company_id=record.company_id,
        actor=by.user if by else None,
        target=record.membership,
        required_perm=Perm.HR_VIEW,
        record=record.pk,
        kind=record.kind,
        category=record.category,
        **details,
    )


def bump(company_id: int) -> None:
    transaction.on_commit(partial(pulse.bump, company_id, DISCIPLINE))
