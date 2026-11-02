"""Owner dashboard endpoints of payroll (`payroll/…`, docs/PLAN-OWNER.md §4.11).

Every endpoint is company-scoped and branch-scoped by person (§2.6: someone outside the
caller's branches answers 404), checks its `payroll.*` permission, audits writes through the
services and bumps the module's pulse keys after commit. Amounts reach only `payroll.view`
holders: for anyone else they are left out of the response. Except for the settings, the
endpoints answer 403 while the module is off.
"""

from decimal import Decimal

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
from apps.payroll import conf, periods, queries, rules, services
from apps.payroll import serializers as s
from apps.payroll.models import (
    Adjustment,
    AdjustmentRule,
    Advance,
    Compensation,
    PayrollRun,
    Payslip,
    TaskRate,
)

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
    @action(detail=True, methods=["post"], url_path="repay")
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


# Rules ----------------------------------------------------------------------------------


class RuleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, PayrollViewSet):
    """Automatic bonuses and fines. Shipped examples start switched off; `preview` is a dry
    run for a month (who would get what, the total) that writes nothing."""

    perm = MANAGE
    serializer_class = s.RuleSerializer
    pagination_class = None
    http_method_names = ("get", "post", "patch", "delete")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AdjustmentRule.objects.none()
        return (
            AdjustmentRule.objects.for_company(self.company)
            .prefetch_related("positions")
            .order_by("-is_active", "pk")
        )

    def _fields(self, data: dict) -> dict:
        fields = dict(data)
        if "positions" in fields:
            ids = set(fields["positions"])
            found = list(Position.objects.for_company(self.company).filter(pk__in=ids))
            if len(found) != len(ids):
                raise ValidationError({"positions": [_("Pick positions from the list.")]})
            fields["positions"] = found
        if "tiers" in fields:
            fields["tiers"] = [
                {"threshold": str(tier["threshold"]), "amount": str(tier["amount"])}
                for tier in fields["tiers"]
            ]
        return fields

    def _answer(self, rule, code=status.HTTP_200_OK) -> Response:
        rule = self.get_queryset().get(pk=rule.pk)
        return Response(s.RuleSerializer(rule, context=self.context()).data, status=code)

    @extend_schema(request=s.RuleWriteSerializer, responses={201: s.RuleSerializer})
    def create(self, request, company_id):
        serializer = s.RuleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        for name in ("name", "kind", "metric"):
            if name not in serializer.validated_data:
                raise ValidationError({name: [_("This field is required.")]})
        rule = services.save_rule(
            self.company, by=self.membership, **self._fields(serializer.validated_data)
        )
        return self._answer(rule, status.HTTP_201_CREATED)

    @extend_schema(request=s.RuleWriteSerializer, responses=s.RuleSerializer)
    def partial_update(self, request, company_id, pk):
        serializer = s.RuleWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        rule = services.save_rule(
            self.company,
            by=self.membership,
            rule=self.get_object(),
            **self._fields(serializer.validated_data),
        )
        return self._answer(rule)

    def destroy(self, request, company_id, pk):
        services.remove_rule(self.get_object(), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=s.RulePreviewRequestSerializer, responses=s.RulePreviewSerializer)
    @action(detail=True, methods=["post"])
    def preview(self, request, company_id, pk):
        serializer = s.RulePreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        period = serializer.validated_data.get("period") or periods.first_day(
            periods.today(self.company)
        )
        result = rules.preview(self.get_object(), period)
        visible = None
        if self.branch_scope is not None:
            visible = set(
                queries.payable_people(self.company, branch_ids=self.branch_scope).values_list(
                    "pk", flat=True
                )
            )
        rows = [
            {
                "member": s.person(row["member"]),
                "value": str(row["value"]) if row["value"] is not None else None,
                "amount": f"{row['amount']:.2f}" if row["amount"] is not None else None,
                "units": str(row["units"]) if row["units"] is not None else None,
                "tier": str(row["tier"]) if row["tier"] is not None else None,
            }
            for row in result["rows"]
            if visible is None or row["member"].pk in visible
        ]
        data = {
            "period": result["period"].isoformat(),
            "to": result["to"].isoformat(),
            "currency": conf.get_settings(self.company).currency,
            "rows": s.RulePreviewRowSerializer(rows, many=True, context=self.context()).data,
        }
        if self.show_amounts:
            total = sum(
                (Decimal(row["amount"]) for row in rows if row["amount"] is not None), Decimal(0)
            )
            data["total"] = f"{total:.2f}"
        return Response(data)


