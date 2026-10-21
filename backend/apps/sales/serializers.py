"""Serializers of sales and cash, shared by the owner and the employee APIs.

Money is a string ("14250000.00"), days are company-local `YYYY-MM-DD`, moments ISO 8601.
Private photos come as short-lived signed links (`apps.core.files`), checked again at download.
Employees never see a shift's expected cash or difference before a manager verified it while the
blind count is on (`ShiftSerializer` with `blind=True`).
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.files import PrivateFileSerializerField
from apps.core.money import MoneySerializerField
from apps.finance.models import Category, MoneyAccount
from apps.members.models import Membership
from apps.sales import cash, finance_bridge
from apps.sales.models import (
    CashMovement,
    CashShift,
    PaymentMethod,
    Register,
    Sale,
    SalesSettings,
)
from apps.sales.queries import m, person
from apps.sales.services import PaymentLine


class PersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "SalesPerson"


class RefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "SalesRef"


class BranchRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()

    class Meta:
        ref_name = "SalesBranchRef"


def branch_ref(branch) -> dict | None:
    if branch is None:
        return None
    return {"id": branch.pk, "name": branch.name, "code": branch.code}


def ref(obj) -> dict | None:
    if obj is None:
        return None
    return {"id": obj.pk, "name": str(getattr(obj, "name", obj))}


# Settings --------------------------------------------------------------------------------


class SettingsSerializer(serializers.ModelSerializer):
    cash_tolerance = MoneySerializerField(positive=False, min_value=0)
    big_payout_alert = MoneySerializerField(
        positive=False, min_value=0, allow_null=True, required=False
    )
    business_day_ends_at = serializers.TimeField(format="%H:%M")

    class Meta:
        ref_name = "SalesSettings"
        model = SalesSettings
        fields = (
            "business_day_ends_at",
            "cash_tolerance",
            "blind_cash_count",
            "require_z_photo",
            "require_terminal_photo",
            "mode",
            "handover_confirm_hours",
            "big_payout_alert",
            "late_open_minutes",
            "close_alert_minutes",
        )
        extra_kwargs = {
            "handover_confirm_hours": {"min_value": 0, "max_value": 72},
            "late_open_minutes": {"min_value": 1, "max_value": 240},
            "close_alert_minutes": {"min_value": 1, "max_value": 720},
        }


# Payment methods and tills ---------------------------------------------------------------


class PaymentMethodSerializer(serializers.ModelSerializer):
    account = serializers.SerializerMethodField()
    account_id = serializers.PrimaryKeyRelatedField(
        queryset=MoneyAccount.objects.none(),
        source="account",
        write_only=True,
        allow_null=True,
        required=False,
    )
    fee_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False
    )
    is_default = serializers.SerializerMethodField()

    class Meta:
        model = PaymentMethod
        fields = (
            "id",
            "name",
            "kind",
            "account",
            "account_id",
            "fee_percent",
            "is_active",
            "order",
            "is_default",
        )
        read_only_fields = ("id", "order", "is_default")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = self.context.get("company")
        if company is not None:
            self.fields["account_id"].queryset = MoneyAccount.objects.filter(
                company=company, is_active=True
            )

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_account(self, method) -> dict | None:
        return ref(method.account)

    def get_is_default(self, method) -> bool:
        return bool(method.system_code)


class ReorderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)

    class Meta:
        ref_name = "SalesReorder"


class RegisterSerializer(serializers.ModelSerializer):
    branch = serializers.SerializerMethodField()
    branch_id = serializers.IntegerField(write_only=True)
    cash_account = serializers.SerializerMethodField()
    cash_now = serializers.SerializerMethodField()
    open_shift = serializers.SerializerMethodField()

    class Meta:
        model = Register
        fields = (
            "id",
            "name",
            "branch",
            "branch_id",
            "fiscal_serial",
            "is_active",
            "order",
            "cash_account",
            "cash_now",
            "open_shift",
        )
        read_only_fields = ("id", "order", "cash_account", "cash_now", "open_shift")

    @extend_schema_field(BranchRefSerializer)
    def get_branch(self, register) -> dict:
        return branch_ref(register.branch)

    @extend_schema_field(RefSerializer)
    def get_cash_account(self, register) -> dict:
        return ref(register.cash_account)

    def _open(self, register):
        shifts = self.context.get("open_shifts")
        if shifts is not None:
            return shifts.get(register.pk)
        return (
            CashShift.objects.filter(register=register, status=CashShift.Status.OPEN)
            .select_related("cashier")
            .first()
        )

    @extend_schema_field(serializers.CharField())
    def get_cash_now(self, register) -> str:
        amounts = self.context.get("cash_now")
        if amounts is not None and register.pk in amounts:
            return m(amounts[register.pk])
        return m(cash.till_now(register, self._open(register)))

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_open_shift(self, register) -> dict | None:
        shift = self._open(register)
        if shift is None:
            return None
        return {
            "id": shift.pk,
            "code": shift.code,
            "cashier": person(shift.cashier),
            "since": shift.opened_at.isoformat(),
        }


# Shifts ----------------------------------------------------------------------------------


def _shift_photo(attr: str):
    del attr
    return PrivateFileSerializerField(check="sales.shift_photo", allow_null=True)


class ShiftListSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)
    branch = serializers.SerializerMethodField()
    register = serializers.SerializerMethodField()
    cashier = serializers.SerializerMethodField()
    verified_by = serializers.SerializerMethodField()
    net = serializers.SerializerMethodField()
    opening_float = MoneySerializerField(positive=False)
    expected_cash = MoneySerializerField(positive=False, allow_null=True)
    counted_cash = serializers.SerializerMethodField()
    difference = MoneySerializerField(positive=False, allow_null=True)
    has_photos = serializers.SerializerMethodField()

    class Meta:
        model = CashShift
        fields = (
            "id",
            "code",
            "number",
            "branch",
            "register",
            "cashier",
            "business_day",
            "status",
            "opened_at",
            "closed_at",
            "opening_float",
            "net",
            "receipts",
            "expected_cash",
            "counted_cash",
            "difference",
            "forced",
            "ai_mismatch",
            "verified_by",
            "verified_at",
            "has_photos",
        )
        read_only_fields = fields

    @extend_schema_field(BranchRefSerializer)
    def get_branch(self, shift) -> dict:
        return branch_ref(shift.branch)

    @extend_schema_field(RefSerializer)
    def get_register(self, shift) -> dict:
        return ref(shift.register)

    @extend_schema_field(PersonSerializer)
    def get_cashier(self, shift) -> dict:
        return person(shift.cashier)

    @extend_schema_field(PersonSerializer(allow_null=True))
    def get_verified_by(self, shift) -> dict | None:
        return person(shift.verified_by)

    def get_net(self, shift) -> str:
        net = getattr(shift, "net", None)
        if net is None:
            net = sum((p.sales - p.refunds for p in shift.payments.all()), 0)
        return m(net)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_counted_cash(self, shift) -> str | None:
        final = shift.final_count
        return m(final) if final is not None else None

    def get_has_photos(self, shift) -> bool:
        return bool(shift.z_photo or shift.terminal_photo)


class ShiftPaymentSerializer(serializers.Serializer):
    method = serializers.DictField()
    sales = serializers.CharField()
    refunds = serializers.CharField()
    net = serializers.CharField()
    receipts = serializers.IntegerField()


class MovementSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    amount = MoneySerializerField()
    branch = serializers.SerializerMethodField()
    register = serializers.SerializerMethodField()
    shift = serializers.SerializerMethodField()
    receiver = serializers.SerializerMethodField()
    to_account = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    confirmed_by = serializers.SerializerMethodField()
    photo = PrivateFileSerializerField(check="sales.movement_photo", allow_null=True)

    class Meta:
        model = CashMovement
        fields = (
            "id",
            "kind",
            "status",
            "amount",
            "currency",
            "branch",
            "register",
            "shift",
            "receiver",
            "to_account",
            "category",
            "reason",
            "photo",
            "created_by",
            "created_at",
            "confirmed_at",
            "confirmed_by",
            "declined_at",
            "decline_reason",
            "voided_at",
            "void_reason",
        )
        read_only_fields = fields

    @extend_schema_field(BranchRefSerializer)
    def get_branch(self, movement) -> dict:
        return branch_ref(movement.branch)

    @extend_schema_field(RefSerializer)
    def get_register(self, movement) -> dict:
        return ref(movement.register)

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_shift(self, movement) -> dict | None:
        if movement.shift_id is None:
            return None
        return {"id": movement.shift_id, "code": movement.shift.code}

    @extend_schema_field(PersonSerializer(allow_null=True))
    def get_receiver(self, movement) -> dict | None:
        return person(movement.receiver)

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_to_account(self, movement) -> dict | None:
        return ref(movement.to_account)

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_category(self, movement) -> dict | None:
        return ref(movement.category)

    @extend_schema_field(PersonSerializer)
    def get_created_by(self, movement) -> dict:
        return person(movement.created_by)

    @extend_schema_field(PersonSerializer(allow_null=True))
    def get_confirmed_by(self, movement) -> dict | None:
        return (
            person(movement.confirmed_by) if movement.kind == CashMovement.Kind.HANDOVER else None
        )


class ShiftDetailSerializer(ShiftListSerializer):
    """A shift with everything a manager checks: totals per method, the cash flow, both counts,
    photos, the AI reading, movements, the ledger rows and what the viewer may do."""

    payments = serializers.SerializerMethodField()
    cash_flow = serializers.SerializerMethodField()
    expected_float = MoneySerializerField(positive=False, allow_null=True)
    float_difference = serializers.SerializerMethodField()
    recount_cash = MoneySerializerField(positive=False, allow_null=True)
    cashier_counted = serializers.SerializerMethodField()
    fiscal_cash_total = MoneySerializerField(positive=False, allow_null=True)
    fiscal_card_total = MoneySerializerField(positive=False, allow_null=True)
    z_photo = _shift_photo("z_photo")
    terminal_photo = _shift_photo("terminal_photo")
    movements = serializers.SerializerMethodField()
    receipts_recorded = serializers.SerializerMethodField()
    ledger = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    closed_by = serializers.SerializerMethodField()
    tolerance = serializers.SerializerMethodField()

    class Meta(ShiftListSerializer.Meta):
        fields = (
            *ShiftListSerializer.Meta.fields,
            "payments",
            "cash_flow",
            "opening_count",
            "closing_count",
            "expected_float",
            "float_difference",
            "recount_cash",
            "cashier_counted",
            "fiscal_cash_total",
            "fiscal_card_total",
            "z_number",
            "z_photo",
            "terminal_photo",
            "ai_reading",
            "cashier_note",
            "note",
            "closed_by",
            "movements",
            "receipts_recorded",
            "ledger",
            "actions",
            "tolerance",
        )
        read_only_fields = fields

    @extend_schema_field(ShiftPaymentSerializer(many=True))
    def get_payments(self, shift) -> list[dict]:
        rows = []
        for payment in cash.payments_of(shift):
            rows.append(
                {
                    "method": {
                        "id": payment.method_id,
                        "name": payment.method.name,
                        "kind": payment.method.kind,
                    },
                    "sales": m(payment.sales),
                    "refunds": m(payment.refunds),
                    "net": m(payment.sales - payment.refunds),
                    "receipts": payment.receipts,
                    "fee": m(
                        finance_bridge.fee_of(payment.method, payment.sales - payment.refunds)
                    ),
                }
            )
        return rows

    @extend_schema_field(serializers.DictField())
    def get_cash_flow(self, shift) -> dict:
        """The expected-cash formula, term by term."""
        if shift.status == CashShift.Status.OPEN:
            cash_net = cash.receipts_cash_net(shift)
            sales, refunds = cash_net, 0
        else:
            sales = refunds = 0
            for payment in cash.payments_of(shift):
                if payment.method.kind == PaymentMethod.Kind.CASH:
                    sales += payment.sales
                    refunds += payment.refunds
        moves = cash.movement_totals_by_kind(shift)
        return {
            "opening_float": m(shift.opening_float),
            "cash_sales": m(sales),
            "cash_refunds": m(refunds),
            **{kind: m(moves.get(kind, 0)) for kind in CashMovement.Kind.values},
            "expected": m(
                cash.expected_cash(shift) if shift.expected_cash is None else shift.expected_cash
            ),
        }

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_float_difference(self, shift) -> str | None:
        if shift.expected_float is None:
            return None
        return m(shift.opening_float - shift.expected_float)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_cashier_counted(self, shift) -> str | None:
        return m(shift.counted_cash) if shift.counted_cash is not None else None

    @extend_schema_field(MovementSerializer(many=True))
    def get_movements(self, shift) -> list[dict]:
        rows = shift.movements.select_related(
            "branch",
            "register",
            "shift__branch",
            "receiver",
            "to_account",
            "category",
            "created_by",
            "confirmed_by",
        ).order_by("created_at")
        return MovementSerializer(rows, many=True, context=self.context).data

    def get_receipts_recorded(self, shift) -> int:
        return shift.sales.filter(voided_at__isnull=True).count()

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_ledger(self, shift) -> list[dict]:
        member: Membership | None = self.context.get("membership")
        from apps.members.permissions import Perm

        if member is None or not member.has_perm(Perm.FINANCE_VIEW):
            return []
        return [
            {
                "id": row.pk,
                "key": row.source_key,
                "kind": row.kind,
                "amount": m(row.amount),
                "account": ref(row.account),
                "category": ref(row.category),
                "occurred_on": row.occurred_on.isoformat(),
            }
            for row in finance_bridge.shift_rows(shift)
        ]

    @extend_schema_field(serializers.DictField())
    def get_actions(self, shift) -> dict:
        member: Membership | None = self.context.get("membership")
        from apps.members.permissions import Perm

        manage = bool(member and member.has_perm(Perm.SALES_MANAGE))
        own = bool(
            member and member.pk == shift.cashier_id and not (member.role and member.role.is_owner)
        )
        status = shift.status
        return {
            "verify": manage
            and not own
            and status in (CashShift.Status.CLOSED, CashShift.Status.DISPUTED),
            "dispute": manage
            and not own
            and status in (CashShift.Status.CLOSED, CashShift.Status.VERIFIED),
            "correct": manage and status != CashShift.Status.OPEN,
            "force_close": manage and status == CashShift.Status.OPEN,
        }

    @extend_schema_field(PersonSerializer(allow_null=True))
    def get_closed_by(self, shift) -> dict | None:
        return person(shift.closed_by)

    def get_tolerance(self, shift) -> str:
        from apps.sales.conf import get_settings

        return m(get_settings(shift.company).cash_tolerance)


# Writes ----------------------------------------------------------------------------------


class PaymentLineSerializer(serializers.Serializer):
    method_id = serializers.IntegerField()
    sales = MoneySerializerField(positive=False, min_value=0, required=False, default="0")
    refunds = MoneySerializerField(positive=False, min_value=0, required=False, default="0")
    receipts = serializers.IntegerField(min_value=0, max_value=1_000_000, required=False, default=0)


def payment_lines(company, rows: list[dict]) -> list[PaymentLine]:
    methods = {
        method.pk: method
        for method in PaymentMethod.objects.filter(
            company=company, pk__in=[row["method_id"] for row in rows]
        )
    }
    lines = []
    for row in rows:
        method = methods.get(row["method_id"])
        if method is None:
            raise serializers.ValidationError({"payments": [_("Unknown payment method.")]})
        lines.append(
            PaymentLine(
                method, row.get("sales") or 0, row.get("refunds") or 0, row.get("receipts") or 0
            )
        )
    return lines


class VerifySerializer(serializers.Serializer):
    recount_cash = MoneySerializerField(
        positive=False, min_value=0, required=False, allow_null=True
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)

    class Meta:
        ref_name = "SalesReason"


class OptionalReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ForceCloseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)
    counted_cash = MoneySerializerField(
        positive=False, min_value=0, required=False, allow_null=True
    )
    payments = PaymentLineSerializer(many=True, required=False)


class CorrectSerializer(serializers.Serializer):
    payments = PaymentLineSerializer(many=True)
    reason = serializers.CharField(max_length=300)
    counted_cash = MoneySerializerField(
        positive=False, min_value=0, required=False, allow_null=True
    )


class MovementWriteSerializer(serializers.Serializer):
    register_id = serializers.IntegerField(required=False)
    kind = serializers.ChoiceField(choices=CashMovement.Kind.choices)
    amount = MoneySerializerField()
    receiver_id = serializers.IntegerField(required=False, allow_null=True)
    to_account_id = serializers.IntegerField(required=False, allow_null=True)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    photo = serializers.ImageField(required=False, allow_null=True)


def movement_kwargs(company, data: dict) -> dict:
    """Ids from a movement request as rows of the company (unknown ids: validation errors)."""
    kwargs = {
        "kind": data["kind"],
        "amount": data["amount"],
        "reason": data.get("reason", ""),
        "photo": data.get("photo"),
    }
    if data.get("receiver_id"):
        kwargs["receiver"] = Membership.objects.filter(
            company=company, pk=data["receiver_id"]
        ).first()
        if kwargs["receiver"] is None:
            raise serializers.ValidationError({"receiver_id": [_("Pick someone from the team.")]})
    if data.get("to_account_id"):
        kwargs["to_account"] = MoneyAccount.objects.filter(
            company=company, pk=data["to_account_id"]
        ).first()
        if kwargs["to_account"] is None:
            raise serializers.ValidationError({"to_account_id": [_("Unknown account.")]})
    if data.get("category_id"):
        kwargs["category"] = Category.objects.filter(
            company=company, pk=data["category_id"]
        ).first()
        if kwargs["category"] is None:
            raise serializers.ValidationError({"category_id": [_("Unknown category.")]})
    return kwargs


class SalePaymentSerializer(serializers.Serializer):
    method_id = serializers.IntegerField()
    amount = MoneySerializerField()


class SaleWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Sale.Kind.choices, default=Sale.Kind.SALE)
    payments = SalePaymentSerializer(many=True)
    branch_id = serializers.IntegerField(required=False)
    register_id = serializers.IntegerField(required=False, allow_null=True)
    number = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")
    discount = MoneySerializerField(positive=False, min_value=0, required=False, default="0")
    sold_at = serializers.DateTimeField(required=False)


def sale_payments(company, rows: list[dict]):
    methods = {
        m_.pk: m_
        for m_ in PaymentMethod.objects.filter(
            company=company, pk__in=[r["method_id"] for r in rows]
        )
    }
    out = []
    for row in rows:
        method = methods.get(row["method_id"])
        if method is None:
            raise serializers.ValidationError({"payments": [_("Unknown payment method.")]})
        out.append((method, row["amount"]))
    return out


class SaleSerializer(serializers.ModelSerializer):
    total = MoneySerializerField()
    discount = MoneySerializerField(positive=False)
    branch = serializers.SerializerMethodField()
    register = serializers.SerializerMethodField()
    shift = serializers.SerializerMethodField()
    cashier = serializers.SerializerMethodField()
    performed_by = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = (
            "id",
            "kind",
            "number",
            "total",
            "discount",
            "branch",
            "register",
            "shift",
            "cashier",
            "performed_by",
            "sold_at",
            "business_day",
            "source",
            "note",
            "payments",
            "voided_at",
            "void_reason",
        )
        read_only_fields = fields

    @extend_schema_field(BranchRefSerializer)
    def get_branch(self, sale) -> dict:
        return branch_ref(sale.branch)

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_register(self, sale) -> dict | None:
        return ref(sale.register)

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_shift(self, sale) -> dict | None:
        return {"id": sale.shift_id, "code": sale.shift.code} if sale.shift_id else None

    @extend_schema_field(PersonSerializer(allow_null=True))
    def get_cashier(self, sale) -> dict | None:
        return person(sale.cashier)

    @extend_schema_field(PersonSerializer(allow_null=True))
    def get_performed_by(self, sale) -> dict | None:
        return person(sale.performed_by)

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_payments(self, sale) -> list[dict]:
        return [
            {
                "method": {"id": p.method_id, "name": p.method.name, "kind": p.method.kind},
                "amount": m(p.amount),
            }
            for p in sale.payments.all()
        ]


class TargetWriteSerializer(serializers.Serializer):
    month = serializers.DateField()
    amount = MoneySerializerField()
    branch_id = serializers.IntegerField(required=False, allow_null=True)
    member_id = serializers.IntegerField(required=False, allow_null=True)


class TargetAmountSerializer(serializers.Serializer):
    amount = MoneySerializerField()
