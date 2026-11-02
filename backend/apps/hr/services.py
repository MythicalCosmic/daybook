"""Business logic of HR records: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

Who may do what: `hr.manage` edits anyone's profile and documents in their branch scope (ID
numbers are write-only for them: reading one back needs `hr.sensitive`, and every such read
is audited); a person edits a few fields of their own profile and adds their own documents.
"""

from datetime import date, timedelta
from functools import partial
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core import uploads
from apps.core.exceptions import DomainError
from apps.core.storage import private_storage
from apps.hr import conf, ids, printing, queries, tasks
from apps.hr.audit_actions import HRAction
from apps.hr.models import (
    TERM_KINDS,
    Contract,
    ContractKind,
    ContractTemplate,
    DocumentKind,
    DocumentLevel,
    EmergencyContact,
    EmployeeDocument,
    EmployeeProfile,
    HRSettings,
    RequiredDocument,
)
from apps.members import scope
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

PEOPLE = "hr.people"
DOCUMENTS = "hr.documents"
EXPIRING = "hr.expiring"
REQUIRED = "hr.required"
SETTINGS = "hr.settings"
CONTRACTS = "hr.contracts"
TEMPLATES = "hr.templates"

SETTINGS_FIELDS = (
    "document_warn_days",
    "contract_warn_days",
    "probation_warn_days",
    "celebrations_enabled",
    "celebrate_anniversaries",
    "employer_name",
    "employer_tin",
)
# What hr.manage edits on a profile; the secret ones go in encrypted and never come back out
# (only masked) without hr.sensitive.
PROFILE_FIELDS = (
    "employee_number",
    "middle_name",
    "birth_date",
    "show_birthday",
    "gender",
    "hire_date",
    "employment_type",
    "personal_phone",
    "email",
    "address",
    "city",
    "tin",
    "payout_method",
)
SECRET_FIELDS = ("pinfl", "passport", "payout_card", "notes")
# Only for someone who has left: corrections of how and when.
FORMER_FIELDS = ("terminated_on", "termination_reason", "termination_note")
# What a person changes on their own profile in the mini app.
OWN_FIELDS = ("personal_phone", "email", "address", "city", "show_birthday", "payout_card")
DOCUMENT_FIELDS = (
    "kind",
    "title",
    "number",
    "issued_on",
    "expires_on",
    "level",
    "specialty",
    "issuer",
    "visible_to_employee",
)
# A change to any of these needs the document checked again.
VERIFIED_FIELDS = ("kind", "number", "issued_on", "expires_on", "level", "file")
DIPLOMA_LEVELS = (DocumentLevel.HIGHER, DocumentLevel.COLLEGE)
CATEGORY_LEVELS = (DocumentLevel.HIGHEST, DocumentLevel.FIRST, DocumentLevel.SECOND)
DIPLOMA_KINDS = (DocumentKind.DIPLOMA, DocumentKind.PHARMACY_DIPLOMA, DocumentKind.MEDICAL_DIPLOMA)
# Numbers in the passport format (series and seven digits).
PASSPORT_KINDS = (DocumentKind.PASSPORT, DocumentKind.ID_CARD)
# The offboarding wizard's reasons (members.services.OFFBOARD_REASONS) as the profile keeps them.
LEAVING_REASONS = {
    "resignation": EmployeeProfile.TerminationReason.RESIGNED,
    "dismissal": EmployeeProfile.TerminationReason.DISMISSED,
    "contract_end": EmployeeProfile.TerminationReason.CONTRACT_ENDED,
    "probation_failed": EmployeeProfile.TerminationReason.PROBATION_FAILED,
}
EARLIEST_BIRTH = date(1920, 1, 1)
DOCUMENT_TYPES = ("pdf", "image")


# Settings -------------------------------------------------------------------------------


@transaction.atomic
def update_settings(company, *, by: Membership | None, **fields) -> HRSettings:
    _ensure(by, Perm.HR_MANAGE)
    row = HRSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    changes = {}
    for name in SETTINGS_FIELDS:
        if name in fields and getattr(row, name) != fields[name]:
            changes[name] = [getattr(row, name), fields[name]]
            setattr(row, name, fields[name])
    if changes:
        row.save()
        audit.record(
            HRAction.SETTINGS_CHANGED,
            company_id=company.pk,
            actor=by.user if by else None,
            target=row,
            changes=changes,
        )
        bump(company.pk, SETTINGS, EXPIRING)
    return row


# Profiles -------------------------------------------------------------------------------


def hired(membership: Membership) -> EmployeeProfile:
    """`member_approved`: the person's profile, hired today. Someone coming back starts a new
    stint: today is their hire date again and their last one is cleared."""
    day = queries.today(membership.company)
    profile, created = EmployeeProfile.objects.get_or_create(
        membership=membership, defaults={"company_id": membership.company_id, "hire_date": day}
    )
    if not created:
        profile.hire_date = day
        profile.terminated_on = None
        profile.termination_reason = ""
        profile.termination_note = ""
        profile.save(
            update_fields=[
                "hire_date",
                "terminated_on",
                "termination_reason",
                "termination_note",
                "updated_at",
            ]
        )
    bump(membership.company_id, PEOPLE)
    return profile