# Overview -------------------------------------------------------------------------------


class OverviewView(PayrollMixin, OwnerAPIView):
    """Payroll cost by month, the latest closed month by position and branch, bonuses against
    fines, how many people are paid, this month's projection and what waits for a decision."""

    perm = VIEW

    @extend_schema(
        parameters=[OpenApiParameter("months", int, description="How many months (1-24).")],
        responses=s.OverviewSerializer,
    )
    def get(self, request, company_id):
        months = self.int_param("months") or 12
        if not 1 <= months <= 24:
            raise ValidationError({"months": [_("Pick 1 to 24 months.")]})
        data = queries.overview(
            self.company,
            months=months,
            branch_ids=self.branch_scope,
            today=periods.today(self.company),
        )
        return Response(data)


# Runs and payslips ----------------------------------------------------------------------


def _visible_totals(run, payslips) -> dict:
    """A run's totals over the payslips the caller sees (people outside their branches left
    out)."""
    totals = dict(run.totals or {})
    rows = list(payslips)
    totals["people"] = len(rows)
    for field in ("gross", "deductions", "net"):
        totals[field] = f"{sum((getattr(p, field) for p in rows), Decimal(0)):.2f}"
    for field in ("bonuses", "fines", "advances", "reimbursements"):
        totals.pop(field, None)
    totals["paid"] = sum(1 for p in rows if p.status == Payslip.Status.PAID)
    totals["published"] = sum(1 for p in rows if p.published_at is not None)
    return totals


class RunViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, PayrollViewSet):
    """Payroll runs: one a month (plus final settlements). Draft → calculate (again and again)
    → finalize → publish → mark paid; reopen and cancel. Warnings come first."""

    perm = VIEW
    perms_by_action = {
        "create": MANAGE,
        "calculate": MANAGE,
        "cancel": MANAGE,
        "finalize": FINALIZE,
        "reopen": FINALIZE,
        "publish": FINALIZE,
        "mark_paid": PAY,
    }
    serializer_class = s.RunSerializer
    http_method_names = ("get", "post")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PayrollRun.objects.none()
        rows = PayrollRun.objects.for_company(self.company).select_related(
            "membership__user", "finalized_by"
        )
        if self.action == "list":
            params = self.request.query_params
            if value := params.get("status"):
                rows = rows.filter(status__in=value.split(","))
            if value := params.get("kind"):
                rows = rows.filter(kind__in=value.split(","))
            if value := params.get("year"):
                rows = rows.filter(period__year=self.int_param("year"))
            rows = rows.order_by("-period", "-pk")
        return rows

    def visible_payslips(self, run):
        rows = run.payslips.select_related(
            "membership__user", "membership__position", "membership__home_branch", "run"
        ).prefetch_related("lines")
        return queries.people_scope(rows, self.branch_scope)

    def _out(self, run, code=status.HTTP_200_OK) -> Response:
        data = s.RunSerializer(run, context=self.get_serializer_context()).data
        if self.branch_scope is not None:
            data["totals"] = _visible_totals(run, self.visible_payslips(run))
            visible = set(self.visible_payslips(run).values_list("membership_id", flat=True))
            data["warnings"] = [
                warning
                for warning in data["warnings"]
                if warning.get("member") is None or warning["member"]["id"] in visible
            ]
        return Response(data, status=code)

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, description="draft,finalized,paid,cancelled"),
            OpenApiParameter("kind", str, description="regular,final"),
            OpenApiParameter("year", int),
        ]
    )
    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        context = self.get_serializer_context()
        rows = []
        for run in page:
            data = s.RunSerializer(run, context=context).data
            if self.branch_scope is not None:
                data["totals"] = _visible_totals(run, self.visible_payslips(run))
                data["warnings"] = []
            rows.append(data)
        return self.get_paginated_response(rows)

    def retrieve(self, request, *args, **kwargs):
        return self._out(self.get_object())

    @extend_schema(request=s.RunCreateSerializer, responses={201: s.RunSerializer})
    def create(self, request, company_id):
        serializer = s.RunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        run = services.create_run(
            self.company,
            by=self.membership,
            period=data["period"],
            usd_rate=data.get("usd_rate"),
            notes=data["notes"],
        )
        return self._out(run, status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[OpenApiParameter("status", str, description="draft,published,paid")],
        responses=s.PayslipRowSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def payslips(self, request, company_id, pk):
        run = self.get_object()
        rows = self.visible_payslips(run)
        if value := request.query_params.get("status"):
            rows = rows.filter(status__in=value.split(","))
        rows = rows.order_by("membership__first_name", "membership__last_name", "pk")
        page = self.paginate_queryset(rows)
        data = s.PayslipRowSerializer(page, many=True, context=self.context()).data
        return self.get_paginated_response(data)

    @extend_schema(request=s.RunCalculateSerializer, responses=s.RunSerializer)
    @action(detail=True, methods=["post"])
    def calculate(self, request, company_id, pk):
        serializer = s.RunCalculateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = services.calculate_run(
            self.get_object(),
            by=self.membership,
            usd_rate=serializer.validated_data.get("usd_rate"),
        )
        return self._out(run)

    @extend_schema(request=None, responses=s.RunSerializer)
    @action(detail=True, methods=["post"])
    def finalize(self, request, company_id, pk):
        return self._out(services.finalize_run(self.get_object(), by=self.membership))

    @extend_schema(request=s.ReasonSerializer, responses=s.RunSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = services.reopen_run(
            self.get_object(), by=self.membership, reason=serializer.validated_data["reason"]
        )
        return self._out(run)

    @extend_schema(request=s.ReasonSerializer, responses=s.RunSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = services.cancel_run(
            self.get_object(), by=self.membership, reason=serializer.validated_data["reason"]
        )
        return self._out(run)

    def _payslip_ids(self, run, ids):
        """Ids the caller may act on: payslips of people in their scope."""
        if ids is None:
            return list(self.visible_payslips(run).values_list("pk", flat=True))
        visible = set(self.visible_payslips(run).filter(pk__in=ids).values_list("pk", flat=True))
        if visible != set(ids):
            raise NotFound
        return ids

    @extend_schema(request=s.PublishSerializer, responses=s.RunSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, company_id, pk):
        serializer = s.PublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = self.get_object()
        ids = self._payslip_ids(run, serializer.validated_data.get("payslip_ids"))
        services.publish(run, by=self.membership, payslip_ids=ids)
        run.refresh_from_db()
        return self._out(run)

    @extend_schema(request=s.MarkPaidSerializer, responses=s.RunSerializer)
    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, company_id, pk):
        serializer = s.MarkPaidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        run = self.get_object()
        services.mark_paid(
            run,
            by=self.membership,
            payslip_ids=self._payslip_ids(run, data["payslip_ids"]),
            account=self.account(data["account"]),
            method=data["method"],
            paid_on=data.get("paid_on"),
        )
        run.refresh_from_db()
        return self._out(run)


class PayslipViewSet(mixins.RetrieveModelMixin, PayrollViewSet):
    """One payslip with its lines; hand-made lines while the run is a draft; the PDF."""

    perm = VIEW
    perms_by_action = {"partial_update": MANAGE}
    serializer_class = s.PayslipSerializer
    http_method_names = ("get", "patch")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payslip.objects.none()
        rows = Payslip.objects.for_company(self.company).select_related(
            "membership__user", "membership__position", "membership__home_branch", "run"
        )
        return queries.people_scope(rows, self.branch_scope)

    @extend_schema(request=s.PayslipPatchSerializer, responses=s.PayslipSerializer)
    def partial_update(self, request, company_id, pk):
        serializer = s.PayslipPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payslip = services.set_manual_lines(
            self.get_object(), by=self.membership, lines=serializer.validated_data["manual_lines"]
        )
        payslip = self.get_queryset().get(pk=payslip.pk)
        return Response(s.PayslipSerializer(payslip, context=self.context()).data)

    @extend_schema(responses=s.FileLinkSerializer)
    @action(detail=True, methods=["get"])
    def pdf(self, request, company_id, pk):
        """A short-lived link to the payslip as a PDF, in your language."""
        return Response(pdf_link(self.get_object(), request))


def pdf_link(payslip: Payslip, request) -> dict:
    from django.utils import translation

    from apps.core.files import DEFAULT_TTL, signed_url
    from apps.payroll import payslip_pdf

    language = (translation.get_language() or "uz")[:2]
    stored = payslip_pdf.save(payslip, language=language)
    name = payslip_pdf.file_name(payslip)
    url = signed_url(
        stored,
        user=request.user,
        company_id=payslip.company_id,
        check=f"payroll.payslip:{payslip.pk}",
        filename=name,
    )
    return {"url": url, "name": name, "expires_in": DEFAULT_TTL}
