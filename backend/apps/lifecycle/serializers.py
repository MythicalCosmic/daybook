"""Shapes of the lifecycle endpoints (owner dashboard and mini app). The context carries
`membership` (the viewer) and `today`. A fine's amount and anyone's pay show only with
`payroll.view` (the person sees their own in the mini app)."""

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.files import signed_url
from apps.core.money import MoneySerializerField
from apps.hr.serializers import BranchRefSerializer, PersonRefSerializer
from apps.lifecycle import integrations, job_changes, services, terminations
from apps.lifecycle.models import DisciplinaryRecord, HandoverItem, JobChange, Termination
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
        return services.may_discipline(
            self.context["membership"],
            record.membership,
            in_scope=self.context.get("in_scope", False),
        )


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


# Leaving (owner dashboard) -------------------------------------------------------------------
# Context: `states` ({termination id: terminations.item_states}), `blockers` (detail only).


def _position(member: Membership) -> str | None:
    return member.position.name if member.position_id else None


class ProgressSerializer(serializers.Serializer):
    done = serializers.IntegerField()
    total = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleHandoverProgress"


class HandoverItemSerializer(serializers.ModelSerializer):
    """One thing to hand over. `done`: ticked off, or done by itself (`auto`): equipment no
    longer held, no open tasks left."""

    kind = serializers.ChoiceField(HandoverItem.Kind.choices, read_only=True)
    done = serializers.SerializerMethodField()
    ticked = serializers.BooleanField(source="done", read_only=True)
    auto = serializers.SerializerMethodField(help_text="Done without being ticked off.")
    held = serializers.SerializerMethodField(help_text="Equipment they still hold (else null).")
    open_tasks = serializers.SerializerMethodField(help_text="The tasks item: how many are open.")
    done_by = serializers.SerializerMethodField()

    class Meta:
        model = HandoverItem
        fields = (
            "id",
            "kind",
            "title",
            "asset_id",
            "done",
            "ticked",
            "auto",
            "held",
            "open_tasks",
            "note",
            "done_at",
            "done_by",
        )
        read_only_fields = fields
        ref_name = "LifecycleHandoverItem"

    def _states(self, item: HandoverItem) -> dict | None:
        return (self.context.get("states") or {}).get(item.termination_id)

    def get_done(self, item: HandoverItem) -> bool:
        return terminations.item_done(item, self._states(item))

    def get_auto(self, item: HandoverItem) -> bool:
        return not item.done and terminations.item_done(item, self._states(item))

    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def get_held(self, item: HandoverItem) -> bool | None:
        states = self._states(item)
        if item.kind != HandoverItem.Kind.EQUIPMENT or states is None:
            return None
        return item.asset_id in states["held"]

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_open_tasks(self, item: HandoverItem) -> int | None:
        states = self._states(item)
        if item.kind != HandoverItem.Kind.TASKS or states is None:
            return None
        return states["open_tasks"]

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_done_by(self, item: HandoverItem) -> dict | None:
        return person_ref(item.done_by)


class LeavingEventSerializer(serializers.Serializer):
    kind = serializers.CharField(
        help_text="requested, started, agreed, moved, declined, withdrawn, completed, left"
    )
    at = serializers.DateTimeField()
    by = serializers.IntegerField(allow_null=True, help_text="Member id; null: the system.")
    name = serializers.CharField(allow_blank=True)
    day = serializers.DateField(allow_null=True)
    note = serializers.CharField(allow_blank=True)

    class Meta:
        ref_name = "LifecycleLeavingEvent"


class ExitInterviewSerializer(serializers.Serializer):
    reason = serializers.ChoiceField([(r, r) for r in terminations.EXIT_REASONS])
    better = serializers.CharField(allow_blank=True)
    recommend = serializers.CharField(allow_blank=True, help_text="yes, maybe, no or empty.")
    answered_at = serializers.DateTimeField()

    class Meta:
        ref_name = "LifecycleExitInterview"


class FinalPayslipSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField(help_text="The payroll run's status.")
    period = serializers.DateField()
    last_day = serializers.DateField(allow_null=True)
    net = serializers.CharField(allow_null=True, help_text="Only with payroll.view.")
    currency = serializers.CharField()

    class Meta:
        ref_name = "LifecycleFinalPayslip"


