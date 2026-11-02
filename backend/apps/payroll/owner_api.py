"""Owner dashboard endpoints of payroll (`payroll/…`, docs/PLAN-OWNER.md §4.11).

Every endpoint is company-scoped and branch-scoped by person (§2.6: someone outside the
caller's branches answers 404), checks its `payroll.*` permission, audits writes through the
services and bumps the module's pulse keys after commit. Amounts reach only `payroll.view`
holders: for anyone else they are left out of the response. Except for the settings, the
endpoints answer 403 while the module is off.
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.console.base import AnyOf, OwnerAPIView, OwnerViewSet
from apps.finance.models import MoneyAccount
from apps.members import scope
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.members.queries import in_scope
from apps.payroll import conf, periods, queries, services
from apps.payroll import serializers as s
from apps.payroll.models import Adjustment, Advance, Compensation, TaskRate

VIEW, PROPOSE, MANAGE = Perm.PAYROLL_VIEW, Perm.PAYROLL_PROPOSE, Perm.PAYROLL_MANAGE
FINALIZE, PAY = Perm.PAYROLL_FINALIZE, Perm.PAYROLL_PAY
FEATURE = "payroll"

MEMBER_PARAM = OpenApiParameter("member", int, description="Only this person.")
PERIOD_PARAM = OpenApiParameter("period", str, description="A month: YYYY-MM.")


class ModuleOn:
    """403 while payroll is switched off for the company."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.company.has_feature(FEATURE):
            raise PermissionDenied(_("Payroll isn't switched on for this company."))


class PayrollMixin(ModuleOn):
    """Lookups every payroll view shares: people and accounts inside the caller's scope."""

    @property
    def show_amounts(self) -> bool:
        return self.membership.has_perm(VIEW)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "membership", None) is not None:
            context["show_amounts"] = self.show_amounts
        return context

    def context(self) -> dict:
        return {"show_amounts": self.show_amounts, "request": self.request}

    def person(self, member_id) -> Membership:
        member = (
            Membership.objects.for_company(self.company)
            .select_related("user", "company", "position", "home_branch")
            .filter(pk=member_id)
            .first()
        )
        if member is None or not in_scope(self.membership, member):
            raise NotFound
        return member

    def account(self, account_id) -> MoneyAccount:
        account = MoneyAccount.objects.for_company(self.company).filter(pk=account_id).first()
        if account is None or not scope.allows(self.branch_scope, account.branch_id):
            raise ValidationError({"account": [_("Pick an account.")]})
        return account

    def int_param(self, name: str) -> int | None:
        value = self.request.query_params.get(name)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise ValidationError({name: [_("Give a number.")]}) from exc

    def period_param(self, name: str = "period"):
        value = self.request.query_params.get(name)
        if not value:
            return None
        try:
            return periods.parse_period(value)
        except Exception as exc:
            raise ValidationError({name: [_("Give a month as YYYY-MM.")]}) from exc

    def flag(self, name: str) -> bool | None:
        value = self.request.query_params.get(name)
        if value in (None, ""):
            return None
        return value.lower() in ("1", "true", "yes")

    def ordered(self, rows, allowed: dict[str, tuple], default: tuple):
        """`?ordering=` among `allowed` (amount orderings only for payroll.view)."""
        key = self.request.query_params.get("ordering") or ""
        if key.lstrip("-") == "amount" and not self.show_amounts:
            key = ""
        return rows.order_by(*allowed.get(key, default))


class PayrollViewSet(PayrollMixin, OwnerViewSet):
    lookup_value_regex = r"\d+"


# Settings -------------------------------------------------------------------------------


