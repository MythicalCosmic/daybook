"""Employee (mini app) endpoints of sales and cash; routed in `urls.py` under
`/api/v1/companies/<id>/sales/` (docs/PLAN-OWNER.md §4.8, the E rows).

Kassa runs on these: `shifts/current/` is everything the screen needs in one call; then open,
movements, receipts and close. While the blind count is on, nothing a cashier can read tells them
how much cash there should be (no expected cash, no difference) until a manager verified the
shift. Handovers are answered by their receiver, who needs no permission.
"""

import json
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.companies.models import Feature
from apps.core.files import signed_url
from apps.core.money import MoneySerializerField
from apps.finance.models import Category
from apps.members import scope
from apps.members.api import IsCompanyMember, requires
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.sales import cash, queries, services
from apps.sales.conf import get_settings
from apps.sales.models import CashMovement, CashShift, PaymentMethod, Register, Sale
from apps.sales.queries import m, person
from apps.sales.serializers import (
    MovementSerializer,
    OptionalReasonSerializer,
    PaymentLineSerializer,
    ReasonSerializer,
    SalePaymentSerializer,
    branch_ref,
    movement_kwargs,
    payment_lines,
    ref,
    sale_payments,
)

# A close repeated this soon by the same person (a lost response on bad signal) answers with the
# shift as closed instead of an error.
RETRY_WINDOW = timedelta(minutes=15)


class SalesOn(BasePermission):
    def has_permission(self, request, view):
        if not view.membership.company.has_feature(Feature.SALES):
            raise NotFound
        return True


OPERATE = (IsAuthenticated, IsCompanyMember, SalesOn, requires(Perm.SALES_OPERATE))
SELF = (IsAuthenticated, IsCompanyMember, SalesOn)


@extend_schema_field(OpenApiTypes.ANY)
class JSONValueField(serializers.Field):
    """A list or object, also as a JSON string (multipart forms send everything as text)."""

    def to_internal_value(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data or "null")
            except ValueError:
                raise ValidationError(_("This isn't readable.")) from None
        return data

    def to_representation(self, value):
        return value


# Shapes ------------------------------------------------------------------------------------


def shows_result(shift: CashShift, blind: bool) -> bool:
    """Whether the cashier may see expected cash and the difference of their shift."""
    if shift.status == CashShift.Status.VERIFIED:
        return True
    return not blind and shift.status != CashShift.Status.OPEN


def shift_data(shift: CashShift, request, *, blind: bool, detail: bool = False) -> dict:
    payments = cash.payments_of(shift)
    net = sum((p.sales - p.refunds for p in payments), 0)
    result = shows_result(shift, blind)
    data = {
        "id": shift.pk,
        "code": shift.code,
        "status": shift.status,
        "branch": branch_ref(shift.branch),
        "register": ref(shift.register),
        "business_day": shift.business_day.isoformat(),
        "opened_at": shift.opened_at.isoformat(),
        "closed_at": shift.closed_at.isoformat() if shift.closed_at else None,
        "opening_float": m(shift.opening_float),
        "net": m(net),
        "receipts": shift.receipts,
        "counted_cash": m(shift.counted_cash) if shift.counted_cash is not None else None,
        "expected_cash": m(shift.expected_cash)
        if result and shift.expected_cash is not None
        else None,
        "difference": m(shift.difference) if result and shift.difference is not None else None,
        "verified_at": shift.verified_at.isoformat() if shift.verified_at else None,
        "verified_by": person(shift.verified_by) if shift.verified_by_id else None,
        "note": shift.note
        if shift.status in (CashShift.Status.DISPUTED, CashShift.Status.VERIFIED)
        else "",
        "forced": shift.forced,
    }
    if detail:
        movements = shift.movements.select_related(
            "branch",
            "register",
            "shift__branch",
            "receiver",
            "to_account",
            "category",
            "created_by",
            "confirmed_by",
        ).order_by("-created_at")
        data |= {
            "payments": [
                {
                    "method": {"id": p.method_id, "name": p.method.name, "kind": p.method.kind},
                    "sales": m(p.sales),
                    "refunds": m(p.refunds),
                    "receipts": p.receipts,
                }
                for p in payments
            ],
            "opening_count": shift.opening_count,
            "closing_count": shift.closing_count,
            "z_number": shift.z_number,
            "cashier_note": shift.cashier_note,
            "movements": MovementSerializer(
                movements, many=True, context={"request": request}
            ).data,
            "moved": {
                kind: m(total) for kind, total in cash.movement_totals_by_kind(shift).items()
            },
            "receipts_recorded": _receipts_recorded(shift),
            "entries": _entries(shift),
            "photos": {
                "z_photo": _signed(shift, "z_photo", request),
                "terminal_photo": _signed(shift, "terminal_photo", request),
            },
        }
    return data