@transaction.atomic
def left(membership: Membership, *, terminated_on: date | None, details: dict | None) -> None:
    """`member_left`: their last day and why go on their profile (when they have one), and
    their contract in force ends that day (it ran out, or it was terminated)."""
    wizard = (details or {}).get("members") or {}
    last_day = terminated_on or queries.today(membership.company)
    reason = LEAVING_REASONS.get(wizard.get("reason"), EmployeeProfile.TerminationReason.OTHER)
    note = str(wizard.get("note") or "")[:1000]
    profile = EmployeeProfile.objects.filter(membership=membership).first()
    if profile is not None:
        profile.terminated_on = last_day
        profile.termination_reason = reason
        profile.termination_note = note
        profile.save(
            update_fields=["terminated_on", "termination_reason", "termination_note", "updated_at"]
        )
    contract = (
        Contract.objects.select_for_update()
        .filter(membership=membership, status=Contract.Status.ACTIVE)
        .first()
    )
    if contract is not None:
        with translation.override(membership.company.default_language):
            why = note or str(EmployeeProfile.TerminationReason(reason).label)
        status = (
            Contract.Status.ENDED
            if reason == EmployeeProfile.TerminationReason.CONTRACT_ENDED
            else Contract.Status.TERMINATED
        )
        _close(contract, status, max(last_day, contract.starts_on), why, by=None)
    bump(membership.company_id, PEOPLE, EXPIRING)


def ensure_profile(membership: Membership) -> EmployeeProfile:
    """The person's profile, made (with their hire date) if they have none yet."""
    profile = queries.profile_of(membership)
    if profile.pk is None:
        try:
            with transaction.atomic():
                profile.save()
        except IntegrityError:
            profile = EmployeeProfile.objects.get(membership=membership)
    return profile