class SettingsView(OwnerAPIView):
    """The company's payroll rules: pay day, advances, the deductions cap, rounding,
    overtime, holiday and night pay, and taxes (off by default)."""

    perm = MANAGE

    @extend_schema(responses=s.SettingsSerializer)
    def get(self, request, company_id):
        return Response(s.SettingsSerializer(conf.get_settings(self.company)).data)

    @extend_schema(request=s.SettingsSerializer, responses=s.SettingsSerializer)
    def patch(self, request, company_id):
        serializer = s.SettingsSerializer(
            conf.get_settings(self.company), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        row = services.update_settings(
            self.company, by=self.membership, **serializer.validated_data
        )
        return Response(s.SettingsSerializer(row).data)


# Pay setups -----------------------------------------------------------------------------

COMPENSATION_ORDERINGS = {
    "effective_from": ("effective_from", "pk"),
    "-effective_from": ("-effective_from", "-pk"),
    "name": ("membership__first_name", "membership__last_name", "-effective_from"),
    "amount": ("amount", "pk"),
    "-amount": ("-amount", "-pk"),
}


class CompensationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, PayrollViewSet):
    """Pay setups, effective-dated. A change is a new row from its first day; a row a
    finalized run used is locked (read-only, `locked_reason` says why)."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "destroy": MANAGE,
    }
    serializer_class = s.CompensationSerializer
    http_method_names = ("get", "post", "patch", "delete")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Compensation.objects.none()
        rows = queries.compensations(self.company, branch_ids=self.branch_scope)
        if self.action == "list":
            if (member := self.int_param("member")) is not None:
                rows = rows.filter(membership_id=member)
            if self.flag("current"):
                today = periods.today(self.company)
                current = queries.current_compensations(
                    rows.values_list("membership_id", flat=True).distinct(), today
                )
                rows = rows.filter(pk__in=[row.pk for row in current.values()])
            rows = self.ordered(rows, COMPENSATION_ORDERINGS, ("-effective_from", "-pk"))
        return rows

    @extend_schema(
        parameters=[
            MEMBER_PARAM,
            OpenApiParameter("current", bool, description="Only the setup in force today."),
            OpenApiParameter("ordering", str, description="effective_from, name, amount (±)"),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.CompensationWriteSerializer, responses={201: s.CompensationSerializer})
    def create(self, request, company_id):
        serializer = s.CompensationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        member = self.person(data.pop("membership"))
        row = services.set_pay(member, by=self.membership, **data)
        return Response(
            s.CompensationSerializer(row, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=s.CompensationUpdateSerializer, responses=s.CompensationSerializer)
    def partial_update(self, request, company_id, pk):
        serializer = s.CompensationUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = services.update_pay(
            self.get_object(), by=self.membership, **serializer.validated_data
        )
        return Response(s.CompensationSerializer(row, context=self.context()).data)

    def destroy(self, request, company_id, pk):
        services.remove_pay(self.get_object(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        parameters=[OpenApiParameter("q", str, description="Search names.")],
        responses=s.PaySetupRowSerializer(many=True),
    )
    @action(detail=False, methods=["get"])
    def people(self, request, company_id):
        """Everyone who can be paid, with the setup in force today and the next one planned
        (null when there is none: "no pay setup")."""
        people = queries.payable_people(self.company, branch_ids=self.branch_scope)
        if q := (request.query_params.get("q") or "").strip():
            for word in q.split()[:4]:
                people = people.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word))
        people = people.order_by("first_name", "last_name", "pk")
        page = self.paginate_queryset(people)
        ids = [member.pk for member in page]
        today = periods.today(self.company)
        current = queries.current_compensations(ids, today)
        upcoming = queries.next_compensations(ids, today)
        context = self.context()
        rows = [
            {
                "member": s.person_card(member),
                "current": s.CompensationSerializer(current[member.pk], context=context).data
                if member.pk in current
                else None,
                "next": s.CompensationSerializer(upcoming[member.pk], context=context).data
                if member.pk in upcoming
                else None,
            }
            for member in page
        ]
        return self.get_paginated_response(rows)


# Task rates -----------------------------------------------------------------------------


class TaskRateViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, PayrollViewSet):
    """Piece rates: what one finished task earns people whose pay setup pays task rates."""

    perm = AnyOf(VIEW, MANAGE)
    perms_by_action = {"create": MANAGE, "partial_update": MANAGE, "destroy": MANAGE}
    serializer_class = s.TaskRateSerializer
    pagination_class = None
    http_method_names = ("get", "post", "patch", "delete")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TaskRate.objects.none()
        return (
            TaskRate.objects.for_company(self.company)
            .select_related("template", "position")
            .order_by("-is_active", "pk")
        )

    def _links(self, data: dict) -> dict:
        from apps.tasks.models import TaskTemplate

        fields = dict(data)
        if "template" in fields:
            value = fields["template"]
            fields["template"] = (
                get_object_or_404(TaskTemplate.objects.for_company(self.company), pk=value)
                if value
                else None
            )
        if "position" in fields:
            value = fields["position"]
            fields["position"] = (
                get_object_or_404(Position.objects.for_company(self.company), pk=value)
                if value
                else None
            )
        return fields

    @extend_schema(request=s.TaskRateWriteSerializer, responses={201: s.TaskRateSerializer})
    def create(self, request, company_id):
        serializer = s.TaskRateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.save_task_rate(
            self.company, by=self.membership, **self._links(serializer.validated_data)
        )
        return Response(
            s.TaskRateSerializer(row, context=self.context()).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=s.TaskRateWriteSerializer, responses=s.TaskRateSerializer)
    def partial_update(self, request, company_id, pk):
        serializer = s.TaskRateWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = services.save_task_rate(
            self.company,
            by=self.membership,
            rate=self.get_object(),
            **self._links(serializer.validated_data),
        )
        return Response(s.TaskRateSerializer(row, context=self.context()).data)

    def destroy(self, request, company_id, pk):
        services.remove_task_rate(self.get_object(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


# Bonuses and fines ----------------------------------------------------------------------

ADJUSTMENT_ORDERINGS = {
    "created_at": ("created_at", "pk"),
    "-created_at": ("-created_at", "-pk"),
    "period": ("period", "pk"),
    "-period": ("-period", "-pk"),
    "amount": ("amount", "pk"),
    "-amount": ("-amount", "-pk"),
    "name": ("membership__first_name", "membership__last_name", "-pk"),
}


class AdjustmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, PayrollViewSet):
    """Bonuses, fines, allowances and deductions: proposed, then approved or rejected.
    `payroll.propose` holders without `payroll.view` see only their own proposals, without
    amounts."""

    perm = AnyOf(VIEW, PROPOSE, MANAGE)
    perms_by_action = {
        "create": AnyOf(PROPOSE, MANAGE),
        "approve": MANAGE,
        "reject": MANAGE,
        "void": MANAGE,
        "answer_dispute": MANAGE,
        "bulk_decide": MANAGE,
    }
    serializer_class = s.AdjustmentSerializer
    http_method_names = ("get", "post")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Adjustment.objects.none()
        rows = queries.adjustments(self.company, branch_ids=self.branch_scope).select_related(
            "task", "dispute_answered_by"
        )
        member = self.membership
        if not member.has_perm(VIEW) and not member.has_perm(MANAGE):
            rows = rows.filter(proposed_by=member.user)
        if self.action == "list":
            params = self.request.query_params
            if period := self.period_param():
                rows = rows.filter(period=period)
            if value := params.get("status"):
                rows = rows.filter(status__in=value.split(","))
            if value := params.get("source"):
                rows = rows.filter(source__in=value.split(","))
            if value := params.get("kind"):
                rows = rows.filter(kind__in=value.split(","))
            if (member_id := self.int_param("member")) is not None:
                rows = rows.filter(membership_id=member_id)
            disputed = params.get("disputed")
            if disputed == "open":
                rows = rows.filter(
                    disputed_at__isnull=False,
                    dispute_answered_at__isnull=True,
                    status__in=(Adjustment.Status.PROPOSED, Adjustment.Status.APPROVED),
                )
            elif disputed not in (None, ""):
                rows = rows.filter(disputed_at__isnull=not self.flag("disputed"))
            rows = self.ordered(rows, ADJUSTMENT_ORDERINGS, ("-created_at", "-pk"))
        return rows

    @extend_schema(
        parameters=[
            PERIOD_PARAM,
            MEMBER_PARAM,
            OpenApiParameter("status", str, description="proposed,approved,rejected,void"),
            OpenApiParameter("source", str, description="manual,rule,task,attendance,discipline"),
            OpenApiParameter("kind", str, description="bonus,fine,allowance,deduction"),
            OpenApiParameter("disputed", str, description="true, false or open"),
            OpenApiParameter("ordering", str, description="created_at, period, amount, name (±)"),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _answer(self, row) -> Response:
        return Response(s.AdjustmentSerializer(row, context=self.context()).data)

    @extend_schema(request=s.AdjustmentWriteSerializer, responses={201: s.AdjustmentSerializer})
    def create(self, request, company_id):
        serializer = s.AdjustmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        member = self.person(data.pop("membership"))
        if data.get("approve") and not self.membership.has_perm(MANAGE):
            raise PermissionDenied(_("Only people who approve bonuses and fines can do that."))
        row = services.propose(member, by=self.membership, **data)
        return Response(
            s.AdjustmentSerializer(row, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=s.ReasonSerializer, responses=s.AdjustmentSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.approve(
            self.get_object(), by=self.membership, note=serializer.validated_data["reason"]
        )
        return self._answer(row)

    @extend_schema(request=s.ReasonSerializer, responses=s.AdjustmentSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.reject(
            self.get_object(), by=self.membership, reason=serializer.validated_data["reason"]
        )
        return self._answer(row)

    @extend_schema(request=s.RequiredReasonSerializer, responses=s.AdjustmentSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request, company_id, pk):
        serializer = s.RequiredReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.void(
            self.get_object(), by=self.membership, reason=serializer.validated_data["reason"]
        )
        return self._answer(row)

    @extend_schema(request=s.AnswerDisputeSerializer, responses=s.AdjustmentSerializer)
    @action(detail=True, methods=["post"], url_path="answer-dispute")
    def answer_dispute(self, request, company_id, pk):
        serializer = s.AnswerDisputeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        answer = data.get("answer") or data.get("reason") or ""
        if not answer.strip():
            raise ValidationError({"answer": [_("Write an answer.")]})
        row = services.answer_dispute(
            self.get_object(), by=self.membership, answer=answer, void_it=data["void"]
        )
        return self._answer(row)

    @extend_schema(request=s.BulkDecideSerializer, responses=s.BulkResultSerializer(many=True))
    @action(detail=False, methods=["post"], url_path="bulk-decide")
    def bulk_decide(self, request, company_id):
        serializer = s.BulkDecideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        found = {row.pk: row for row in self.get_queryset().filter(pk__in=data["ids"])}
        results = services.bulk_decide(
            [found[pk] for pk in data["ids"] if pk in found],
            by=self.membership,
            approve_them=data["approve"],
            reason=data["reason"],
        )
        missing = [
            {"id": pk, "ok": False, "error": _("Not found.")}
            for pk in data["ids"]
            if pk not in found
        ]
        return Response(results + missing)


# Advances -------------------------------------------------------------------------------

ADVANCE_ORDERINGS = {
    "created_at": ("created_at", "pk"),
    "-created_at": ("-created_at", "-pk"),
    "amount": ("amount", "pk"),
    "-amount": ("-amount", "-pk"),
    "name": ("membership__first_name", "membership__last_name", "-pk"),
}


class AdvanceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, PayrollViewSet):
    """Advances: requests to decide, approved ones to pay (from an account, through finance),
    repayments from payslips or in money."""

    perm = AnyOf(VIEW, MANAGE, PAY)
    perms_by_action = {
        "create": MANAGE,
        "decide": MANAGE,
        "cancel": MANAGE,
        "pay": PAY,
        "repay": PAY,
    }
    serializer_class = s.AdvanceSerializer
    http_method_names = ("get", "post")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Advance.objects.none()
        rows = queries.advances(self.company, branch_ids=self.branch_scope).select_related(
            "requested_by", "decided_by", "paid_by"
        )
        rows = rows.prefetch_related("repayments__payslip_line")
        if self.action == "list":
            params = self.request.query_params
            if value := params.get("status"):
                rows = rows.filter(status__in=value.split(","))
            if (member_id := self.int_param("member")) is not None:
                rows = rows.filter(membership_id=member_id)
            rows = self.ordered(rows, ADVANCE_ORDERINGS, ("-created_at", "-pk"))
        return rows

    @extend_schema(
        parameters=[
            MEMBER_PARAM,
            OpenApiParameter(
                "status", str, description="requested,approved,rejected,paid,repaid,cancelled"
            ),
            OpenApiParameter("ordering", str, description="created_at, amount, name (±)"),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _answer(self, row, code=status.HTTP_200_OK) -> Response:
        row = self.get_queryset().get(pk=row.pk)
        return Response(s.AdvanceSerializer(row, context=self.context()).data, status=code)

    @extend_schema(request=s.AdvanceWriteSerializer, responses={201: s.AdvanceSerializer})
    def create(self, request, company_id):
        serializer = s.AdvanceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        member = self.person(data.pop("membership"))
        row = services.create_advance(member, by=self.membership, **data)
        return self._answer(row, status.HTTP_201_CREATED)

    @extend_schema(request=s.AdvanceDecideSerializer, responses=s.AdvanceSerializer)
    @action(detail=True, methods=["post"])
    def decide(self, request, company_id, pk):
        serializer = s.AdvanceDecideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = services.decide_advance(
            self.get_object(),
            by=self.membership,
            approve_it=data["approve"],
            note=data["reason"],
            installments=data.get("installments"),
            first_period=data.get("first_period"),
        )
        return self._answer(row)

    @extend_schema(request=s.ReasonSerializer, responses=s.AdvanceSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.cancel_advance(
            self.get_object(), by=self.membership, reason=serializer.validated_data["reason"]
        )
        return self._answer(row)

    @extend_schema(request=s.AdvancePaySerializer, responses=s.AdvanceSerializer)
    @action(detail=True, methods=["post"])
    def pay(self, request, company_id, pk):
        serializer = s.AdvancePaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = services.pay_advance(
            self.get_object(),
            by=self.membership,
            account=self.account(data["account"]),
            method=data["method"],
            paid_on=data.get("paid_on"),
        )
        return self._answer(row)

    @extend_schema(request=s.AdvanceRepaySerializer, responses=s.AdvanceSerializer)
    @action(detail=True, methods=["post"])
    def repay(self, request, company_id, pk):
        serializer = s.AdvanceRepaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        advance = self.get_object()
        services.repay_advance(
            advance,
            by=self.membership,
            amount=data["amount"],
            account=self.account(data["account"]),
            paid_on=data.get("paid_on"),
            note=data["note"],
        )
        return self._answer(advance)
