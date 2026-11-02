"""Shapes of the HR endpoints (owner dashboard and mini app).

IDs and card numbers always leave masked ("AA•••••67"), except from `people/{mid}/sensitive/`.
An ID document's number and file are hidden from anyone without `hr.sensitive` (their own
documents excepted). The context carries `membership` (the viewer) and `today`.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.files import signed_url
from apps.core.models import Language
from apps.hr import ids, queries, services
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
from apps.members import departments
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, person_ref


class PersonRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "HrPersonRef"


class NamedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "HrNamed"


class BranchRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()

    class Meta:
        ref_name = "HrBranchRef"


def named(row) -> dict | None:
    return {"id": row.pk, "name": row.name} if row is not None else None


def viewer(context) -> Membership:
    return context["membership"]


# Settings -------------------------------------------------------------------------------


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = HRSettings
        fields = services.SETTINGS_FIELDS
        ref_name = "HrSettings"


# Profiles -------------------------------------------------------------------------------


class EmergencyContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmergencyContact
        fields = ("id", "name", "relation", "phone")
        read_only_fields = ("id",)
        ref_name = "HrEmergencyContact"
        extra_kwargs = {"relation": {"required": False}}


class ProfileSerializer(serializers.ModelSerializer):
    """A person's profile as HR sees it: IDs masked, notes only for `hr.manage`."""

    member = serializers.SerializerMethodField()
    first_name = serializers.CharField(source="membership.first_name", read_only=True)
    last_name = serializers.CharField(source="membership.last_name", read_only=True)
    status = serializers.ChoiceField(
        source="membership.status", choices=Membership.Status.choices, read_only=True
    )
    position = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    manager = serializers.SerializerMethodField(help_text="Their head: whom they report to.")
    home_branch = serializers.SerializerMethodField()
    pinfl = serializers.SerializerMethodField(help_text="Masked: 10 hidden, the last 4 shown.")
    passport = serializers.SerializerMethodField(help_text="Masked, e.g. AA•••••67.")
    payout_card = serializers.SerializerMethodField(help_text="Masked: the last 4 digits.")
    passport_shared = serializers.SerializerMethodField(
        help_text="Someone else in the company has the same passport number on file."
    )
    notes = serializers.SerializerMethodField(help_text="HR's notes; null without hr.manage.")
    emergency_contacts = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_reveal = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeProfile
        fields = (
            "member",
            "first_name",
            "last_name",
            "status",
            "position",
            "department",
            "manager",
            "home_branch",
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
            "pinfl",
            "passport",
            "passport_shared",
            "payout_method",
            "payout_card",
            "terminated_on",
            "termination_reason",
            "termination_note",
            "notes",
            "emergency_contacts",
            "can_edit",
            "can_reveal",
        )
        read_only_fields = fields
        ref_name = "HrProfile"

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, profile: EmployeeProfile) -> dict:
        return person_ref(profile.membership)

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_position(self, profile: EmployeeProfile) -> dict | None:
        return named(profile.membership.position)

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_department(self, profile: EmployeeProfile) -> dict | None:
        return named(profile.membership.department)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_manager(self, profile: EmployeeProfile) -> dict | None:
        return person_ref(departments.manager_of(profile.membership))

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, profile: EmployeeProfile) -> dict | None:
        return branch_ref(profile.membership.home_branch)

    def get_pinfl(self, profile: EmployeeProfile) -> str:
        return ids.masked(profile.pinfl, head=0, tail=4)

    def get_passport(self, profile: EmployeeProfile) -> str:
        return ids.masked(profile.passport)

    def get_payout_card(self, profile: EmployeeProfile) -> str:
        return ids.masked(profile.payout_card, head=0, tail=4)

    def get_passport_shared(self, profile: EmployeeProfile) -> bool:
        return queries.passport_shared(profile)

    def get_notes(self, profile: EmployeeProfile) -> str | None:
        return profile.notes if viewer(self.context).has_perm(Perm.HR_MANAGE) else None

    @extend_schema_field(EmergencyContactSerializer(many=True))
    def get_emergency_contacts(self, profile: EmployeeProfile) -> list[dict]:
        if profile.pk is None:
            return []
        return EmergencyContactSerializer(profile.emergency_contacts.all(), many=True).data

    def get_can_edit(self, profile: EmployeeProfile) -> bool:
        return viewer(self.context).has_perm(Perm.HR_MANAGE)

    def get_can_reveal(self, profile: EmployeeProfile) -> bool:
        return viewer(self.context).has_perm(Perm.HR_SENSITIVE)


