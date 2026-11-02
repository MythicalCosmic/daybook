"""Business logic of HR records: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

Who may do what: `hr.manage` edits anyone's profile and documents in their branch scope (ID
numbers are write-only for them: reading one back needs `hr.sensitive`, and every such read
is audited); a person edits a few fields of their own profile and adds their own documents.
"""

from datetime import date
from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core import uploads
from apps.core.exceptions import DomainError
from apps.hr import conf, ids, queries
from apps.hr.audit_actions import HRAction
from apps.hr.models import (
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

SETTINGS_FIELDS = (
    "document_warn_days",
    "contract_warn_days",
    "probation_warn_days",
    "celebrations_enabled",
    "celebrate_anniversaries",
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


def left(membership: Membership, *, terminated_on: date | None, details: dict | None) -> None:
    """`member_left`: their last day and why go on their profile (when they have one)."""
    profile = EmployeeProfile.objects.filter(membership=membership).first()
    if profile is None:
        return
    wizard = (details or {}).get("members") or {}
    profile.terminated_on = terminated_on or queries.today(membership.company)
    profile.termination_reason = LEAVING_REASONS.get(
        wizard.get("reason"), EmployeeProfile.TerminationReason.OTHER
    )
    profile.termination_note = str(wizard.get("note") or "")[:1000]
    profile.save(
        update_fields=["terminated_on", "termination_reason", "termination_note", "updated_at"]
    )
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
    storage = EmployeeDocument._meta.get_field("file").storage
    transaction.on_commit(partial(storage.delete, name))


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
