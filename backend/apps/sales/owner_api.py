"""Owner dashboard endpoints of sales and cash (docs/PLAN-OWNER.md §4.8); routed in
`owner_urls.py` under `/api/v1/owner/companies/<id>/sales/`.

Every view is company-scoped and branch-scoped (§2.6: an id outside the caller's branches answers
404), checks its `Perm`, answers 404 while the sales module is off, sends money as strings and
lets the services audit and bump the pulse keys.
"""

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.companies.models import Branch, Feature
from apps.console.base import HasPerm, OwnerAPIView, OwnerCompanyAccess, OwnerViewSet, RangeMixin
from apps.finance.models import Category, MoneyAccount
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.sales import queries, services
from apps.sales.conf import get_settings
from apps.sales.days import business_day
from apps.sales.models import (
    CashMovement,
    CashShift,
    DailySales,
    PaymentMethod,
    Register,
    Sale,
    SalesTarget,
)
from apps.sales.serializers import (
    CorrectSerializer,
    ForceCloseSerializer,
    MovementSerializer,
    MovementWriteSerializer,
    OptionalReasonSerializer,
    PaymentMethodSerializer,
    ReasonSerializer,
    RegisterSerializer,
    ReorderSerializer,
    SaleSerializer,
    SaleWriteSerializer,
    SettingsSerializer,
    ShiftDetailSerializer,
    ShiftListSerializer,
    TargetAmountSerializer,
    TargetWriteSerializer,
    VerifySerializer,
    movement_kwargs,
    payment_lines,
    sale_payments,
)


class SalesOn(BasePermission):
    """The sales module is switched on for the company (else the endpoints don't exist)."""

    def has_permission(self, request, view):
        if not view.company.has_feature(Feature.SALES):
            raise NotFound
        return True


PERMISSIONS = (IsAuthenticated, OwnerCompanyAccess, SalesOn, HasPerm)


class SalesView(RangeMixin, OwnerAPIView):
    permission_classes = PERMISSIONS
    perm = Perm.SALES_VIEW


class SalesViewSet(OwnerViewSet):
    permission_classes = PERMISSIONS
    perm = Perm.SALES_VIEW
    lookup_value_regex = r"\d+"


def _ids(params, name: str) -> list[int]:
    values = []
    for raw in params.getlist(name):
        values += [int(part) for part in str(raw).split(",") if part.strip().isdigit()]
    return values


def _flag(params, name: str) -> bool | None:
    value = params.get(name)
    if value in ("1", "true", "yes"):
        return True
    if value in ("0", "false", "no"):
        return False
    return None


def _branch(member: Membership, branch_id) -> Branch:
    branch = Branch.objects.for_company(member.company).filter(pk=branch_id, is_active=True).first()
    if branch is None or not scope.allows(scope.branch_ids(member), branch.pk):
        raise ValidationError({"branch_id": [_("Pick one of your branches.")]})
    return branch


def _register(member: Membership, register_id) -> Register:
    register = (
        Register.objects.for_company(member.company)
        .select_related("branch", "cash_account")
        .filter(pk=register_id)
        .first()
    )
    if register is None or not scope.allows(scope.branch_ids(member), register.branch_id):
        raise ValidationError({"register_id": [_("Pick one of your tills.")]})
    return register


# settings/ -------------------------------------------------------------------------------