class ProfileUpdateSerializer(serializers.Serializer):
    """What HR changes. IDs go in as typed (spaces are fine) and come back masked."""

    employee_number = serializers.CharField(max_length=20, allow_blank=True, required=False)
    middle_name = serializers.CharField(max_length=100, allow_blank=True, required=False)
    birth_date = serializers.DateField(allow_null=True, required=False)
    show_birthday = serializers.BooleanField(required=False)
    gender = serializers.ChoiceField(
        EmployeeProfile.Gender.choices, allow_blank=True, required=False
    )
    hire_date = serializers.DateField(allow_null=True, required=False)
    employment_type = serializers.ChoiceField(
        EmployeeProfile.EmploymentType.choices, required=False
    )
    personal_phone = serializers.CharField(max_length=30, allow_blank=True, required=False)
    email = serializers.EmailField(allow_blank=True, required=False)
    address = serializers.CharField(max_length=255, allow_blank=True, required=False)
    city = serializers.CharField(max_length=100, allow_blank=True, required=False)
    tin = serializers.CharField(max_length=20, allow_blank=True, required=False)
    pinfl = serializers.CharField(max_length=30, allow_blank=True, required=False)
    passport = serializers.CharField(max_length=20, allow_blank=True, required=False)
    payout_method = serializers.ChoiceField(EmployeeProfile.PayoutMethod.choices, required=False)
    payout_card = serializers.CharField(max_length=30, allow_blank=True, required=False)
    notes = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    terminated_on = serializers.DateField(allow_null=True, required=False)
    termination_reason = serializers.ChoiceField(
        EmployeeProfile.TerminationReason.choices, allow_blank=True, required=False
    )
    termination_note = serializers.CharField(max_length=1000, allow_blank=True, required=False)

    class Meta:
        ref_name = "HrProfileUpdate"


class SensitiveSerializer(serializers.Serializer):
    member = PersonRefSerializer()
    pinfl = serializers.CharField()
    passport = serializers.CharField()
    payout_card = serializers.CharField()
    tin = serializers.CharField()

    class Meta:
        ref_name = "HrSensitive"


def sensitive_payload(profile: EmployeeProfile) -> dict:
    return {
        "member": person_ref(profile.membership),
        "pinfl": profile.pinfl,
        "passport": profile.passport,
        "payout_card": profile.payout_card,
        "tin": profile.tin,
    }


# Documents ------------------------------------------------------------------------------