class LeavingActionsSerializer(serializers.Serializer):
    manage = serializers.BooleanField()
    agree = serializers.BooleanField()
    decline = serializers.BooleanField()
    withdraw = serializers.BooleanField()
    handover = serializers.BooleanField()
    retry = serializers.BooleanField()

    class Meta:
        ref_name = "LifecycleLeavingActions"


class TerminationRowSerializer(serializers.ModelSerializer):
    """A leaving in the list: who, why, the days and how far the handover is."""

    member = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()
    member_status = serializers.CharField(source="membership.status", read_only=True)
    kind = serializers.ChoiceField(Termination.Kind.choices, read_only=True)
    status = serializers.ChoiceField(Termination.Status.choices, read_only=True)
    initiated_by = serializers.SerializerMethodField(help_text="employee or company")
    notice_days = serializers.SerializerMethodField()
    handover = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = Termination
        fields = (
            "id",
            "member",
            "position",
            "home_branch",
            "member_status",
            "kind",
            "status",
            "initiated_by",
            "requested_at",
            "wished_last_day",
            "last_day",
            "left_on",
            "notice_days",
            "handover",
            "error",
            "can_manage",
            "created_at",
        )
        read_only_fields = fields
        ref_name = "LifecycleLeavingRow"

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, row: Termination) -> dict:
        return person_ref(row.membership)

    def get_position(self, row: Termination) -> str | None:
        return _position(row.membership)

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, row: Termination) -> dict | None:
        return branch_ref(row.membership.home_branch)

    def get_initiated_by(self, row: Termination) -> str:
        return "employee" if row.requested_by_id == row.membership_id else "company"

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_notice_days(self, row: Termination) -> int | None:
        return terminations.notice_days(row)

    @extend_schema_field(ProgressSerializer)
    def get_handover(self, row: Termination) -> dict:
        states = (self.context.get("states") or {}).get(row.pk)
        done, total = terminations.progress(row, states) if row.is_open else _frozen(row)
        return {"done": done, "total": total}

    def get_can_manage(self, row: Termination) -> bool:
        return terminations.may_manage(
            self.context["membership"], row.membership, in_scope=self.context.get("in_scope", False)
        )


def _frozen(row: Termination) -> tuple[int, int]:
    items = list(row.handover.all())
    return sum(1 for item in items if item.done), len(items)


class TerminationSerializer(TerminationRowSerializer):
    """A leaving with everything: the reason, what happened when, the handover list, the
    person's answers, HR's notes and the final payslip (its amount for payroll.view)."""

    requested_by = serializers.SerializerMethodField()
    agreed_by = serializers.SerializerMethodField()
    closed_by = serializers.SerializerMethodField()
    completed_by = serializers.SerializerMethodField()
    rehire = serializers.ChoiceField(Termination.Rehire.choices, read_only=True, allow_blank=True)
    leave_days = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    exit_interview = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    blockers = serializers.SerializerMethodField(help_text="What would stop the offboarding now.")
    final_run = serializers.SerializerMethodField()
    can = serializers.SerializerMethodField()

    class Meta(TerminationRowSerializer.Meta):
        fields = (
            *TerminationRowSerializer.Meta.fields,
            "reason",
            "requested_by",
            "agreed_by",
            "agreed_at",
            "closed_by",
            "closed_at",
            "close_reason",
            "completed_at",
            "completed_by",
            "final_payslip",
            "leave_days",
            "rehire",
            "notes",
            "exit_interview",
            "events",
            "items",
            "blockers",
            "left_open",
            "final_run",
            "can",
        )
        read_only_fields = fields
        ref_name = "LifecycleLeaving"

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_requested_by(self, row: Termination) -> dict | None:
        return person_ref(row.requested_by)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_agreed_by(self, row: Termination) -> dict | None:
        return person_ref(row.agreed_by)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_closed_by(self, row: Termination) -> dict | None:
        return person_ref(row.closed_by)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_completed_by(self, row: Termination) -> dict | None:
        return person_ref(row.completed_by)

    @extend_schema_field(ExitInterviewSerializer(allow_null=True))
    def get_exit_interview(self, row: Termination) -> dict | None:
        return row.exit_interview or None

    @extend_schema_field(LeavingEventSerializer(many=True))
    def get_events(self, row: Termination) -> list:
        return list(row.events or [])

    @extend_schema_field(HandoverItemSerializer(many=True))
    def get_items(self, row: Termination) -> list:
        items = sorted(
            row.handover.all(),
            key=lambda item: (terminations.ITEM_ORDER.get(item.kind, 9), item.order, item.pk),
        )
        return HandoverItemSerializer(items, many=True, context=self.context).data

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_blockers(self, row: Termination) -> list[str]:
        return list(self.context.get("blockers") or [])

    @extend_schema_field(FinalPayslipSerializer(allow_null=True))
    def get_final_run(self, row: Termination) -> dict | None:
        if row.status != Termination.Status.COMPLETED:
            return None
        found = integrations.final_run(row.membership)
        if found is not None and not self.context["membership"].has_perm(Perm.PAYROLL_VIEW):
            found["net"] = None
        return found

    @extend_schema_field(LeavingActionsSerializer)
    def get_can(self, row: Termination) -> dict:
        viewer: Membership = self.context["membership"]
        manage = viewer.has_perm(Perm.HR_TERMINATE) and terminations.may_manage(
            viewer, row.membership, in_scope=self.context.get("in_scope", False)
        )
        today = self.context["today"]
        return {
            "manage": manage,
            "agree": manage and row.is_open,
            "decline": manage and row.status == Termination.Status.REQUESTED,
            "withdraw": manage and row.is_open,
            "handover": manage and row.is_open,
            "retry": manage
            and row.status == Termination.Status.AGREED
            and bool(row.error)
            and row.last_day is not None
            and row.last_day <= today,
        }


