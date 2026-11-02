"""Shapes of the lifecycle endpoints (owner dashboard and mini app). The context carries
`membership` (the viewer) and `today`. A fine's amount shows only with `payroll.view`."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.files import signed_url
from apps.core.money import MoneySerializerField
from apps.hr.serializers import BranchRefSerializer, PersonRefSerializer
from apps.lifecycle import integrations, services
from apps.lifecycle.models import DisciplinaryRecord
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, person_ref


class FineSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = serializers.CharField(help_text='Money as a string, e.g. "200000.00".')
    currency = serializers.CharField()
    status = serializers.CharField(help_text="The adjustment's status in payroll.")

    class Meta:
        ref_name = "LifecycleFine"


class RecordSerializer(serializers.ModelSerializer):
    """A disciplinary record as HR sees it."""

    member = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()
    kind = serializers.ChoiceField(DisciplinaryRecord.Kind.choices, read_only=True)
    category = serializers.ChoiceField(DisciplinaryRecord.Category.choices, read_only=True)
    status = serializers.ChoiceField(DisciplinaryRecord.Status.choices, read_only=True)
    issued_by = serializers.SerializerMethodField()
    evidence = serializers.SerializerMethodField(help_text="Signed download link.")
    active = serializers.SerializerMethodField(help_text="Not withdrawn and not expired.")
    fine = serializers.SerializerMethodField(help_text="Only with payroll.view.")
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = DisciplinaryRecord
        fields = (
            "id",
            "member",
            "position",
            "home_branch",
            "kind",
            "category",
            "incident_on",
            "issued_on",
            "issued_by",
            "description",
            "evidence",
            "expires_on",
            "active",
            "status",
            "read_at",
            "acknowledged_at",
            "employee_response",
            "responded_at",
            "fine_id",
            "fine",
            "withdrawn_at",
            "withdraw_reason",
            "created_at",
            "can_edit",
        )
        read_only_fields = fields
        ref_name = "LifecycleRecord"

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, record: DisciplinaryRecord) -> dict:
        return person_ref(record.membership)

    def get_position(self, record: DisciplinaryRecord) -> str | None:
        position = record.membership.position
        return position.name if position else None

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, record: DisciplinaryRecord) -> dict | None:
        return branch_ref(record.membership.home_branch)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_issued_by(self, record: DisciplinaryRecord) -> dict | None:
        return person_ref(record.issued_by)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_evidence(self, record: DisciplinaryRecord) -> str | None:
        if not record.evidence:
            return None
        return signed_url(
            record.evidence,
            user=self.context["request"].user,
            company_id=record.company_id,
            check=f"lifecycle.evidence:{record.pk}",
        )

    def get_active(self, record: DisciplinaryRecord) -> bool:
        return is_active(record, self.context["today"])

    @extend_schema_field(FineSerializer(allow_null=True))
    def get_fine(self, record: DisciplinaryRecord) -> dict | None:
        viewer: Membership = self.context["membership"]
        if not record.fine_id or not viewer.has_perm(Perm.PAYROLL_VIEW):
            return None
        return integrations.fine_summary(record.company, record.fine_id)

    def get_can_edit(self, record: DisciplinaryRecord) -> bool:
        return services.may_discipline(self.context["membership"], record.membership)


def is_active(record: DisciplinaryRecord, today) -> bool:
    return record.status != DisciplinaryRecord.Status.WITHDRAWN and (
        record.expires_on is None or record.expires_on >= today
    )


class RecordWriteSerializer(serializers.Serializer):
    """A record's fields; multipart with `evidence` (a PDF or a picture)."""

    member_id = serializers.IntegerField(required=False, help_text="Whose record (on create).")
    kind = serializers.ChoiceField(DisciplinaryRecord.Kind.choices, required=False)
    category = serializers.ChoiceField(DisciplinaryRecord.Category.choices, required=False)
    incident_on = serializers.DateField(required=False)
    issued_on = serializers.DateField(required=False)
    description = serializers.CharField(max_length=2000, required=False)
    expires_on = serializers.DateField(
        required=False, allow_null=True, help_text="By default from the kind (3, 6, 12 months)."
    )
    evidence = serializers.FileField(required=False, allow_null=True)
    fine_amount = MoneySerializerField(
        required=False, allow_null=True, help_text="Also propose this fine in payroll."
    )

    class Meta:
        ref_name = "LifecycleRecordWrite"


class WithdrawSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)

    class Meta:
        ref_name = "LifecycleWithdraw"


class FineRequestSerializer(serializers.Serializer):
    amount = MoneySerializerField()

    class Meta:
        ref_name = "LifecycleFineRequest"


class SuspensionSerializer(serializers.Serializer):
    member = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()
    until = serializers.DateField(
        allow_null=True, help_text="The last suspended day; null: until reinstated."
    )
    since = serializers.DateTimeField(allow_null=True)
    reason = serializers.CharField()
    by = serializers.CharField(allow_null=True, help_text="Who suspended them.")
    can_reinstate = serializers.SerializerMethodField()

    class Meta:
        ref_name = "LifecycleSuspension"

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, row) -> dict:
        return person_ref(row["member"])

    def get_position(self, row) -> str | None:
        position = row["member"].position
        return position.name if position else None

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, row) -> dict | None:
        return branch_ref(row["member"].home_branch)

    def get_can_reinstate(self, row) -> bool:
        viewer: Membership = self.context["membership"]
        return viewer.has_perm(Perm.HR_SUSPEND) and viewer.pk != row["member"].pk


class SuspendSerializer(serializers.Serializer):
    member_id = serializers.IntegerField()
    until = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="The last suspended day; empty: until reinstated.",
    )
    reason = serializers.CharField(max_length=300)

    class Meta:
        ref_name = "LifecycleSuspend"


class MyRecordSerializer(serializers.ModelSerializer):
    """A record as the person reads it: no evidence file, no fine amount."""

    kind = serializers.ChoiceField(DisciplinaryRecord.Kind.choices, read_only=True)
    category = serializers.ChoiceField(DisciplinaryRecord.Category.choices, read_only=True)
    status = serializers.ChoiceField(DisciplinaryRecord.Status.choices, read_only=True)
    issued_by = serializers.SerializerMethodField()
    active = serializers.SerializerMethodField()
    has_fine = serializers.SerializerMethodField()

    class Meta:
        model = DisciplinaryRecord
        fields = (
            "id",
            "kind",
            "category",
            "incident_on",
            "issued_on",
            "issued_by",
            "description",
            "expires_on",
            "active",
            "status",
            "read_at",
            "acknowledged_at",
            "employee_response",
            "responded_at",
            "has_fine",
            "withdraw_reason",
        )
        read_only_fields = fields
        ref_name = "LifecycleMyRecord"

    def get_issued_by(self, record: DisciplinaryRecord) -> str | None:
        return str(record.issued_by) if record.issued_by else None

    def get_active(self, record: DisciplinaryRecord) -> bool:
        return is_active(record, self.context["today"])

    def get_has_fine(self, record: DisciplinaryRecord) -> bool:
        return bool(record.fine_id)


class ExplainSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000)

    class Meta:
        ref_name = "LifecycleExplain"