@transaction.atomic
def update_profile(membership: Membership, *, by: Membership, **fields) -> EmployeeProfile:
    """HR's edit of someone's profile (`hr.manage`)."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(membership, by)
    allowed = PROFILE_FIELDS + SECRET_FIELDS + FORMER_FIELDS
    return _save_profile(membership, by, {k: v for k, v in fields.items() if k in allowed})


@transaction.atomic
def update_own_profile(membership: Membership, **fields) -> EmployeeProfile:
    """What a person changes on their own profile: contacts, address, birthday shown or not,
    and the card their pay goes to."""
    return _save_profile(
        membership, membership, {k: v for k, v in fields.items() if k in OWN_FIELDS}
    )


def _save_profile(membership: Membership, by: Membership, fields: dict) -> EmployeeProfile:
    ensure_profile(membership)
    profile = EmployeeProfile.objects.select_for_update().get(membership=membership)
    fields = _clean_profile(profile, membership, fields)
    changes, secrets = {}, []
    for name, value in fields.items():
        if getattr(profile, name) == value:
            continue
        if name in SECRET_FIELDS:
            secrets.append(name)
        else:
            changes[name] = [audit.plain(getattr(profile, name)), audit.plain(value)]
        setattr(profile, name, value)
    if not changes and not secrets:
        return profile
    try:
        with transaction.atomic():
            profile.save()
    except IntegrityError as exc:
        if "hr_unique_pinfl" in str(exc):
            raise DomainError(_("Someone else in the company has this PINFL.")) from exc
        raise DomainError(_("Someone else in the company has this employee number.")) from exc
    details = {"changes": changes} if changes else {}
    if secrets:
        details["fields"] = secrets
    _audit(HRAction.PROFILE_CHANGED, membership, by, **details)
    bump(membership.company_id, PEOPLE)
    return profile


def _clean_profile(profile: EmployeeProfile, membership: Membership, fields: dict) -> dict:
    today = queries.today(membership.company)
    clean = {}
    for name, value in fields.items():
        match name:
            case "pinfl":
                value = ids.pinfl(value)
            case "passport":
                value = ids.passport(value)
            case "payout_card":
                value = ids.card(value)
            case "tin":
                value = ids.tin(value)
            case "personal_phone":
                value = ids.phone(value)
            case "employee_number" | "middle_name" | "address" | "city" | "termination_note":
                value = " ".join(str(value or "").split())
            case "notes":
                value = str(value or "").strip()
            case "birth_date" if value is not None:
                if value > today or value < EARLIEST_BIRTH:
                    raise DomainError(_("Check the date of birth."))
            case "hire_date" if value is not None and value > today:
                raise DomainError(_("The hire date can't be in the future."))
            case "terminated_on" | "termination_reason":
                if membership.status not in queries.GONE and value not in (None, ""):
                    raise DomainError(_("Only someone who has left has a last day."))
        clean[name] = value
    hire = clean.get("hire_date", profile.hire_date)
    end = clean.get("terminated_on", profile.terminated_on)
    if hire and end and end < hire:
        raise DomainError(_("The last day can't be before the hire date."))
    if clean.get("payout_method") == EmployeeProfile.PayoutMethod.CARD and not clean.get(
        "payout_card", profile.payout_card
    ):
        raise DomainError(_("Add the card number to pay to a card."))
    return clean


def reveal(membership: Membership, *, by: Membership) -> EmployeeProfile:
    """Someone's profile with its ID and card numbers readable, for a holder of
    `hr.sensitive`. Every reveal is audited."""
    _ensure(by, Perm.HR_SENSITIVE)
    _ensure_reach(membership, by)
    profile = queries.profile_of(membership)
    _audit(HRAction.SENSITIVE_VIEWED, membership, by, required_perm=Perm.HR_SENSITIVE)
    return profile


# Emergency contacts ---------------------------------------------------------------------


@transaction.atomic
def add_contact(
    membership: Membership, *, by: Membership, name: str, phone: str, relation: str = ""
) -> EmergencyContact:
    _ensure_own_or(membership, by, Perm.HR_MANAGE)
    ensure_profile(membership)
    profile = EmployeeProfile.objects.select_for_update().get(membership=membership)
    if profile.emergency_contacts.count() >= EmergencyContact.MAX_PER_PERSON:
        raise DomainError(_("Three emergency contacts at most."))
    contact = EmergencyContact.objects.create(
        company_id=membership.company_id, profile=profile, **_clean_contact(name, phone, relation)
    )
    _audit(HRAction.CONTACT_ADDED, membership, by, contact=contact.pk)
    bump(membership.company_id, PEOPLE)
    return contact


@transaction.atomic
def update_contact(contact: EmergencyContact, *, by: Membership, **fields) -> EmergencyContact:
    membership = contact.profile.membership
    _ensure_own_or(membership, by, Perm.HR_MANAGE)
    values = _clean_contact(
        fields.get("name", contact.name),
        fields.get("phone", contact.phone),
        fields.get("relation", contact.relation),
    )
    for name, value in values.items():
        setattr(contact, name, value)
    contact.save()
    _audit(HRAction.CONTACT_CHANGED, membership, by, contact=contact.pk)
    bump(membership.company_id, PEOPLE)
    return contact


@transaction.atomic
def remove_contact(contact: EmergencyContact, *, by: Membership) -> None:
    membership = contact.profile.membership
    _ensure_own_or(membership, by, Perm.HR_MANAGE)
    _audit(HRAction.CONTACT_REMOVED, membership, by, contact=contact.pk)
    contact.delete()
    bump(membership.company_id, PEOPLE)


def _clean_contact(name: str, phone: str, relation: str) -> dict:
    name = " ".join(str(name or "").split())
    if not name:
        raise DomainError(_("Write the contact's name."))
    return {
        "name": name[:150],
        "phone": ids.phone(phone, required=True),
        "relation": " ".join(str(relation or "").split())[:50],
    }


# Documents ------------------------------------------------------------------------------


@transaction.atomic
def add_document(membership: Membership, *, by: Membership, kind: str, file=None, **fields):
    """A document of `membership`'s, added by HR (`hr.manage`) or by the person themselves
    (always visible to them, checked by HR later). `file` is an upload: a PDF or a picture."""
    own = by.pk == membership.pk
    _ensure_own_or(membership, by, Perm.HR_MANAGE)
    if membership.status not in queries.EMPLOYED:
        raise DomainError(_("Documents are kept for people who work here."))
    document = EmployeeDocument(
        company_id=membership.company_id, membership=membership, uploaded_by=by.user
    )
    values = _clean_document(document, {**fields, "kind": kind})
    if own:
        values["visible_to_employee"] = True
    for name, value in values.items():
        setattr(document, name, value)
    if file is not None:
        _attach(document, file)
    document.save()
    _audit(HRAction.DOCUMENT_ADDED, membership, by, document=document.pk, kind=document.kind)
    bump(membership.company_id, DOCUMENTS, EXPIRING)
    return document


@transaction.atomic
def update_document(document: EmployeeDocument, *, by: Membership, file=None, **fields):
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(document.membership, by)
    document = EmployeeDocument.objects.select_for_update().get(pk=document.pk)
    values = _clean_document(document, {k: v for k, v in fields.items() if k in DOCUMENT_FIELDS})
    changed = [name for name, value in values.items() if getattr(document, name) != value]
    for name in changed:
        setattr(document, name, values[name])
    old_file = document.file.name if document.file else ""
    if file is not None:
        _attach(document, file)
        changed.append("file")
    if not changed:
        return document
    if any(name in VERIFIED_FIELDS for name in changed):
        document.verified_at = None
        document.verified_by = None
    if "expires_on" in changed:
        document.expiry_notified = []
    document.save()
    if "file" in changed and old_file:
        _delete_file_on_commit(old_file)
    _audit(
        HRAction.DOCUMENT_CHANGED,
        document.membership,
        by,
        document=document.pk,
        kind=document.kind,
        fields=sorted(changed),
    )
    bump(document.company_id, DOCUMENTS, EXPIRING)
    return document


@transaction.atomic
def remove_document(document: EmployeeDocument, *, by: Membership) -> None:
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(document.membership, by)
    name = document.file.name if document.file else ""
    _audit(
        HRAction.DOCUMENT_REMOVED,
        document.membership,
        by,
        document=document.pk,
        kind=document.kind,
    )
    document.delete()
    if name:
        _delete_file_on_commit(name)
    bump(document.company_id, DOCUMENTS, EXPIRING)


@transaction.atomic
def verify_document(document: EmployeeDocument, *, by: Membership) -> EmployeeDocument:
    """HR has seen the original (or the scan) and it is right. An ID needs `hr.sensitive`:
    checking it means looking at it."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(document.membership, by)
    if document.is_id:
        _ensure(by, Perm.HR_SENSITIVE)
    document = EmployeeDocument.objects.select_for_update().get(pk=document.pk)
    if document.verified_at is None:
        document.verified_at = timezone.now()
        document.verified_by = by.user
        document.save(update_fields=["verified_at", "verified_by", "updated_at"])
        _audit(
            HRAction.DOCUMENT_VERIFIED,
            document.membership,
            by,
            document=document.pk,
            kind=document.kind,
        )
        bump(document.company_id, DOCUMENTS)
    return document