def _receipts_recorded(shift: CashShift) -> dict:
    found = cash.receipts_by_method(shift)
    return {
        str(method_id): {
            "sales": m(row["sales"]),
            "refunds": m(row["refunds"]),
            "receipts": row["receipts"],
        }
        for method_id, row in found.items()
    }


def _entries(shift: CashShift, limit: int = 30) -> list[dict]:
    """The shift's latest single receipts (receipts mode), so a mistyped one can be voided."""
    rows = shift.sales.prefetch_related("payments__method").order_by("-sold_at", "-pk")[:limit]
    return [
        {
            "id": sale.pk,
            "kind": sale.kind,
            "total": m(sale.total),
            "number": sale.number,
            "sold_at": sale.sold_at.isoformat(),
            "voided_at": sale.voided_at.isoformat() if sale.voided_at else None,
            "methods": [
                {"id": line.method_id, "name": line.method.name, "amount": m(line.amount)}
                for line in sale.payments.all()
            ],
        }
        for sale in rows
    ]


def _signed(shift: CashShift, attr: str, request) -> str | None:
    file = getattr(shift, attr)
    if not file:
        return None
    return signed_url(
        file, user=request.user, company_id=shift.company_id, check=f"sales.shift_photo:{shift.pk}"
    )


def handover_data(movement: CashMovement) -> dict:
    return {
        "id": movement.pk,
        "amount": m(movement.amount),
        "currency": movement.currency,
        "from": person(movement.created_by),
        "branch": branch_ref(movement.branch),
        "register": ref(movement.register),
        "reason": movement.reason,
        "created_at": movement.created_at.isoformat(),
    }


# shifts/current/ -----------------------------------------------------------------------------