class DocumentSerializer(serializers.ModelSerializer):
    """A document row. An ID's number is masked and its file left out without `hr.sensitive`
    (`file_hidden` says one exists)."""

    member = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()
    kind = serializers.ChoiceField(DocumentKind.choices, read_only=True)
    number = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField(help_text="Signed download link (audited).")
    has_file = serializers.SerializerMethodField()
    file_hidden = serializers.SerializerMethodField()
    is_id = serializers.BooleanField(read_only=True)
    uploaded_by = serializers.SerializerMethodField()
    verified = serializers.SerializerMethodField()
    verified_by = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField(
        help_text="Days until it expires (negative once expired); null without an expiry."
    )
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeDocument
        fields = (
            "id",
            "member",
            "position",
            "home_branch",
            "kind",
            "title",
            "number",
            "issued_on",
            "expires_on",
            "level",
            "specialty",
            "issuer",
            "file",
            "has_file",
            "file_hidden",
            "is_id",
            "visible_to_employee",
            "uploaded_by",
            "verified",
            "verified_by",
            "verified_at",
            "state",
            "days_left",
            "created_at",
            "can_edit",
        )
        read_only_fields = fields
        ref_name = "HrDocument"

    def _sees(self, document: EmployeeDocument) -> bool:
        cache = self.context.setdefault("_sees", {})
        if document.pk not in cache:
            cache[document.pk] = services.may_see_document(viewer(self.context), document)
        return cache[document.pk]

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, document: EmployeeDocument) -> dict:
        return person_ref(document.membership)

    def get_position(self, document: EmployeeDocument) -> str | None:
        position = document.membership.position
        return position.name if position else None

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, document: EmployeeDocument) -> dict | None:
        return branch_ref(document.membership.home_branch)

    def get_number(self, document: EmployeeDocument) -> str:
        if document.is_id and not self._sees(document):
            return ids.masked(document.number)
        return document.number

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file(self, document: EmployeeDocument) -> str | None:
        if not document.file or not self._sees(document):
            return None
        request = self.context.get("request")
        return signed_url(
            document.file,
            user=request.user,
            company_id=document.company_id,
            check=f"hr.document:{document.pk}",
        )

    def get_has_file(self, document: EmployeeDocument) -> bool:
        return bool(document.file)

    def get_file_hidden(self, document: EmployeeDocument) -> bool:
        return bool(document.file) and not self._sees(document)

    def get_uploaded_by(self, document: EmployeeDocument) -> str | None:
        user = document.uploaded_by
        return user.get_full_name() or str(user) if user else None

    def get_verified(self, document: EmployeeDocument) -> bool:
        return document.verified_at is not None

    def get_verified_by(self, document: EmployeeDocument) -> str | None:
        user = document.verified_by
        return user.get_full_name() or str(user) if user else None

    @extend_schema_field(serializers.ChoiceField(queries.DOCUMENT_STATES))
    def get_state(self, document: EmployeeDocument) -> str:
        return queries.state(document, self.context["today"], self.context["warn_days"])

    def get_days_left(self, document: EmployeeDocument) -> int | None:
        if document.expires_on is None:
            return None
        return (document.expires_on - self.context["today"]).days

    def get_can_edit(self, document: EmployeeDocument) -> bool:
        return viewer(self.context).has_perm(Perm.HR_MANAGE)


class DocumentWriteSerializer(serializers.Serializer):
    """A document's fields; multipart with `file` (a PDF or a picture)."""

    member_id = serializers.IntegerField(required=False, help_text="Whose document (on create).")
    kind = serializers.ChoiceField(DocumentKind.choices, required=False)
    title = serializers.CharField(max_length=150, allow_blank=True, required=False)
    number = serializers.CharField(max_length=40, allow_blank=True, required=False)
    issued_on = serializers.DateField(allow_null=True, required=False)
    expires_on = serializers.DateField(allow_null=True, required=False)
    level = serializers.ChoiceField(DocumentLevel.choices, allow_blank=True, required=False)
    specialty = serializers.CharField(max_length=80, allow_blank=True, required=False)
    issuer = serializers.CharField(max_length=150, allow_blank=True, required=False)
    visible_to_employee = serializers.BooleanField(required=False)
    file = serializers.FileField(required=False, allow_null=True)

    class Meta:
        ref_name = "HrDocumentWrite"


class RequiredDocumentSerializer(serializers.ModelSerializer):
    position = serializers.SerializerMethodField()
    position_id = serializers.IntegerField(
        write_only=True, required=False, allow_null=True, help_text="Empty: everyone."
    )
    kind = serializers.ChoiceField(DocumentKind.choices)
    level = serializers.ChoiceField(DocumentLevel.choices, allow_blank=True, required=False)
    alternatives = serializers.ListField(
        child=serializers.ChoiceField(DocumentKind.choices), required=False, max_length=8
    )

    class Meta:
        model = RequiredDocument
        fields = ("id", "kind", "position", "position_id", "level", "alternatives")
        read_only_fields = ("id", "position")
        ref_name = "HrRequiredDocument"

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_position(self, row: RequiredDocument) -> dict | None:
        return named(row.position)


class ComplianceItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(DocumentKind.choices)
    status = serializers.ChoiceField(queries.CHECK_STATES)
    document_id = serializers.IntegerField(allow_null=True)
    expires_on = serializers.DateField(allow_null=True)
    level = serializers.CharField(help_text="The level asked for; empty for any.")

    class Meta:
        ref_name = "HrComplianceItem"


class ComplianceRowSerializer(serializers.Serializer):
    member = PersonRefSerializer()
    position = NamedSerializer(allow_null=True)
    home_branch = BranchRefSerializer(allow_null=True)
    items = ComplianceItemSerializer(many=True)
    missing = serializers.IntegerField(help_text="Required documents missing or expired.")
    complete = serializers.BooleanField()

    class Meta:
        ref_name = "HrComplianceRow"


class ComplianceTotalsSerializer(serializers.Serializer):
    people = serializers.IntegerField()
    complete = serializers.IntegerField()
    missing = serializers.IntegerField()
    expired = serializers.IntegerField()
    expiring = serializers.IntegerField()
    unverified = serializers.IntegerField()

    class Meta:
        ref_name = "HrComplianceTotals"


class ComplianceSerializer(serializers.Serializer):
    kinds = serializers.ListField(child=serializers.ChoiceField(DocumentKind.choices))
    rows = ComplianceRowSerializer(many=True)
    totals = ComplianceTotalsSerializer()

    class Meta:
        ref_name = "HrCompliance"


def compliance_payload(found: dict) -> dict:
    rows = []
    for member, checks in found["rows"]:
        rows.append(
            {
                "member": person_ref(member),
                "position": named(member.position),
                "home_branch": branch_ref(member.home_branch),
                "items": [
                    {
                        "kind": each.required.kind,
                        "status": each.status,
                        "document_id": each.document.pk if each.document else None,
                        "expires_on": each.document.expires_on if each.document else None,
                        "level": each.required.level,
                    }
                    for each in checks
                ],
                "missing": sum(
                    1 for each in checks if each.status in (queries.MISSING, queries.EXPIRED)
                ),
                "complete": all(
                    each.status not in (queries.MISSING, queries.EXPIRED) for each in checks
                ),
            }
        )
    return {"kinds": found["kinds"], "rows": rows, "totals": found["totals"]}


# The mini app: a person's own file --------------------------------------------------------


class MyProfileSerializer(serializers.ModelSerializer):
    """Someone's own profile: their IDs and card masked back."""

    first_name = serializers.CharField(source="membership.first_name", read_only=True)
    last_name = serializers.CharField(source="membership.last_name", read_only=True)
    position = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    pinfl = serializers.SerializerMethodField()
    passport = serializers.SerializerMethodField()
    payout_card = serializers.SerializerMethodField()
    emergency_contacts = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeProfile
        fields = (
            "first_name",
            "last_name",
            "middle_name",
            "position",
            "department",
            "birth_date",
            "show_birthday",
            "hire_date",
            "employment_type",
            "personal_phone",
            "email",
            "address",
            "city",
            "pinfl",
            "passport",
            "payout_method",
            "payout_card",
            "emergency_contacts",
        )
        read_only_fields = fields
        ref_name = "HrMyProfile"

    def get_position(self, profile: EmployeeProfile) -> str | None:
        position = profile.membership.position
        return position.name if position else None

    def get_department(self, profile: EmployeeProfile) -> str | None:
        department = profile.membership.department
        return department.name if department else None

    def get_pinfl(self, profile: EmployeeProfile) -> str:
        return ids.masked(profile.pinfl, head=0, tail=4)

    def get_passport(self, profile: EmployeeProfile) -> str:
        return ids.masked(profile.passport)

    def get_payout_card(self, profile: EmployeeProfile) -> str:
        return ids.masked(profile.payout_card, head=0, tail=4)

    @extend_schema_field(EmergencyContactSerializer(many=True))
    def get_emergency_contacts(self, profile: EmployeeProfile) -> list[dict]:
        if profile.pk is None:
            return []
        return EmergencyContactSerializer(profile.emergency_contacts.all(), many=True).data