class LeaveStartSerializer(serializers.Serializer):
    member_id = serializers.IntegerField()
    kind = serializers.ChoiceField(Termination.Kind.choices)
    last_day = serializers.DateField(help_text="Their last working day (today or later).")
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    leave_days = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        min_value=0,
        help_text="Unused leave days the final payslip pays out.",
    )
    final_payslip = serializers.BooleanField(required=False, default=True)

    class Meta:
        ref_name = "LifecycleLeaveStart"


class LeaveAgreeSerializer(serializers.Serializer):
    last_day = serializers.DateField(
        required=False, help_text="Their last working day; by default the one they asked for."
    )
    leave_days = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, min_value=0
    )
    # Left out (also from a form): as it is.
    final_payslip = serializers.BooleanField(required=False, allow_null=True, default=None)

    class Meta:
        ref_name = "LifecycleLeaveAgree"


class LeaveReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        ref_name = "LifecycleLeaveReason"


class LeaveUpdateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(Termination.Kind.choices, required=False)
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    rehire = serializers.ChoiceField(Termination.Rehire.choices, required=False, allow_blank=True)
    leave_days = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, min_value=0
    )
    final_payslip = serializers.BooleanField(required=False)

    class Meta:
        ref_name = "LifecycleLeaveUpdate"


class HandoverAddSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    kind = serializers.ChoiceField(
        [(kind, kind) for kind in terminations.ADDABLE], required=False, default="other"
    )

    class Meta:
        ref_name = "LifecycleHandoverAdd"


class HandoverSetSerializer(serializers.Serializer):
    done = serializers.BooleanField(required=False)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        ref_name = "LifecycleHandoverSet"


class LeavingCountsSerializer(serializers.Serializer):
    requested = serializers.IntegerField()
    agreed = serializers.IntegerField()
    completed = serializers.IntegerField()
    closed = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleLeavingCounts"


# Job changes (owner dashboard) ---------------------------------------------------------------


class NamedRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "LifecycleNamed"


class JobPaySerializer(serializers.Serializer):
    amount = serializers.CharField(help_text='Money as a string, e.g. "5200000.00".')
    currency = serializers.CharField()
    pay_type = serializers.CharField(help_text="monthly, daily, hourly or per_task.")

    class Meta:
        ref_name = "LifecycleJobPay"


class JobSideSerializer(serializers.Serializer):
    """A job as it was or became: the pay only for payroll.view."""

    position = NamedRefSerializer(allow_null=True)
    branch = NamedRefSerializer(allow_null=True)
    branches = NamedRefSerializer(many=True)
    department = NamedRefSerializer(allow_null=True)
    role = NamedRefSerializer(allow_null=True)
    pay = JobPaySerializer(allow_null=True)

    class Meta:
        ref_name = "LifecycleJobSide"