class CurrentView(APIView):
    """Everything Kassa needs: my open shift (or the tills I can open), how the company records
    sales, the payment methods, who can receive cash, payout categories, handovers waiting for
    me and my last shifts."""

    permission_classes = OPERATE
    membership: Membership

    @extend_schema(
        responses=inline_serializer(
            "KassaCurrent", {"shift": serializers.DictField(allow_null=True)}
        )
    )
    def get(self, request, company_id):
        member = self.membership
        company = member.company
        settings = get_settings(company)
        shift = queries.current_shift(member)
        mine = scope.branch_ids(member)
        branch_ids = [b.pk for b in member.branches.all()] or (
            [member.home_branch_id] if member.home_branch_id else []
        )
        if mine is None and not branch_ids:
            branch_ids = list(company.branches.filter(is_active=True).values_list("pk", flat=True))
        registers = (
            Register.objects.for_company(company)
            .filter(is_active=True, branch__is_active=True, branch_id__in=branch_ids)
            .select_related("branch")
        )
        busy = {
            row.register_id: row
            for row in CashShift.objects.filter(
                register__in=registers, status=CashShift.Status.OPEN
            ).select_related("cashier")
        }
        people = (
            Membership.objects.for_company(company)
            .filter(status=Membership.Status.APPROVED)
            .exclude(pk=member.pk)
            .select_related("role")
            .prefetch_related("branches")
        )
        receivers = []
        for person_ in people.order_by("first_name", "last_name"):
            shared = {b.pk for b in person_.branches.all()} & set(branch_ids)
            if not (person_.has_perm(Perm.SALES_MANAGE) or person_.has_perm(Perm.FINANCE_RECORD)):
                continue
            if shared or scope.branch_ids(person_) is None:
                receivers.append(
                    {
                        "id": person_.pk,
                        "name": str(person_),
                        "role": person_.role.name if person_.role else "",
                    }
                )
        recent = (
            CashShift.objects.filter(cashier=member)
            .exclude(status=CashShift.Status.OPEN)
            .select_related("branch", "register", "verified_by")
            .prefetch_related("payments__method")[:5]
        )
        return Response(
            {
                "shift": shift_data(shift, request, blind=settings.blind_cash_count, detail=True)
                if shift
                else None,
                "settings": {
                    "mode": settings.mode,
                    "blind_cash_count": settings.blind_cash_count,
                    "require_z_photo": settings.require_z_photo,
                    "require_terminal_photo": settings.require_terminal_photo,
                    "currency": company.base_currency,
                },
                "registers": [
                    {
                        "id": r.pk,
                        "name": r.name,
                        "branch": branch_ref(r.branch),
                        "busy": {"code": busy[r.pk].code, "cashier": str(busy[r.pk].cashier)}
                        if r.pk in busy
                        else None,
                    }
                    for r in registers.order_by("branch__order", "order", "name")
                ],
                "methods": [
                    {"id": p.pk, "name": p.name, "kind": p.kind}
                    for p in PaymentMethod.objects.for_company(company)
                    .filter(is_active=True)
                    .order_by("order", "pk")
                ],
                "receivers": receivers,
                "categories": [
                    {"id": c.pk, "name": c.name, "code": c.system_code}
                    for c in Category.objects.filter(
                        company=company, kind=Category.Kind.EXPENSE, is_active=True
                    )
                    .exclude(
                        system_code__in=[
                            "salaries",
                            "payroll_taxes",
                            "taxes",
                            "bad_debts",
                            "fx_diff",
                            "cash_shortage",
                            "bank_fees",
                        ]
                    )
                    .order_by("order", "name")
                ],
                "pending_handovers": [
                    handover_data(row) for row in queries.pending_handovers_for(member)
                ],
                "recent": [
                    shift_data(row, request, blind=settings.blind_cash_count) for row in recent
                ],
            }
        )


# shifts/ -------------------------------------------------------------------------------------


class OpenSerializer(serializers.Serializer):
    register_id = serializers.IntegerField()
    opening_count = JSONValueField(required=False)
    opening_float = MoneySerializerField(
        positive=False, min_value=0, required=False, allow_null=True
    )


class ShiftListView(ListAPIView):
    """My shifts, newest first (POST opens one). The difference shows once a manager verified
    it."""

    permission_classes = OPERATE
    membership: Membership

    def get_queryset(self):
        return (
            CashShift.objects.filter(cashier=self.membership)
            .select_related("branch", "register", "verified_by")
            .prefetch_related("payments__method")
        )

    @extend_schema(
        responses=inline_serializer(
            "KassaShiftPage", {"results": serializers.ListField(child=serializers.DictField())}
        )
    )
    def get(self, request, company_id):
        blind = get_settings(self.membership.company).blind_cash_count
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([shift_data(row, request, blind=blind) for row in page])

    @extend_schema(
        request=OpenSerializer,
        responses=inline_serializer("KassaShift", {"id": serializers.IntegerField()}),
    )
    def post(self, request, company_id):
        data = OpenSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        member = self.membership
        register = (
            Register.objects.for_company(member.company)
            .select_related("branch", "cash_account")
            .filter(pk=data.validated_data["register_id"])
            .first()
        )
        allowed = {b.pk for b in member.branches.all()} | (
            {member.home_branch_id} if member.home_branch_id else set()
        )
        if register is None or (
            scope.branch_ids(member) is not None and register.branch_id not in allowed
        ):
            raise ValidationError({"register_id": [_("Pick one of your branch's tills.")]})
        shift = services.open_shift(
            by=member,
            register=register,
            opening_count=data.validated_data.get("opening_count"),
            opening_float=data.validated_data.get("opening_float"),
        )
        blind = get_settings(member.company).blind_cash_count
        return Response(
            shift_data(shift, request, blind=blind, detail=True), status=status.HTTP_201_CREATED
        )