def document_opened(document: EmployeeDocument, user) -> None:
    """Every download of a document's file is recorded (the file check calls this)."""
    audit.record(
        HRAction.DOCUMENT_OPENED,
        company_id=document.company_id,
        actor=user,
        target=document.membership,
        required_perm=Perm.HR_SENSITIVE if document.is_id else Perm.HR_VIEW,
        document=document.pk,
        kind=document.kind,
    )


def may_see_document(member: Membership, document: EmployeeDocument) -> bool:
    """Whether `member` may open `document`'s file and read its number: their own document
    shown to them, or anyone's in their scope with `hr.view` (`hr.sensitive` for an ID)."""
    if member.company_id != document.company_id:
        return False
    if document.membership_id == member.pk:
        return document.visible_to_employee
    perm = Perm.HR_SENSITIVE if document.is_id else Perm.HR_VIEW
    if not member.has_perm(perm):
        return False
    return (
        queries.person(member.company, document.membership_id, branch_ids=scope.branch_ids(member))
        is not None
    )


def _clean_document(document: EmployeeDocument, fields: dict) -> dict:
    clean = dict(fields)
    kind = clean.get("kind", document.kind)
    if kind not in DocumentKind.values:
        raise DomainError(_("Pick a kind of document."))
    if "number" in clean:
        number = clean["number"]
        clean["number"] = (
            ids.passport(number) if kind in PASSPORT_KINDS else ids.document_number(number)
        )
    for name, limit in (("title", 150), ("specialty", 80), ("issuer", 150)):
        if name in clean:
            clean[name] = " ".join(str(clean[name] or "").split())[:limit]
    level = clean.get("level", document.level)
    if level:
        if kind in DIPLOMA_KINDS:
            allowed = DIPLOMA_LEVELS
        elif kind == DocumentKind.QUALIFICATION_CATEGORY:
            allowed = CATEGORY_LEVELS
        else:
            allowed = ()
        if level not in allowed:
            raise DomainError(_("This level doesn't fit this kind of document."))
    issued = clean.get("issued_on", document.issued_on)
    expires = clean.get("expires_on", document.expires_on)
    today = queries.today(document.membership.company)
    if issued and issued > today:
        raise DomainError(_("The issue date can't be in the future."))
    if issued and expires and expires < issued:
        raise DomainError(_("A document can't expire before it was issued."))
    return clean


def _attach(document: EmployeeDocument, file) -> None:
    content = uploads.accept_document(file, allowed=DOCUMENT_TYPES)
    document.file.save(content.name, content, save=False)


def _delete_file_on_commit(name: str) -> None:
    transaction.on_commit(partial(private_storage.delete, name))


# Required documents ---------------------------------------------------------------------


@transaction.atomic
def save_required(
    company,
    *,
    by: Membership,
    kind: str,
    position: Position | None = None,
    level: str = "",
    alternatives: list[str] | tuple = (),
    required: RequiredDocument | None = None,
) -> RequiredDocument:
    """Add a required document (or change `required`): `kind` for everyone, or for the
    people in `position`."""
    _ensure(by, Perm.HR_MANAGE)
    if kind not in DocumentKind.values:
        raise DomainError(_("Pick a kind of document."))
    if position is not None and position.company_id != company.pk:
        raise DomainError(_("Pick a position of this company."))
    others = [value for value in dict.fromkeys(alternatives or ()) if value != kind]
    if any(value not in DocumentKind.values for value in others):
        raise DomainError(_("Pick a kind of document."))
    if level and level not in DocumentLevel.values:
        raise DomainError(_("This level doesn't fit this kind of document."))
    row = required or RequiredDocument(company=company)
    row.kind, row.position, row.level, row.alternatives = kind, position, level, others
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError as exc:
        raise DomainError(_("This document is already required there.")) from exc
    audit.record(
        HRAction.REQUIRED_SAVED,
        company_id=company.pk,
        actor=by.user,
        target=row,
        kind=kind,
        position=position.name if position else None,
    )
    bump(company.pk, REQUIRED, EXPIRING)
    return row


@transaction.atomic
def remove_required(required: RequiredDocument, *, by: Membership) -> None:
    _ensure(by, Perm.HR_MANAGE)
    audit.record(
        HRAction.REQUIRED_REMOVED,
        company_id=required.company_id,
        actor=by.user,
        target=required,
        kind=required.kind,
    )
    required.delete()
    bump(required.company_id, REQUIRED)