class MyProfileUpdateSerializer(serializers.Serializer):
    personal_phone = serializers.CharField(max_length=30, allow_blank=True, required=False)
    email = serializers.EmailField(allow_blank=True, required=False)
    address = serializers.CharField(max_length=255, allow_blank=True, required=False)
    city = serializers.CharField(max_length=100, allow_blank=True, required=False)
    show_birthday = serializers.BooleanField(required=False)
    payout_card = serializers.CharField(max_length=30, allow_blank=True, required=False)

    class Meta:
        ref_name = "HrMyProfileUpdate"


class MyDocumentSerializer(serializers.ModelSerializer):
    kind = serializers.ChoiceField(DocumentKind.choices, read_only=True)
    number = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField(help_text="Signed download link.")
    verified = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeDocument
        fields = (
            "id",
            "kind",
            "title",
            "number",
            "issued_on",
            "expires_on",
            "level",
            "file",
            "verified",
            "state",
            "days_left",
            "created_at",
        )
        read_only_fields = fields
        ref_name = "HrMyDocument"

    def get_number(self, document: EmployeeDocument) -> str:
        return ids.masked(document.number) if document.is_id else document.number

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file(self, document: EmployeeDocument) -> str | None:
        if not document.file:
            return None
        return signed_url(
            document.file,
            user=self.context["request"].user,
            company_id=document.company_id,
            check=f"hr.document:{document.pk}",
        )

    def get_verified(self, document: EmployeeDocument) -> bool:
        return document.verified_at is not None

    @extend_schema_field(serializers.ChoiceField(queries.DOCUMENT_STATES))
    def get_state(self, document: EmployeeDocument) -> str:
        return queries.state(document, self.context["today"], self.context["warn_days"])

    def get_days_left(self, document: EmployeeDocument) -> int | None:
        if document.expires_on is None:
            return None
        return (document.expires_on - self.context["today"]).days


class MyDocumentWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(DocumentKind.choices)
    title = serializers.CharField(max_length=150, allow_blank=True, required=False)
    number = serializers.CharField(max_length=40, allow_blank=True, required=False)
    issued_on = serializers.DateField(allow_null=True, required=False)
    expires_on = serializers.DateField(allow_null=True, required=False)
    file = serializers.FileField()

    class Meta:
        ref_name = "HrMyDocumentWrite"


# Contract templates and contracts ---------------------------------------------------------


class ContractTemplateSerializer(serializers.ModelSerializer):
    kind = serializers.ChoiceField(ContractKind.choices, allow_blank=True, required=False)
    language = serializers.ChoiceField(Language.choices, required=False)
    contracts = serializers.SerializerMethodField(help_text="Contracts printed from it.")

    class Meta:
        model = ContractTemplate
        fields = ("id", "name", "kind", "language", "body", "is_active", "contracts", "updated_at")
        read_only_fields = ("id", "contracts", "updated_at")
        ref_name = "HrContractTemplate"

    def get_contracts(self, template: ContractTemplate) -> int:
        found = getattr(template, "contracts_count", None)
        return found if found is not None else template.contracts.count()


class PreviewRequestSerializer(serializers.Serializer):
    member_id = serializers.IntegerField(required=False, allow_null=True)
    body = serializers.CharField(required=False, help_text="Unsaved text to preview instead.")
    language = serializers.ChoiceField(Language.choices, required=False)

    class Meta:
        ref_name = "HrPreviewRequest"


class PreviewSerializer(serializers.Serializer):
    html = serializers.CharField(help_text="The filled-in text (safe HTML).")
    empty = serializers.ListField(
        child=serializers.CharField(), help_text="Placeholders with nothing to fill in."
    )
    has_salary = serializers.BooleanField()

    class Meta:
        ref_name = "HrPreview"


class PlaceholdersSerializer(serializers.Serializer):
    placeholders = serializers.ListField(child=serializers.CharField())

    class Meta:
        ref_name = "HrPlaceholders"