class ShiftDetailView(APIView):
    permission_classes = OPERATE
    membership: Membership

    @extend_schema(
        responses=inline_serializer("KassaShiftDetail", {"id": serializers.IntegerField()})
    )
    def get(self, request, company_id, pk):
        shift = (
            CashShift.objects.filter(cashier=self.membership, pk=pk)
            .select_related("branch", "register")
            .first()
        )
        if shift is None:
            raise NotFound
        blind = get_settings(self.membership.company).blind_cash_count
        return Response(shift_data(shift, request, blind=blind, detail=True))


class CloseSerializer(serializers.Serializer):
    payments = JSONValueField()
    closing_count = JSONValueField(required=False)
    counted_cash = MoneySerializerField(
        positive=False, min_value=0, required=False, allow_null=True
    )
    receipts = serializers.IntegerField(
        min_value=0, max_value=1_000_000, required=False, allow_null=True
    )
    z_number = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")
    fiscal_cash_total = MoneySerializerField(
        positive=False, min_value=0, required=False, allow_null=True
    )
    fiscal_card_total = MoneySerializerField(
        positive=False, min_value=0, required=False, allow_null=True
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    z_photo = serializers.ImageField(required=False, allow_null=True)
    terminal_photo = serializers.ImageField(required=False, allow_null=True)

    def validate_payments(self, value):
        if not isinstance(value, list):
            raise ValidationError(_("Give the totals per payment method."))
        rows = PaymentLineSerializer(data=value, many=True)
        rows.is_valid(raise_exception=True)
        return rows.validated_data


class CloseView(APIView):
    """Close my shift: totals per method from the Z-report, the cash I counted, photos.
    Never answers with the expected cash while the blind count is on."""

    permission_classes = OPERATE
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    membership: Membership

    @extend_schema(
        request=CloseSerializer,
        responses=inline_serializer("KassaClosed", {"id": serializers.IntegerField()}),
    )
    def post(self, request, company_id, pk):
        member = self.membership
        shift = (
            CashShift.objects.filter(cashier=member, pk=pk)
            .select_related("branch", "register")
            .first()
        )
        if shift is None:
            raise NotFound
        blind = get_settings(member.company).blind_cash_count
        if shift.status != CashShift.Status.OPEN:
            recent = shift.closed_at and timezone.now() - shift.closed_at < RETRY_WINDOW
            if shift.closed_by_id == member.pk and recent:
                return Response(shift_data(shift, request, blind=blind, detail=True))
            raise ValidationError({"detail": _("This shift is already closed.")})
        data = CloseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        shift = services.close_shift(
            shift,
            by=member,
            payments=payment_lines(member.company, values["payments"]),
            counted_cash=values.get("counted_cash"),
            closing_count=values.get("closing_count"),
            receipts=values.get("receipts"),
            z_number=values.get("z_number", ""),
            fiscal_cash_total=values.get("fiscal_cash_total"),
            fiscal_card_total=values.get("fiscal_card_total"),
            z_photo=values.get("z_photo"),
            terminal_photo=values.get("terminal_photo"),
            note=values.get("note", ""),
        )
        return Response(shift_data(shift, request, blind=blind, detail=True))


class AppMovementSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[(k, k) for k in services.APP_MOVEMENTS])
    amount = MoneySerializerField()
    receiver_id = serializers.IntegerField(required=False, allow_null=True)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    photo = serializers.ImageField(required=False, allow_null=True)