def _live(kind: str, ref, names: dict) -> dict | None:
    if not isinstance(ref, dict):
        return None
    return {"id": ref.get("id"), "name": names.get((kind, ref.get("id")), ref.get("name") or "")}


def job_side(data: dict | None, *, show_pay: bool, names: dict) -> dict:
    """One side of a change as the client reads it: today's names, the pay only when shown."""
    data = dict(data or {})
    return {
        "position": _live("position", data.get("position"), names),
        "branch": _live("branch", data.get("branch"), names),
        "branches": [
            found
            for found in (_live("branch", ref, names) for ref in data.get("branches") or [])
            if found is not None
        ],
        "department": _live("department", data.get("department"), names),
        "role": _live("role", data.get("role"), names),
        "pay": data.get("pay") if show_pay else None,
    }


def _names(serializer, change: JobChange) -> dict:
    """Today's names for the changes being shown, read once per response."""
    context = serializer.context
    if "names" not in context:
        root = serializer.root.instance if serializer.root is not None else None
        changes = list(root) if isinstance(root, (list, tuple, QuerySet)) else [change]
        if change not in changes:
            changes.append(change)
        context["names"] = job_changes.live_names(changes)
    return context["names"]


class JobChangeActionsSerializer(serializers.Serializer):
    decide = serializers.BooleanField()
    cancel = serializers.BooleanField()
    retry = serializers.BooleanField()

    class Meta:
        ref_name = "LifecycleJobChangeActions"


class JobChangeSerializer(serializers.ModelSerializer):
    """A job change: who, from when, what it was and what it becomes (pay for payroll.view)."""

    member = serializers.SerializerMethodField()
    position_now = serializers.SerializerMethodField(help_text="Their job title today.")
    home_branch = serializers.SerializerMethodField()
    member_status = serializers.CharField(source="membership.status", read_only=True)
    status = serializers.ChoiceField(JobChange.Status.choices, read_only=True)
    parts = serializers.ListField(child=serializers.CharField(), read_only=True)
    before = serializers.SerializerMethodField()
    after = serializers.SerializerMethodField()
    has_pay = serializers.SerializerMethodField(help_text="The pay changes (shown or not).")
    proposed_by = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()
    upcoming = serializers.SerializerMethodField(help_text="Approved, its day still to come.")
    can = serializers.SerializerMethodField()

    class Meta:
        model = JobChange
        fields = (
            "id",
            "member",
            "position_now",
            "home_branch",
            "member_status",
            "effective_on",
            "status",
            "parts",
            "before",
            "after",
            "has_pay",
            "reason",
            "proposed_by",
            "created_at",
            "decided_by",
            "decided_at",
            "decision_note",
            "applied_at",
            "error",
            "upcoming",
            "can",
        )
        read_only_fields = fields
        ref_name = "LifecycleJobChange"

    def _show_pay(self) -> bool:
        return self.context["membership"].has_perm(Perm.PAYROLL_VIEW)

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, change: JobChange) -> dict:
        return person_ref(change.membership)

    def get_position_now(self, change: JobChange) -> str | None:
        return _position(change.membership)

    @extend_schema_field(BranchRefSerializer(allow_null=True))
    def get_home_branch(self, change: JobChange) -> dict | None:
        return branch_ref(change.membership.home_branch)

    @extend_schema_field(JobSideSerializer)
    def get_before(self, change: JobChange) -> dict:
        return job_side(change.before, show_pay=self._show_pay(), names=_names(self, change))

    @extend_schema_field(JobSideSerializer)
    def get_after(self, change: JobChange) -> dict:
        return job_side(change.after, show_pay=self._show_pay(), names=_names(self, change))

    def get_has_pay(self, change: JobChange) -> bool:
        return "pay" in (change.parts or [])

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_proposed_by(self, change: JobChange) -> dict | None:
        return person_ref(change.proposed_by)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_decided_by(self, change: JobChange) -> dict | None:
        return person_ref(change.decided_by)

    def get_upcoming(self, change: JobChange) -> bool:
        return change.status == JobChange.Status.APPROVED and (
            change.effective_on > self.context["today"]
        )

    @extend_schema_field(JobChangeActionsSerializer)
    def get_can(self, change: JobChange) -> dict:
        viewer: Membership = self.context["membership"]
        in_scope = self.context.get("in_scope", False)
        decide = job_changes.may_decide(viewer, change, in_scope=in_scope)
        proposer = change.proposed_by_id == viewer.pk and job_changes.may_propose(
            viewer, change.membership, in_scope=in_scope
        )
        is_open = change.status in job_changes.OPEN
        return {
            "decide": decide and change.status == JobChange.Status.PROPOSED,
            "cancel": is_open and (decide or proposer),
            "retry": decide and change.status == JobChange.Status.APPROVED and bool(change.error),
        }