# Contract templates ---------------------------------------------------------------------


@transaction.atomic
def save_template(
    company,
    *,
    by: Membership,
    name: str,
    body: str,
    kind: str = "",
    language: str = "uz",
    is_active: bool = True,
    template: ContractTemplate | None = None,
) -> ContractTemplate:
    """Add a contract template (or change `template`). The body is cleaned and may use only
    the fixed placeholders."""
    _ensure(by, Perm.HR_MANAGE)
    name = " ".join(str(name or "").split())[:150]
    if not name:
        raise DomainError(_("Give the template a name."))
    if kind and kind not in ContractKind.values:
        raise DomainError(_("Pick a kind of contract."))
    row = template or ContractTemplate(company=company, created_by=by.user)
    row.name, row.kind, row.language, row.is_active = name, kind, language, is_active
    row.body = printing.clean_body(body)
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError as exc:
        raise DomainError(_("A template with this name exists already.")) from exc
    audit.record(
        HRAction.TEMPLATE_SAVED, company_id=company.pk, actor=by.user, target=row, name=row.name
    )
    bump(company.pk, TEMPLATES)
    return row


@transaction.atomic
def remove_template(template: ContractTemplate, *, by: Membership) -> None:
    """Contracts made from it keep their text (their PDF); they just forget the template."""
    _ensure(by, Perm.HR_MANAGE)
    audit.record(
        HRAction.TEMPLATE_REMOVED,
        company_id=template.company_id,
        actor=by.user,
        target=template,
        name=template.name,
    )
    template.delete()
    bump(template.company_id, TEMPLATES)


def preview(
    template: ContractTemplate,
    *,
    by: Membership,
    membership: Membership | None,
    body: str | None = None,
) -> printing.Filled:
    """The template (or the `body` being edited) filled in for `membership`, or with the
    person's details left blank when there is none."""
    _ensure(by, Perm.HR_MANAGE)
    today = queries.today(by.company)
    if membership is None:
        return printing.fill(
            printing.clean_body(body) if body is not None else template.body,
            {
                "company_name": by.company.name,
                "today": printing.long_date(today, template.language),
            },
        )
    _ensure_reach(membership, by)
    contract = (
        Contract.objects.filter(membership=membership)
        .order_by(_active_first(), "-starts_on", "-pk")
        .first()
    )
    return printing.contract_html(
        membership, template, contract=contract, by=by, today=today, body=body
    )


# Contracts --------------------------------------------------------------------------------

# What changes on a contract in force, through an amendment.
AMENDABLE = ("kind", "ends_on", "probation_until", "weekly_hours", "position")
CONTRACT_FIELDS = (
    "number",
    "kind",
    "starts_on",
    "ends_on",
    "probation_until",
    "weekly_hours",
    "position",
    "template",
    "note",
)
DOCUMENT_TYPES_CONTRACT = ("pdf", "image")


@transaction.atomic
def create_contract(
    membership: Membership,
    *,
    by: Membership,
    starts_on: date,
    kind: str = ContractKind.INDEFINITE,
    file=None,
    **fields,
) -> Contract:
    """A draft contract for `membership` (activated once it is signed). `file` is the signed
    paper scanned, when there is one; otherwise a PDF is made from a template later."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(membership, by)
    if membership.status not in queries.CURRENT:
        raise DomainError(_("Contracts are drawn up for people who work here."))
    contract = Contract(
        company_id=membership.company_id,
        membership=membership,
        created_by=by.user,
        position=membership.position,
    )
    values = _clean_contract(
        contract, {k: v for k, v in {**fields, "kind": kind, "starts_on": starts_on}.items()}
    )
    for name, value in values.items():
        setattr(contract, name, value)
    if not contract.number:
        contract.number = next_number(membership.company, contract.starts_on.year)
    if file is not None:
        _attach_scan(contract, file)
    _save_contract(contract)
    _contract_audit(HRAction.CONTRACT_CREATED, contract, by)
    bump(contract.company_id, CONTRACTS, EXPIRING)
    return contract


@transaction.atomic
def update_contract(contract: Contract, *, by: Membership, file=None, **fields) -> Contract:
    """A draft changes freely; a contract in force or over keeps its terms (an amendment
    changes those) and takes only its number, note and signed scan."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    allowed = CONTRACT_FIELDS if contract.status == Contract.Status.DRAFT else ("number", "note")
    if any(name not in allowed for name in fields):
        raise DomainError(_("A signed contract's terms change only through an amendment."))
    values = _clean_contract(contract, fields)
    changed = {
        name: [audit.plain(_shown(getattr(contract, name))), audit.plain(_shown(value))]
        for name, value in values.items()
        if getattr(contract, name) != value
    }
    for name, value in values.items():
        setattr(contract, name, value)
    old_file = contract.file.name if contract.file else ""
    if file is not None:
        _attach_scan(contract, file)
        changed["file"] = ["", "scan"]
    if not changed:
        return contract
    _save_contract(contract)
    if "file" in changed and old_file:
        _delete_file_on_commit(old_file)
    _contract_audit(HRAction.CONTRACT_CHANGED, contract, by, changes=changed)
    bump(contract.company_id, CONTRACTS, EXPIRING)
    return contract