class SettingsView(SalesView):
    """How the company records sales: business day, cash tolerance, blind count, photos, mode,
    alerts."""

    perms_by_action = {"patch": Perm.SALES_MANAGE}

    @extend_schema(responses=SettingsSerializer)
    def get(self, request, company_id):
        return Response(SettingsSerializer(get_settings(self.company)).data)

    @extend_schema(request=SettingsSerializer, responses=SettingsSerializer)
    def patch(self, request, company_id):
        current = get_settings(self.company)
        serializer = SettingsSerializer(current, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        settings = services.update_settings(
            self.company, by=self.membership, **serializer.validated_data
        )
        return Response(SettingsSerializer(settings).data)


# payment-methods/ ------------------------------------------------------------------------


class PaymentMethodViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    SalesViewSet,
):
    """How customers pay. Archive with `is_active=false`; default methods can be renamed."""

    serializer_class = PaymentMethodSerializer
    pagination_class = None
    perms_by_action = {
        "create": Perm.SALES_MANAGE,
        "update": Perm.SALES_MANAGE,
        "partial_update": Perm.SALES_MANAGE,
        "reorder": Perm.SALES_MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PaymentMethod.objects.none()
        return (
            PaymentMethod.objects.for_company(self.company)
            .select_related("account")
            .order_by("order", "pk")
        )

    def perform_create(self, serializer):
        serializer.instance = services.create_payment_method(
            self.company, by=self.membership, **serializer.validated_data
        )

    def perform_update(self, serializer):
        serializer.instance = services.update_payment_method(
            serializer.instance, by=self.membership, **serializer.validated_data
        )

    @extend_schema(request=ReorderSerializer, responses=PaymentMethodSerializer(many=True))
    @action(detail=False, methods=["post"])
    def reorder(self, request, company_id):
        data = ReorderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.reorder_payment_methods(
            self.company, by=self.membership, ids=data.validated_data["ids"]
        )
        return Response(self.get_serializer(self.get_queryset(), many=True).data)


# registers/ ------------------------------------------------------------------------------


class RegisterViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    SalesViewSet,
):
    """Tills per branch, each with its cash account, what it holds now and its open shift.
    Creating one makes its cash account; archive with `is_active=false`."""

    serializer_class = RegisterSerializer
    pagination_class = None
    perms_by_action = {
        "create": Perm.SALES_MANAGE,
        "update": Perm.SALES_MANAGE,
        "partial_update": Perm.SALES_MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Register.objects.none()
        rows = Register.objects.for_company(self.company).select_related("branch", "cash_account")
        if branches := _ids(self.request.query_params, "branch"):
            rows = rows.filter(branch_id__in=branches)
        return queries.restrict(rows, self.branch_scope)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if hasattr(self, "company"):
            context["open_shifts"] = {
                shift.register_id: shift
                for shift in CashShift.objects.filter(
                    company=self.company, status=CashShift.Status.OPEN
                ).select_related("cashier")
            }
        return context

    @extend_schema(parameters=[OpenApiParameter("branch", int, many=True)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.create_register(
            self.company,
            by=self.membership,
            branch=_branch(self.membership, data["branch_id"]),
            name=data["name"],
            fiscal_serial=data.get("fiscal_serial", ""),
        )

    def perform_update(self, serializer):
        data = dict(serializer.validated_data)
        data.pop("branch_id", None)
        serializer.instance = services.update_register(
            serializer.instance, by=self.membership, **data
        )


# targets/ --------------------------------------------------------------------------------


TargetListSerializer = inline_serializer(
    "SalesTargetList",
    {
        "month": serializers.DateField(),
        "today": serializers.DateField(),
        "targets": serializers.ListField(child=serializers.DictField()),
        "series": serializers.ListField(child=serializers.DictField()),
    },
)


class TargetViewSet(mixins.DestroyModelMixin, SalesViewSet):
    """Monthly goals for the company, a branch or a person, with daily pacing."""

    perms_by_action = {
        "create": Perm.SALES_MANAGE,
        "partial_update": Perm.SALES_MANAGE,
        "destroy": Perm.SALES_MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SalesTarget.objects.none()
        rows = SalesTarget.objects.for_company(self.company)
        if self.branch_scope is not None:
            rows = rows.filter(
                Q(branch_id__in=self.branch_scope)
                | Q(membership__home_branch_id__in=self.branch_scope)
            )
        return rows

    def _month(self):
        raw = self.request.query_params.get("month")
        today = business_day(self.company)
        if not raw:
            return today.replace(day=1), today
        try:
            year, month = (int(part) for part in raw[:7].split("-"))
            return today.replace(year=year, month=month, day=1), today
        except ValueError:
            raise ValidationError({"month": [_("A month like 2026-10.")]}) from None

    @extend_schema(parameters=[OpenApiParameter("month", str)], responses=TargetListSerializer)
    def list(self, request, company_id):
        month, today = self._month()
        branch_ids = self.branch_scope
        return Response(
            {
                "month": month.isoformat(),
                "today": today.isoformat(),
                "targets": queries.targets(
                    self.company, month, branch_ids=branch_ids, today_day=today
                ),
                "series": queries.target_series(self.company, month, branch_ids=branch_ids),
            }
        )

    @extend_schema(
        request=TargetWriteSerializer,
        responses=inline_serializer("SalesTargetId", {"id": serializers.IntegerField()}),
    )
    def create(self, request, company_id):
        data = TargetWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        branch = _branch(self.membership, values["branch_id"]) if values.get("branch_id") else None
        member = None
        if values.get("member_id"):
            member = (
                Membership.objects.for_company(self.company).filter(pk=values["member_id"]).first()
            )
            if member is None:
                raise ValidationError({"member_id": [_("Pick someone from the team.")]})
        if branch is None and member is None and self.branch_scope is not None:
            raise ValidationError({"branch_id": [_("Pick one of your branches.")]})
        target = services.set_target(
            self.company,
            by=self.membership,
            month=values["month"],
            amount=values["amount"],
            branch=branch,
            membership=member,
        )
        return Response({"id": target.pk}, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=TargetAmountSerializer,
        responses=inline_serializer("SalesTargetIdOnly", {"id": serializers.IntegerField()}),
    )
    def partial_update(self, request, company_id, pk):
        target = self.get_object()
        data = TargetAmountSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.set_target(
            self.company,
            by=self.membership,
            month=target.month,
            amount=data.validated_data["amount"],
            branch=target.branch,
            membership=target.membership,
        )
        return Response({"id": target.pk})

    def perform_destroy(self, instance):
        services.delete_target(instance, by=self.membership)


# today/, summary/, daily/, cashiers/ -----------------------------------------------------


class TodayView(SalesView):
    """Per branch right now: opened at/by, open tills, sales so far, cash in the branch, alerts."""

    @extend_schema(
        responses=inline_serializer(
            "SalesToday", {"branches": serializers.ListField(child=serializers.DictField())}
        )
    )
    def get(self, request, company_id):
        return Response(
            {"branches": queries.today(self.company, timezone.now(), branch_ids=self.branch_scope)}
        )


def _scoped_branches(view) -> list[int] | None:
    """The `branch` filter intersected with the caller's scope."""
    wanted = _ids(view.request.query_params, "branch")
    scope_ids = view.branch_scope
    if not wanted:
        return scope_ids
    if scope_ids is None:
        return wanted
    return [pk for pk in wanted if pk in scope_ids]


class SummaryView(SalesView):
    """Sales in the shared analytics shape (`totals`, `previous`, `series`, `breakdown`)."""

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
            OpenApiParameter("preset", str),
            OpenApiParameter("compare", str, enum=["none", "prev", "year"]),
            OpenApiParameter("group_by", str, enum=list(queries.GROUPS)),
            OpenApiParameter("branch", int, many=True),
        ],
        responses=inline_serializer(
            "SalesSummary",
            {
                "range": serializers.DictField(),
                "compare": serializers.DictField(allow_null=True),
                "currency": serializers.CharField(),
                "totals": serializers.DictField(),
                "previous": serializers.DictField(allow_null=True),
                "series": serializers.ListField(child=serializers.DictField()),
                "breakdown": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    def get(self, request, company_id):
        group_by = request.query_params.get("group_by") or "day"
        if group_by not in queries.GROUPS:
            raise ValidationError({"group_by": [_("Unknown grouping.")]})
        r = self.range
        compare = (r.compare_start, r.compare_end) if r.has_compare else None
        return Response(
            queries.summary(
                self.company,
                r.start,
                r.end,
                group_by,
                branch_ids=_scoped_branches(self),
                compare=compare,
            )
        )


class DailySerializer(serializers.ModelSerializer):
    branch = serializers.SerializerMethodField()

    class Meta:
        model = DailySales
        fields = (
            "id",
            "day",
            "branch",
            "sales",
            "refunds",
            "net",
            "receipts",
            "avg_check",
            "by_method",
            "shifts",
            "cash_difference",
        )
        read_only_fields = fields

    def get_branch(self, row) -> dict:
        return {"id": row.branch_id, "name": row.branch.name, "code": row.branch.code}

    def to_representation(self, row):
        data = super().to_representation(row)
        for key in ("sales", "refunds", "net", "avg_check", "cash_difference"):
            data[key] = queries.m(getattr(row, key))
        return data


class DailyViewSet(mixins.ListModelMixin, SalesViewSet, RangeMixin):
    """The `DailySales` table: one row per branch and business day."""

    serializer_class = DailySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DailySales.objects.none()
        r = self.range
        return queries.daily_rows(
            self.company, r.start, r.end, branch_ids=_scoped_branches(self)
        ).order_by("-day", "branch__order")


class CashiersView(SalesView):
    """The cashier scorecard for the range."""

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
            OpenApiParameter("preset", str),
            OpenApiParameter("branch", int, many=True),
        ],
        responses=inline_serializer(
            "SalesCashiers",
            {
                "range": serializers.DictField(),
                "results": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    def get(self, request, company_id):
        r = self.range
        return Response(
            {
                "range": {"from": r.start.isoformat(), "to": r.end.isoformat()},
                "results": queries.cashier_scorecard(
                    self.company, r.start, r.end, branch_ids=_scoped_branches(self)
                ),
            }
        )


# shifts/ ---------------------------------------------------------------------------------


class ShiftViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, SalesViewSet):
    """Cashier shifts: list with filters, detail with everything a manager checks, and verify,
    dispute, force-close and correct."""

    perms_by_action = {
        "verify": Perm.SALES_MANAGE,
        "dispute": Perm.SALES_MANAGE,
        "force_close": Perm.SALES_MANAGE,
        "payments": Perm.SALES_MANAGE,
    }

    def get_serializer_class(self):
        return ShiftListSerializer if self.action == "list" else ShiftDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CashShift.objects.none()
        params = self.request.query_params
        filters = {
            "branch": _ids(params, "branch"),
            "register": params.get("register"),
            "cashier": _ids(params, "cashier"),
            "status": [
                s
                for raw in params.getlist("status")
                for s in raw.split(",")
                if s in CashShift.Status.values
            ],
            "from": params.get("from"),
            "to": params.get("to"),
            "has_difference": _flag(params, "has_difference"),
            "mismatch": _flag(params, "mismatch"),
            "q": params.get("q"),
        }
        rows = queries.shifts(self.company, filters, None, branch_ids=self.branch_scope)
        ordering = params.get("ordering")
        allowed = {
            "opened_at",
            "-opened_at",
            "business_day",
            "-business_day",
            "difference",
            "-difference",
            "net",
            "-net",
            "number",
            "-number",
        }
        if ordering in allowed:
            rows = rows.order_by(ordering, "-pk")
        return rows

    @extend_schema(
        parameters=[
            OpenApiParameter("branch", int, many=True),
            OpenApiParameter("register", int),
            OpenApiParameter("cashier", int, many=True),
            OpenApiParameter("status", str, many=True),
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
            OpenApiParameter("has_difference", bool),
            OpenApiParameter("mismatch", bool),
            OpenApiParameter("q", str),
            OpenApiParameter("ordering", str),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=ShiftDetailSerializer)
    def retrieve(self, request, company_id, pk):
        shift = self.get_object()
        data = ShiftDetailSerializer(shift, context=self.get_serializer_context()).data
        data["timeline"] = queries.shift_timeline(shift, self.membership)
        return Response(data)

    def _detail(self, shift) -> Response:
        shift = queries.shift_for(self.membership, shift.pk)
        data = ShiftDetailSerializer(shift, context=self.get_serializer_context()).data
        data["timeline"] = queries.shift_timeline(shift, self.membership)
        return Response(data)

    @extend_schema(request=VerifySerializer, responses=ShiftDetailSerializer)
    @action(detail=True, methods=["post"])
    def verify(self, request, company_id, pk):
        data = VerifySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        shift = services.verify_shift(self.get_object(), by=self.membership, **data.validated_data)
        return self._detail(shift)

    @extend_schema(request=ReasonSerializer, responses=ShiftDetailSerializer)
    @action(detail=True, methods=["post"])
    def dispute(self, request, company_id, pk):
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        shift = services.dispute_shift(
            self.get_object(), by=self.membership, reason=data.validated_data["reason"]
        )
        return self._detail(shift)

    @extend_schema(request=ForceCloseSerializer, responses=ShiftDetailSerializer)
    @action(detail=True, methods=["post"], url_path="force-close")
    def force_close(self, request, company_id, pk):
        data = ForceCloseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        payments = payment_lines(self.company, values["payments"]) if "payments" in values else None
        shift = services.force_close(
            self.get_object(),
            by=self.membership,
            reason=values["reason"],
            payments=payments,
            counted_cash=values.get("counted_cash"),
        )
        return self._detail(shift)

    @extend_schema(request=CorrectSerializer, responses=ShiftDetailSerializer)
    @action(detail=True, methods=["patch"])
    def payments(self, request, company_id, pk):
        data = CorrectSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        shift = services.correct_shift(
            self.get_object(),
            by=self.membership,
            payments=payment_lines(self.company, values["payments"]),
            reason=values["reason"],
            counted_cash=values.get("counted_cash"),
        )
        return self._detail(shift)


# cash/positions/ and cash-movements/ ---------------------------------------------------------


class CashPositionsView(SalesView):
    """Where the cash is: tills, safes, in transit, held by people, sent to the bank."""

    @extend_schema(
        responses=inline_serializer(
            "SalesCashPositions",
            {
                "totals": serializers.DictField(),
                "branches": serializers.ListField(child=serializers.DictField()),
            },
        )
    )
    def get(self, request, company_id):
        return Response(queries.cash_positions(self.company, branch_ids=self.branch_scope))


class MovementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, SalesViewSet):
    """Cash movements: payouts, handovers, safe, bank, deposits. Managers record and void them."""

    serializer_class = MovementSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    perms_by_action = {"create": Perm.SALES_MANAGE, "void": Perm.SALES_MANAGE}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CashMovement.objects.none()
        params = self.request.query_params
        rows = queries.restrict(
            CashMovement.objects.for_company(self.company), self.branch_scope
        ).select_related(
            "branch",
            "register",
            "shift__branch",
            "receiver",
            "to_account",
            "category",
            "created_by",
            "confirmed_by",
        )
        if branches := _ids(params, "branch"):
            rows = rows.filter(branch_id__in=branches)
        if kinds := [
            k
            for raw in params.getlist("kind")
            for k in raw.split(",")
            if k in CashMovement.Kind.values
        ]:
            rows = rows.filter(kind__in=kinds)
        if register := params.get("register"):
            rows = rows.filter(register_id=register)
        if shift := params.get("shift"):
            rows = rows.filter(shift_id=shift)
        state = params.get("status")
        if state == "pending":
            rows = rows.filter(
                kind=CashMovement.Kind.HANDOVER,
                confirmed_at__isnull=True,
                declined_at__isnull=True,
                voided_at__isnull=True,
            )
        elif state == "declined":
            rows = rows.filter(declined_at__isnull=False, voided_at__isnull=True)
        elif state == "void":
            rows = rows.filter(voided_at__isnull=False)
        elif state == "done":
            rows = rows.filter(confirmed_at__isnull=False, voided_at__isnull=True)
        if start := params.get("from"):
            rows = rows.filter(created_at__date__gte=start)
        if end := params.get("to"):
            rows = rows.filter(created_at__date__lte=end)
        return rows.order_by("-created_at", "-pk")

    @extend_schema(
        parameters=[
            OpenApiParameter("branch", int, many=True),
            OpenApiParameter("kind", str, many=True),
            OpenApiParameter("status", str, enum=["pending", "declined", "done", "void"]),
            OpenApiParameter("register", int),
            OpenApiParameter("shift", int),
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=MovementWriteSerializer, responses=MovementSerializer)
    def create(self, request, company_id):
        data = MovementWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        if not values.get("register_id"):
            raise ValidationError({"register_id": [_("Pick the till.")]})
        movement = services.record_movement(
            by=self.membership,
            register=_register(self.membership, values["register_id"]),
            **movement_kwargs(self.company, values),
        )
        return Response(
            MovementSerializer(movement, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=ReasonSerializer, responses=MovementSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request, company_id, pk):
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        movement = services.void_movement(
            self.get_object(), by=self.membership, reason=data.validated_data["reason"]
        )
        return Response(MovementSerializer(movement, context=self.get_serializer_context()).data)


class HandoverViewSet(SalesViewSet):
    """Cash handed to you: confirm it arrived, or say it didn't (Needs you buttons)."""

    perm = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CashMovement.objects.none()
        return CashMovement.objects.for_company(self.company).filter(
            kind=CashMovement.Kind.HANDOVER, receiver=self.membership
        )

    @extend_schema(request=None, responses=MovementSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, company_id, pk):
        movement = services.confirm_handover(self.get_object(), by=self.membership)
        return Response(MovementSerializer(movement, context=self.get_serializer_context()).data)

    @extend_schema(request=OptionalReasonSerializer, responses=MovementSerializer)
    @action(detail=True, methods=["post"])
    def decline(self, request, company_id, pk):
        data = OptionalReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        movement = services.decline_handover(
            self.get_object(), by=self.membership, reason=data.validated_data["reason"]
        )
        return Response(MovementSerializer(movement, context=self.get_serializer_context()).data)


# entries/ ----------------------------------------------------------------------------------


class EntryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, SalesViewSet):
    """Single receipts (receipts mode, or entered here after the fact)."""

    serializer_class = SaleSerializer
    perms_by_action = {"create": Perm.SALES_MANAGE, "void": Perm.SALES_MANAGE}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Sale.objects.none()
        params = self.request.query_params
        rows = (
            queries.restrict(Sale.objects.for_company(self.company), self.branch_scope)
            .select_related("branch", "register", "shift__branch", "cashier", "performed_by")
            .prefetch_related("payments__method")
        )
        if branches := _ids(params, "branch"):
            rows = rows.filter(branch_id__in=branches)
        if kind := params.get("kind"):
            rows = rows.filter(kind=kind)
        if shift := params.get("shift"):
            rows = rows.filter(shift_id=shift)
        if start := params.get("from"):
            rows = rows.filter(business_day__gte=start)
        if end := params.get("to"):
            rows = rows.filter(business_day__lte=end)
        if _flag(params, "void") is False:
            rows = rows.filter(voided_at__isnull=True)
        if q := (params.get("q") or "").strip():
            rows = rows.filter(Q(number__icontains=q) | Q(note__icontains=q))
        return rows.order_by("-sold_at", "-pk")

    @extend_schema(
        parameters=[
            OpenApiParameter("branch", int, many=True),
            OpenApiParameter("kind", str),
            OpenApiParameter("shift", int),
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
            OpenApiParameter("void", bool),
            OpenApiParameter("q", str),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=SaleWriteSerializer, responses=SaleSerializer)
    def create(self, request, company_id):
        data = SaleWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        if not values.get("branch_id"):
            raise ValidationError({"branch_id": [_("Pick the branch.")]})
        branch = _branch(self.membership, values["branch_id"])
        register = (
            _register(self.membership, values["register_id"]) if values.get("register_id") else None
        )
        sale = services.record_sale(
            by=self.membership,
            payments=sale_payments(self.company, values["payments"]),
            kind=values["kind"],
            branch=branch,
            register=register,
            discount=values.get("discount") or 0,
            number=values.get("number", ""),
            note=values.get("note", ""),
            source=Sale.Source.DASHBOARD,
            sold_at=values.get("sold_at"),
        )
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=ReasonSerializer, responses=SaleSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request, company_id, pk):
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        sale = services.void_sale(
            self.get_object(), by=self.membership, reason=data.validated_data["reason"]
        )
        return Response(SaleSerializer(sale).data)


# options/ ----------------------------------------------------------------------------------


class OptionsView(SalesView):
    """Everything the sales pages' filters and forms pick from, in one call: branches, tills,
    payment methods, cashiers, who can receive cash, expense categories and counter accounts."""

    @extend_schema(
        responses=inline_serializer(
            "SalesOptions", {"branches": serializers.ListField(child=serializers.DictField())}
        )
    )
    def get(self, request, company_id):
        company, branch_ids = self.company, self.branch_scope
        branches = queries.restrict(
            Branch.objects.for_company(company).filter(is_active=True), branch_ids, field="id"
        )
        registers = queries.restrict(
            Register.objects.for_company(company), branch_ids
        ).select_related("branch")
        cashier_ids = set(
            queries.restrict(CashShift.objects.for_company(company), branch_ids).values_list(
                "cashier_id", flat=True
            )
        )
        people = (
            Membership.objects.for_company(company)
            .filter(status=Membership.Status.APPROVED)
            .select_related("role", "home_branch")
            .prefetch_related("branches")
        )
        people = (
            scope.restrict(people, branch_ids, field="branches")
            if branch_ids is not None
            else people
        )
        cashiers, receivers = [], []
        for member in people.order_by("first_name", "last_name"):
            row = {
                "id": member.pk,
                "name": str(member),
                "branch_ids": [b.pk for b in member.branches.all()],
            }
            if member.pk in cashier_ids or member.has_perm(Perm.SALES_OPERATE):
                cashiers.append(row)
            if member.has_perm(Perm.SALES_MANAGE) or member.has_perm(Perm.FINANCE_RECORD):
                receivers.append(row)
        accounts = (
            queries.restrict(
                MoneyAccount.objects.filter(
                    company=company, is_active=True, currency=company.base_currency
                ).exclude(kind__in=[MoneyAccount.Kind.EMPLOYEE, MoneyAccount.Kind.OWNER]),
                branch_ids,
            )
            if branch_ids is not None
            else MoneyAccount.objects.filter(
                company=company, is_active=True, currency=company.base_currency
            ).exclude(kind__in=[MoneyAccount.Kind.EMPLOYEE, MoneyAccount.Kind.OWNER])
        )
        till_accounts = set(
            Register.objects.for_company(company).values_list("cash_account_id", flat=True)
        )
        settings = get_settings(company)
        return Response(
            {
                "currency": company.base_currency,
                "settings": {
                    "mode": settings.mode,
                    "blind_cash_count": settings.blind_cash_count,
                    "cash_tolerance": queries.m(settings.cash_tolerance),
                    "business_day_ends_at": settings.business_day_ends_at.strftime("%H:%M"),
                },
                "today": business_day(company).isoformat(),
                "branches": [
                    {"id": b.pk, "name": b.name, "code": b.code}
                    for b in branches.order_by("order", "name")
                ],
                "registers": [
                    {
                        "id": r.pk,
                        "name": r.name,
                        "branch_id": r.branch_id,
                        "branch": r.branch.name,
                        "is_active": r.is_active,
                    }
                    for r in registers.order_by("branch__order", "order", "name")
                ],
                "methods": [
                    {"id": p.pk, "name": p.name, "kind": p.kind, "is_active": p.is_active}
                    for p in PaymentMethod.objects.for_company(company).order_by("order", "pk")
                ],
                "cashiers": cashiers,
                "receivers": receivers,
                "categories": [
                    {"id": c.pk, "name": c.name, "code": c.system_code, "parent_id": c.parent_id}
                    for c in Category.objects.filter(
                        company=company, kind=Category.Kind.EXPENSE, is_active=True
                    ).order_by("order", "name")
                ],
                "accounts": [
                    {"id": a.pk, "name": a.name, "kind": a.kind, "branch_id": a.branch_id}
                    for a in accounts.order_by("order", "name")
                    if a.pk not in till_accounts
                ],
            }
        )