class JobChangeWriteSerializer(serializers.Serializer):
    """What changes from when. Leave a part out to keep it; `department_id: null` takes them out
    of their department, `position_id: null` leaves them without a position."""

    member_id = serializers.IntegerField()
    effective_on = serializers.DateField(help_text="The day it takes effect (today or later).")
    reason = serializers.CharField(max_length=1000)
    position_id = serializers.IntegerField(required=False, allow_null=True)
    branch_id = serializers.IntegerField(required=False, help_text="The new home branch.")
    department_id = serializers.IntegerField(required=False, allow_null=True)
    pay_amount = MoneySerializerField(required=False, allow_null=True)
    pay_type = serializers.ChoiceField(
        [(kind, kind) for kind in ("monthly", "daily", "hourly", "per_task")],
        required=False,
        allow_blank=True,
    )
    approve = serializers.BooleanField(
        required=False, default=False, help_text="Approve it at once when you may."
    )

    class Meta:
        ref_name = "LifecycleJobChangeWrite"


class JobChangeReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        ref_name = "LifecycleJobChangeReason"


class JobChangeCountsSerializer(serializers.Serializer):
    proposed = serializers.IntegerField()
    upcoming = serializers.IntegerField()
    applied = serializers.IntegerField()
    closed = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleJobChangeCounts"


class OpenChangeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    effective_on = serializers.DateField()
    status = serializers.CharField()
    parts = serializers.ListField(child=serializers.CharField())

    class Meta:
        ref_name = "LifecycleOpenChange"


class CurrentJobSerializer(serializers.Serializer):
    """Someone's job now, for the "Change job" dialog: the pay only for payroll.view."""

    member = PersonRefSerializer()
    position = NamedRefSerializer(allow_null=True)
    home_branch = BranchRefSerializer(allow_null=True)
    branches = BranchRefSerializer(many=True)
    department = NamedRefSerializer(allow_null=True)
    role = serializers.CharField(allow_null=True)
    pay = JobPaySerializer(allow_null=True)
    may_change_pay = serializers.BooleanField(help_text="payroll is on and you manage pay")
    departments = NamedRefSerializer(many=True)
    open_changes = OpenChangeSerializer(many=True)

    class Meta:
        ref_name = "LifecycleCurrentJob"


class CareerSerializer(serializers.Serializer):
    """Person 360's career: when they were hired, their job changes (applied and to come) and
    their leaving."""

    hired_on = serializers.DateField(allow_null=True)
    changes = JobChangeSerializer(many=True)
    leavings = TerminationRowSerializer(many=True)

    class Meta:
        ref_name = "LifecycleCareer"


# The mini app: my leaving and my career ------------------------------------------------------


class MyHandoverItemSerializer(serializers.ModelSerializer):
    kind = serializers.ChoiceField(HandoverItem.Kind.choices, read_only=True)
    done = serializers.SerializerMethodField()
    open_tasks = serializers.SerializerMethodField()

    class Meta:
        model = HandoverItem
        fields = ("id", "kind", "title", "done", "open_tasks")
        read_only_fields = fields
        ref_name = "LifecycleMyHandoverItem"

    def _states(self, item: HandoverItem) -> dict | None:
        return (self.context.get("states") or {}).get(item.termination_id)

    def get_done(self, item: HandoverItem) -> bool:
        return terminations.item_done(item, self._states(item))

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_open_tasks(self, item: HandoverItem) -> int | None:
        states = self._states(item)
        if item.kind != HandoverItem.Kind.TASKS or states is None:
            return None
        return states["open_tasks"]