@transaction.atomic
def delete_contract(contract: Contract, *, by: Membership) -> None:
    """Only a draft goes; a signed contract stays on file."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    if contract.status != Contract.Status.DRAFT:
        raise DomainError(_("Only a draft can be removed; end or terminate a signed contract."))
    name = contract.file.name if contract.file else ""
    _contract_audit(HRAction.CONTRACT_REMOVED, contract, by)
    contract.delete()
    if name:
        _delete_file_on_commit(name)
    bump(contract.company_id, CONTRACTS, EXPIRING)


@transaction.atomic
def activate_contract(contract: Contract, *, by: Membership) -> Contract:
    """The draft is signed: it is now the person's contract in force (one at a time)."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    if contract.status != Contract.Status.DRAFT:
        raise DomainError(_("Only a draft can be signed."))
    if contract.membership.status not in queries.CURRENT:
        raise DomainError(_("Contracts are drawn up for people who work here."))
    today = queries.today(contract.company)
    if contract.ends_on is not None and contract.ends_on < today:
        raise DomainError(_("This contract's end date has passed."))
    contract.status = Contract.Status.ACTIVE
    _save_contract(contract)
    _contract_audit(HRAction.CONTRACT_ACTIVATED, contract, by)
    transaction.on_commit(partial(tasks.notify_contract_ready.delay, contract.pk))
    bump(contract.company_id, CONTRACTS, EXPIRING)
    return contract


@transaction.atomic
def terminate_contract(
    contract: Contract, *, by: Membership | None, terminated_on: date, reason: str
) -> Contract:
    """End a contract in force early: its last day (today or before) and why."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    _ensure_active(contract)
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise DomainError(_("Say why the contract ends."))
    _check_last_day(contract, terminated_on)
    return _close(contract, Contract.Status.TERMINATED, terminated_on, reason, by=by)


@transaction.atomic
def end_contract(
    contract: Contract, *, by: Membership | None, ended_on: date | None = None, reason: str = ""
) -> Contract:
    """A contract in force has run its course (its end date, or `ended_on`)."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    _ensure_active(contract)
    ended_on = ended_on or contract.ends_on or queries.today(contract.company)
    _check_last_day(contract, ended_on)
    return _close(contract, Contract.Status.ENDED, ended_on, reason, by=by)


@transaction.atomic
def renew_contract(
    contract: Contract,
    *,
    by: Membership,
    ends_on: date | None,
    starts_on: date | None = None,
    kind: str | None = None,
) -> Contract:
    """A new contract carries on where a fixed-term one ends: the old one ends the day before
    the new one starts, and the new one is in force at once."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    if contract.status not in (Contract.Status.ACTIVE, Contract.Status.ENDED):
        raise DomainError(_("Only a signed contract can be renewed."))
    if contract.kind not in TERM_KINDS:
        raise DomainError(_("An indefinite contract runs on; there is nothing to renew."))
    today = queries.today(contract.company)
    starts_on = starts_on or (contract.ends_on + timedelta(days=1) if contract.ends_on else today)
    renewed = Contract(
        company_id=contract.company_id,
        membership=contract.membership,
        created_by=by.user,
        position=contract.position,
        weekly_hours=contract.weekly_hours,
        template=contract.template,
    )
    values = _clean_contract(
        renewed, {"kind": kind or contract.kind, "starts_on": starts_on, "ends_on": ends_on}
    )
    for name, value in values.items():
        setattr(renewed, name, value)
    if contract.status == Contract.Status.ACTIVE:
        last_day = starts_on - timedelta(days=1)
        if last_day < contract.starts_on:
            raise DomainError(_("The new contract must start after the current one."))
        _close(contract, Contract.Status.ENDED, last_day, "", by=by, quiet=True)
    elif Contract.objects.filter(
        membership=contract.membership, status=Contract.Status.ACTIVE
    ).exists():
        raise DomainError(_("This person already has a contract in force."))
    renewed.number = next_number(contract.company, starts_on.year)
    renewed.status = Contract.Status.ACTIVE
    _save_contract(renewed)
    _contract_audit(
        HRAction.CONTRACT_RENEWED, renewed, by, renews=contract.pk, renews_number=contract.number
    )
    transaction.on_commit(partial(tasks.notify_contract_ready.delay, renewed.pk))
    bump(contract.company_id, CONTRACTS, EXPIRING)
    return renewed


@transaction.atomic
def pass_probation(contract: Contract, *, by: Membership) -> Contract:
    """The person passed their probation."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    _ensure_active(contract)
    if not contract.on_probation:
        raise DomainError(_("This contract has no probation running."))
    contract.probation_passed_at = timezone.now()
    contract.save(update_fields=["probation_passed_at", "updated_at"])
    _contract_audit(HRAction.PROBATION_PASSED, contract, by)
    bump(contract.company_id, CONTRACTS, EXPIRING)
    return contract