class MovementView(APIView):
    """A payout (with a receipt photo), a handover to a named person, or cash to or from the
    safe, on my open shift."""

    permission_classes = OPERATE
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    membership: Membership

    @extend_schema(request=AppMovementSerializer, responses=MovementSerializer)
    def post(self, request, company_id, pk):
        member = self.membership
        shift = (
            CashShift.objects.filter(cashier=member, pk=pk, status=CashShift.Status.OPEN)
            .select_related("register")
            .first()
        )
        if shift is None:
            raise ValidationError({"detail": _("Open a shift first.")})
        data = AppMovementSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        movement = services.record_movement(
            by=member,
            register=shift.register,
            **movement_kwargs(member.company, data.validated_data),
        )
        return Response(
            MovementSerializer(movement, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# entries/ ------------------------------------------------------------------------------------


class AppSaleSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Sale.Kind.choices, default=Sale.Kind.SALE)
    payments = SalePaymentSerializer(many=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")
    number = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")


class EntryView(APIView):
    """A single receipt on my open shift (receipts mode)."""

    permission_classes = OPERATE
    membership: Membership

    @extend_schema(
        request=AppSaleSerializer,
        responses=inline_serializer("KassaSale", {"id": serializers.IntegerField()}),
    )
    def post(self, request, company_id):
        member = self.membership
        if get_settings(member.company).mode != "receipts":
            raise ValidationError(
                {"detail": _("Single receipts are off: totals come from the Z-report.")}
            )
        data = AppSaleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        sale = services.record_sale(
            by=member,
            payments=sale_payments(member.company, values["payments"]),
            kind=values["kind"],
            note=values.get("note", ""),
            number=values.get("number", ""),
            source=Sale.Source.APP,
        )
        return Response(
            {
                "id": sale.pk,
                "total": m(sale.total),
                "kind": sale.kind,
                "sold_at": sale.sold_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


class EntryVoidView(APIView):
    permission_classes = OPERATE
    membership: Membership

    @extend_schema(
        request=ReasonSerializer,
        responses=inline_serializer("KassaSaleVoided", {"id": serializers.IntegerField()}),
    )
    def post(self, request, company_id, pk):
        sale = Sale.objects.filter(
            pk=pk, company=self.membership.company, shift__cashier=self.membership
        ).first()
        if sale is None:
            raise NotFound
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.void_sale(sale, by=self.membership, reason=data.validated_data["reason"])
        return Response({"id": sale.pk})


# handovers/ ----------------------------------------------------------------------------------


class PendingHandoversView(APIView):
    """Cash handed to me that I haven't answered yet."""

    permission_classes = SELF
    membership: Membership

    @extend_schema(
        responses=inline_serializer(
            "KassaHandovers", {"results": serializers.ListField(child=serializers.DictField())}
        )
    )
    def get(self, request, company_id):
        return Response(
            {
                "results": [
                    handover_data(row) for row in queries.pending_handovers_for(self.membership)
                ]
            }
        )


class HandoverAnswerView(APIView):
    permission_classes = SELF
    membership: Membership
    answer = "confirm"

    @extend_schema(
        request=OptionalReasonSerializer,
        responses=inline_serializer(
            "KassaHandoverAnswer",
            {"id": serializers.IntegerField(), "status": serializers.CharField()},
        ),
    )
    def post(self, request, company_id, pk):
        movement = CashMovement.objects.filter(
            pk=pk,
            company=self.membership.company,
            kind=CashMovement.Kind.HANDOVER,
            receiver=self.membership,
        ).first()
        if movement is None:
            raise NotFound
        if self.answer == "confirm":
            movement = services.confirm_handover(movement, by=self.membership)
        else:
            data = OptionalReasonSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            movement = services.decline_handover(
                movement, by=self.membership, reason=data.validated_data["reason"]
            )
        return Response({"id": movement.pk, "status": movement.status})