class MyLeavingSerializer(serializers.ModelSerializer):
    """My leaving as I read it: no HR notes, nothing about others."""

    kind = serializers.ChoiceField(Termination.Kind.choices, read_only=True)
    status = serializers.ChoiceField(Termination.Status.choices, read_only=True)
    mine = serializers.SerializerMethodField(help_text="I asked for it (a resignation).")
    closed_by_me = serializers.SerializerMethodField()
    agreed_by = serializers.SerializerMethodField()
    notice_days = serializers.SerializerMethodField()
    handover = serializers.SerializerMethodField()
    exit_interview = serializers.SerializerMethodField()
    can_withdraw = serializers.SerializerMethodField()
    can_answer = serializers.SerializerMethodField()

    class Meta:
        model = Termination
        fields = (
            "id",
            "kind",
            "status",
            "mine",
            "wished_last_day",
            "last_day",
            "left_on",
            "reason",
            "requested_at",
            "agreed_at",
            "agreed_by",
            "close_reason",
            "closed_by_me",
            "notice_days",
            "handover",
            "exit_interview",
            "can_withdraw",
            "can_answer",
        )
        read_only_fields = fields
        ref_name = "LifecycleMyLeaving"

    def get_mine(self, row: Termination) -> bool:
        return row.requested_by_id == row.membership_id

    def get_closed_by_me(self, row: Termination) -> bool:
        return row.closed_by_id is not None and row.closed_by_id == row.membership_id

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_agreed_by(self, row: Termination) -> str | None:
        return str(row.agreed_by) if row.agreed_by else None

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_notice_days(self, row: Termination) -> int | None:
        return terminations.notice_days(row)

    @extend_schema_field(MyHandoverItemSerializer(many=True))
    def get_handover(self, row: Termination) -> list:
        items = sorted(
            row.handover.all(),
            key=lambda item: (terminations.ITEM_ORDER.get(item.kind, 9), item.order, item.pk),
        )
        return MyHandoverItemSerializer(items, many=True, context=self.context).data

    @extend_schema_field(ExitInterviewSerializer(allow_null=True))
    def get_exit_interview(self, row: Termination) -> dict | None:
        return row.exit_interview or None

    def get_can_withdraw(self, row: Termination) -> bool:
        if row.status == Termination.Status.REQUESTED:
            return True
        return row.status == Termination.Status.AGREED and (
            row.last_day is not None and self.context["today"] < row.last_day
        )

    def get_can_answer(self, row: Termination) -> bool:
        return row.is_open


class MyLeavingStateSerializer(serializers.Serializer):
    current = MyLeavingSerializer(allow_null=True)
    can_request = serializers.BooleanField()
    notice_days = serializers.IntegerField(help_text="The usual notice, in days.")
    today = serializers.DateField()

    class Meta:
        ref_name = "LifecycleMyLeavingState"


class LeaveRequestSerializer(serializers.Serializer):
    wished_last_day = serializers.DateField(help_text="My last working day (today or later).")
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    class Meta:
        ref_name = "LifecycleLeaveRequest"


class ExitAnswerSerializer(serializers.Serializer):
    reason = serializers.ChoiceField([(r, r) for r in terminations.EXIT_REASONS])
    better = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    recommend = serializers.ChoiceField(
        [(r, r) for r in terminations.RECOMMEND], required=False, allow_blank=True
    )

    class Meta:
        ref_name = "LifecycleExitAnswer"


class MyJobChangeSerializer(serializers.ModelSerializer):
    """One of my job changes: what it was and became, my own pay included."""

    status = serializers.ChoiceField(JobChange.Status.choices, read_only=True)
    parts = serializers.ListField(child=serializers.CharField(), read_only=True)
    before = serializers.SerializerMethodField()
    after = serializers.SerializerMethodField()

    class Meta:
        model = JobChange
        fields = ("id", "effective_on", "status", "parts", "before", "after", "applied_at")
        read_only_fields = fields
        ref_name = "LifecycleMyJobChange"

    @extend_schema_field(JobSideSerializer)
    def get_before(self, change: JobChange) -> dict:
        return job_side(change.before, show_pay=True, names=_names(self, change))

    @extend_schema_field(JobSideSerializer)
    def get_after(self, change: JobChange) -> dict:
        return job_side(change.after, show_pay=True, names=_names(self, change))


class MyCareerSerializer(serializers.Serializer):
    hired_on = serializers.DateField(allow_null=True)
    position = serializers.CharField(allow_null=True)
    branch = serializers.CharField(allow_null=True)
    department = serializers.CharField(allow_null=True)
    changes = MyJobChangeSerializer(many=True)

    class Meta:
        ref_name = "LifecycleMyCareer"