@transaction.atomic
def extend_probation(contract: Contract, *, by: Membership, until: date) -> Contract:
    """Probation runs longer, until `until` (still within the contract)."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    _ensure_active(contract)
    if not contract.on_probation:
        raise DomainError(_("This contract has no probation running."))
    if until <= contract.probation_until:
        raise DomainError(_("Pick a day after the current end of probation."))
    if contract.ends_on is not None and until > contract.ends_on:
        raise DomainError(_("Probation can't run past the contract's end."))
    before = contract.probation_until
    contract.probation_until = until
    contract.probation_notified = []
    contract.save(update_fields=["probation_until", "probation_notified", "updated_at"])
    _contract_audit(
        HRAction.PROBATION_EXTENDED,
        contract,
        by,
        changes={"probation_until": [before.isoformat(), until.isoformat()]},
    )
    bump(contract.company_id, CONTRACTS, EXPIRING)
    return contract


@transaction.atomic
def amend_contract(
    contract: Contract, *, by: Membership | None, effective_on: date, changes: dict, reason: str
) -> Contract:
    """Change the terms of a contract in force (`hr.contracts.amend`): its kind, end,
    probation, weekly hours or position, from `effective_on`, for `reason`."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    _ensure_active(contract)
    unknown = sorted(set(changes) - set(AMENDABLE))
    if unknown:
        raise DomainError(
            _("These terms can't be amended: %(names)s.") % {"names": ", ".join(unknown)}
        )
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise DomainError(_("Say why the contract changes."))
    values = _clean_contract(contract, dict(changes))
    shown = {
        name: [audit.plain(_shown(getattr(contract, name))), audit.plain(_shown(value))]
        for name, value in values.items()
        if getattr(contract, name) != value
    }
    for name, value in values.items():
        setattr(contract, name, value)
    if "ends_on" in shown:
        contract.end_notified = []
    if "probation_until" in shown:
        contract.probation_notified = []
    _save_contract(contract)
    _contract_audit(
        HRAction.CONTRACT_AMENDED,
        contract,
        by,
        effective_on=effective_on.isoformat(),
        reason=reason[:300],
        changes=shown,
    )
    bump(contract.company_id, CONTRACTS, EXPIRING)
    return contract


@transaction.atomic
def generate_pdf(
    contract: Contract, *, by: Membership, template: ContractTemplate | None = None
) -> Contract:
    """Print the contract from `template` (its own one otherwise) as a PDF, kept with it. The
    pay goes in only when `by` holds payroll.view; the file then opens only for them."""
    _ensure(by, Perm.HR_MANAGE)
    _ensure_reach(contract.membership, by)
    contract = _lock_contract(contract)
    template = template or contract.template
    if template is None:
        raise DomainError(_("Pick a contract template."))
    if template.company_id != contract.company_id:
        raise DomainError(_("Pick a contract template."))
    today = queries.today(contract.company)
    filled = printing.contract_html(
        contract.membership, template, contract=contract, by=by, today=today
    )
    data = printing.contract_pdf(contract, template, filled)
    old_file = contract.file.name if contract.file else ""
    contract.file.save(f"{uuid4().hex}.pdf", ContentFile(data), save=False)
    contract.template = template
    contract.pdf_generated_at = timezone.now()
    contract.file_has_salary = filled.has_salary
    contract.save()
    if old_file:
        _delete_file_on_commit(old_file)
    _contract_audit(HRAction.CONTRACT_PRINTED, contract, by, template=template.name)
    bump(contract.company_id, CONTRACTS)
    return contract


@transaction.atomic
def acknowledge_contract(contract: Contract, *, by: Membership) -> Contract:
    """The person has read their contract in force (the mini app's "I've read it")."""
    contract = _lock_contract(contract)
    if contract.membership_id != by.pk:
        raise PermissionDenied(_("You don't have permission to do this."))
    _ensure_active(contract)
    if contract.acknowledged_at is None:
        contract.acknowledged_at = timezone.now()
        contract.save(update_fields=["acknowledged_at", "updated_at"])
        _contract_audit(HRAction.CONTRACT_ACKNOWLEDGED, contract, by)
        bump(contract.company_id, CONTRACTS)
    return contract


def may_see_contract_file(member: Membership, contract: Contract) -> bool:
    """The person's own contract (not a draft), or anyone's in scope for `hr.view`; a file
    with the pay in it needs `payroll.view` as well."""
    if member.company_id != contract.company_id:
        return False
    if contract.membership_id == member.pk:
        return contract.status != Contract.Status.DRAFT
    if not member.has_perm(Perm.HR_VIEW):
        return False
    if contract.file_has_salary and not member.has_perm(Perm.PAYROLL_VIEW):
        return False
    return (
        queries.person(member.company, contract.membership_id, branch_ids=scope.branch_ids(member))
        is not None
    )


def _close(
    contract: Contract,
    status: str,
    last_day: date,
    reason: str,
    *,
    by: Membership | None,
    quiet: bool = False,
) -> Contract:
    contract.status = status
    contract.terminated_on = last_day
    contract.termination_reason = (reason or "")[:300]
    contract.save(update_fields=["status", "terminated_on", "termination_reason", "updated_at"])
    if not quiet:
        action = (
            HRAction.CONTRACT_TERMINATED
            if status == Contract.Status.TERMINATED
            else HRAction.CONTRACT_ENDED
        )
        _contract_audit(action, contract, by, last_day=last_day.isoformat())
    bump(contract.company_id, CONTRACTS, EXPIRING)
    return contract