class ContractActionsSerializer(serializers.Serializer):
    edit = serializers.BooleanField()
    delete = serializers.BooleanField()
    activate = serializers.BooleanField()
    terminate = serializers.BooleanField()
    end = serializers.BooleanField()
    renew = serializers.BooleanField()
    pass_probation = serializers.BooleanField()
    extend_probation = serializers.BooleanField()
    generate_pdf = serializers.BooleanField()

    class Meta:
        ref_name = "HrContractActions"


def contract_actions(contract: Contract, member: Membership) -> dict:
    """What `member` may do with `contract` now (the buttons the dashboard shows)."""
    manage = member.has_perm(Perm.HR_MANAGE)
    draft = contract.status == Contract.Status.DRAFT
    active = contract.status == Contract.Status.ACTIVE
    probation = active and contract.on_probation
    return {
        "edit": manage and draft,
        "delete": manage and draft,
        "activate": manage and draft,
        "terminate": manage and active,
        "end": manage and active,
        "renew": manage
        and contract.status in (Contract.Status.ACTIVE, Contract.Status.ENDED)
        and contract.kind in TERM_KINDS,
        "pass_probation": manage and probation,
        "extend_probation": manage and probation,
        "generate_pdf": manage,
    }


class ContractSerializer(serializers.ModelSerializer):
    """A contract row. A file with the pay in it is left out without `payroll.view`
    (`file_hidden` says one exists)."""

    member = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()
    kind = serializers.ChoiceField(ContractKind.choices, read_only=True)
    status = serializers.ChoiceField(Contract.Status.choices, read_only=True)
    position = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField()
    weekly_hours = serializers.DecimalField(
        max_digits=4, decimal_places=1, read_only=True, allow_null=True
    )
    on_probation = serializers.BooleanField(read_only=True)
    file = serializers.SerializerMethodField(help_text="Signed download link.")
    has_file = serializers.SerializerMethodField()
    file_hidden = serializers.SerializerMethodField()
    file_is_scan = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField(help_text="Days until it ends; null if open.")
    probation_days_left = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = (
            "id",
            "member",
            "home_branch",
            "number",
            "kind",
            "status",
            "position",
            "starts_on",
            "ends_on",
            "probation_until",
            "probation_passed_at",
            "on_probation",
            "weekly_hours",
            "template",
            "file",
            "has_file",
            "file_hidden",
            "file_is_scan",
            "pdf_generated_at",
            "acknowledged_at",
            "terminated_on",
            "termination_reason",
            "note",
            "days_left",
            "probation_days_left",
            "created_by",
            "created_at",
            "actions",
        )
        read_only_fields = fields
        ref_name = "HrContract"

    def _sees(self, contract: Contract) -> bool:
        cache = self.context.setdefault("_sees_contract", {})
        if contract.pk not in cache:
            cache[contract.pk] = services.may_see_contract_file(viewer(self.context), contract)
        return cache[contract.pk]

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, contract: Contract) -> dict:
        return person_ref(contract.membership)

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, contract: Contract) -> dict | None:
        return branch_ref(contract.membership.home_branch)

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_position(self, contract: Contract) -> dict | None:
        return named(contract.position)

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_template(self, contract: Contract) -> dict | None:
        return named(contract.template)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file(self, contract: Contract) -> str | None:
        if not contract.file or not self._sees(contract):
            return None
        return contract_link(contract, self.context["request"].user)

    def get_has_file(self, contract: Contract) -> bool:
        return bool(contract.file)

    def get_file_hidden(self, contract: Contract) -> bool:
        return bool(contract.file) and not self._sees(contract)

    def get_file_is_scan(self, contract: Contract) -> bool:
        return bool(contract.file) and contract.pdf_generated_at is None

    def get_days_left(self, contract: Contract) -> int | None:
        if contract.ends_on is None:
            return None
        return (contract.ends_on - self.context["today"]).days

    def get_probation_days_left(self, contract: Contract) -> int | None:
        if not contract.on_probation:
            return None
        return (contract.probation_until - self.context["today"]).days

    def get_created_by(self, contract: Contract) -> str | None:
        user = contract.created_by
        return user.get_full_name() or str(user) if user else None

    @extend_schema_field(ContractActionsSerializer)
    def get_actions(self, contract: Contract) -> dict:
        return contract_actions(contract, viewer(self.context))