def _clean_contract(contract: Contract, fields: dict) -> dict:
    clean = dict(fields)
    if "number" in clean:
        clean["number"] = " ".join(str(clean["number"] or "").split())[:30]
    if "note" in clean:
        clean["note"] = " ".join(str(clean["note"] or "").split())[:300]
    if "kind" in clean and clean["kind"] not in ContractKind.values:
        raise DomainError(_("Pick a kind of contract."))
    position = clean.get("position")
    if position is not None and position.company_id != contract.company_id:
        raise DomainError(_("Pick a position of this company."))
    template = clean.get("template")
    if template is not None and template.company_id != contract.company_id:
        raise DomainError(_("Pick a contract template."))
    kind = clean.get("kind", contract.kind)
    starts = clean.get("starts_on", contract.starts_on)
    ends = clean.get("ends_on", contract.ends_on)
    probation = clean.get("probation_until", contract.probation_until)
    if kind == ContractKind.FIXED_TERM and ends is None:
        raise DomainError(_("A fixed-term contract needs its end date."))
    if starts and ends and ends < starts:
        raise DomainError(_("A contract can't end before it starts."))
    if probation is not None:
        if starts and probation < starts:
            raise DomainError(_("Probation can't end before the contract starts."))
        if ends and probation > ends:
            raise DomainError(_("Probation can't run past the contract's end."))
    return clean


def _save_contract(contract: Contract) -> None:
    try:
        with transaction.atomic():
            contract.save()
    except IntegrityError as exc:
        if "hr_one_active_contract" in str(exc):
            raise DomainError(_("This person already has a contract in force.")) from exc
        if "hr_unique_contract_number" in str(exc):
            raise DomainError(_("Another contract has this number.")) from exc
        raise


def next_number(company, year: int) -> str:
    """The company's next free number for `year`: 2026-001, 2026-002…"""
    taken = set(
        Contract.objects.filter(company=company, number__startswith=f"{year}-").values_list(
            "number", flat=True
        )
    )
    count = len(taken) + 1
    while f"{year}-{count:03d}" in taken:
        count += 1
    return f"{year}-{count:03d}"


def _attach_scan(contract: Contract, file) -> None:
    content = uploads.accept_document(file, allowed=DOCUMENT_TYPES_CONTRACT)
    contract.file.save(content.name, content, save=False)
    contract.pdf_generated_at = None
    # A signed paper contract states the pay: it opens like a contract printed with it.
    contract.file_has_salary = True


def _ensure_active(contract: Contract) -> None:
    if contract.status != Contract.Status.ACTIVE:
        raise DomainError(_("This contract isn't in force."))


def _check_last_day(contract: Contract, last_day: date) -> None:
    if last_day > queries.today(contract.company):
        raise DomainError(_("The last day can't be in the future."))
    if last_day < contract.starts_on:
        raise DomainError(_("The last day can't be before the contract starts."))


def _lock_contract(contract: Contract) -> Contract:
    return (
        Contract.objects.select_for_update(of=("self",))
        .select_related("membership__company", "membership__user", "company", "template")
        .get(pk=contract.pk)
    )


def _active_first():
    from django.db.models import Case, IntegerField, Value, When

    return Case(
        When(status=Contract.Status.ACTIVE, then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
    )


def _shown(value):
    """A value as the audit log shows it: a position by its name."""
    if isinstance(value, Position | ContractTemplate):
        return value.name
    return value


def _contract_audit(action: str, contract: Contract, by: Membership | None, **details) -> None:
    _audit(
        action,
        contract.membership,
        by,
        contract=contract.pk,
        number=contract.number,
        **details,
    )


# Helpers --------------------------------------------------------------------------------


def bump(company_id: int, *keys: str) -> None:
    """Move the pulse keys on once the transaction commits (open dashboards refetch)."""
    transaction.on_commit(partial(pulse.bump, company_id, *keys))


def _ensure(by: Membership | None, perm: Perm) -> None:
    if by is not None and not by.has_perm(perm):
        raise PermissionDenied(_("You don't have permission to do this."))


def _ensure_own_or(membership: Membership, by: Membership, perm: Perm) -> None:
    """The person themselves, or a holder of `perm` who reaches them."""
    if by.company_id != membership.company_id:
        raise PermissionDenied(_("You don't have permission to do this."))
    if by.pk != membership.pk:
        _ensure(by, perm)
        _ensure_reach(membership, by)


def _ensure_reach(membership: Membership, by: Membership | None) -> None:
    """`by` works in the same company and sees one of the person's branches."""
    if by is None:
        return
    if by.company_id != membership.company_id or (
        queries.person(membership.company, membership.pk, branch_ids=scope.branch_ids(by)) is None
    ):
        raise PermissionDenied(_("You don't have permission to do this."))


def _audit(
    action: str, membership: Membership, by: Membership | None, *, required_perm=Perm.HR_VIEW, **d
):
    return audit.record(
        action,
        company_id=membership.company_id,
        actor=by.user if by else None,
        target=membership,
        required_perm=required_perm,
        **d,
    )