def contract_link(contract: Contract, user) -> str:
    """A signed link to the contract's file, saved as "<number>.pdf"."""
    extension = contract.file.name.rsplit(".", 1)[-1]
    return signed_url(
        contract.file,
        user=user,
        company_id=contract.company_id,
        check=f"hr.contract:{contract.pk}",
        filename=f"{contract.number or contract.pk}.{extension}",
    )


class ContractWriteSerializer(serializers.Serializer):
    """A contract's terms; multipart with `file` for a signed scan."""

    member_id = serializers.IntegerField(required=False, help_text="Whose contract (on create).")
    number = serializers.CharField(max_length=30, allow_blank=True, required=False)
    kind = serializers.ChoiceField(ContractKind.choices, required=False)
    starts_on = serializers.DateField(required=False)
    ends_on = serializers.DateField(allow_null=True, required=False)
    probation_until = serializers.DateField(allow_null=True, required=False)
    weekly_hours = serializers.DecimalField(
        max_digits=4,
        decimal_places=1,
        min_value=1,
        max_value=60,
        allow_null=True,
        required=False,
    )
    position_id = serializers.IntegerField(allow_null=True, required=False)
    template_id = serializers.IntegerField(allow_null=True, required=False)
    note = serializers.CharField(max_length=300, allow_blank=True, required=False)
    file = serializers.FileField(required=False, allow_null=True)

    class Meta:
        ref_name = "HrContractWrite"


class TerminateSerializer(serializers.Serializer):
    terminated_on = serializers.DateField()
    reason = serializers.CharField(max_length=300)

    class Meta:
        ref_name = "HrContractTerminate"


class EndSerializer(serializers.Serializer):
    ended_on = serializers.DateField(required=False, help_text="Its end date by default.")
    reason = serializers.CharField(max_length=300, allow_blank=True, required=False)

    class Meta:
        ref_name = "HrContractEnd"


class RenewSerializer(serializers.Serializer):
    ends_on = serializers.DateField(allow_null=True, required=False)
    starts_on = serializers.DateField(required=False, help_text="The day after the old end.")
    kind = serializers.ChoiceField(ContractKind.choices, required=False)

    class Meta:
        ref_name = "HrContractRenew"


class ExtendProbationSerializer(serializers.Serializer):
    until = serializers.DateField()

    class Meta:
        ref_name = "HrExtendProbation"


class GeneratePdfSerializer(serializers.Serializer):
    template_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        ref_name = "HrGeneratePdf"


class MyContractSerializer(serializers.ModelSerializer):
    kind = serializers.ChoiceField(ContractKind.choices, read_only=True)
    status = serializers.ChoiceField(Contract.Status.choices, read_only=True)
    position = serializers.SerializerMethodField()
    weekly_hours = serializers.DecimalField(
        max_digits=4, decimal_places=1, read_only=True, allow_null=True
    )
    file = serializers.SerializerMethodField(help_text="Signed download link (a PDF or a scan).")
    needs_acknowledgement = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = (
            "id",
            "number",
            "kind",
            "status",
            "position",
            "starts_on",
            "ends_on",
            "probation_until",
            "probation_passed_at",
            "weekly_hours",
            "file",
            "acknowledged_at",
            "needs_acknowledgement",
            "terminated_on",
        )
        read_only_fields = fields
        ref_name = "HrMyContract"

    def get_position(self, contract: Contract) -> str | None:
        return contract.position.name if contract.position else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file(self, contract: Contract) -> str | None:
        if not contract.file:
            return None
        return contract_link(contract, self.context["request"].user)

    def get_needs_acknowledgement(self, contract: Contract) -> bool:
        return contract.status == Contract.Status.ACTIVE and contract.acknowledged_at is None


class FileLinkSerializer(serializers.Serializer):
    url = serializers.CharField()

    class Meta:
        ref_name = "HrFileLink"
