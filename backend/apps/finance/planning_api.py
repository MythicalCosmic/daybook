"""Owner endpoints of money planning (Package I, docs/PLAN-OWNER.md §4.7, the I rows), under
`/api/v1/owner/companies/<id>/finance/`: recurring payments and the tax calendar, upcoming
payments, the cash forecast, budgets, payables and expense claims.

Like the rest of the finance endpoints (`owner_api.FinanceMixin`): company-scoped,
permission-checked, 404 while the module is off, branch-scoped (§2.6), money as strings, writes
through the services (which audit) and a pulse bump after each write.
"""

from datetime import date, timedelta

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.console.base import AllOf, AnyOf, OwnerAPIView, OwnerViewSet
from apps.core.api import Pagination
from apps.core.exceptions import DomainError
from apps.finance import (
    access,
    budgets,
    claims,
    payables,
    planning,
    recurring,
    services,
    tax_calendar,
)
from apps.finance import owner_serializers as out
from apps.finance import planning_serializers as s
from apps.finance.models import Claim, RecurringRule, Transaction
from apps.finance.owner_api import FinanceMixin, domain
from apps.members.permissions import Perm

VIEW = Perm.FINANCE_VIEW
RECORD = Perm.FINANCE_RECORD
MANAGE = Perm.FINANCE_MANAGE
APPROVE = Perm.FINANCE_APPROVE
VIEW_AND_RECORD = AllOf(VIEW, RECORD)
VIEW_AND_MANAGE = AllOf(VIEW, MANAGE)
CLAIMS = "finance.claims"
OVERDUE = "finance.overdue"
# How far ahead the holiday calendar is read for a rule's next due days.
HORIZON = timedelta(days=400)
RULE_RELATIONS = (
    "company",
    "category__parent",
    "counterparty",
    "account",
    "branch",
    "payer__user",
)


def _days(request, default: int) -> int:
    value = request.query_params.get("days", default)
    try:
        days = int(value)
    except TypeError, ValueError:
        raise exceptions.ValidationError({"days": [_("Give a number of days.")]}) from None
    if not 1 <= days <= planning.MAX_DAYS:
        raise exceptions.ValidationError(
            {"days": [_("From 1 to %(max)s days.") % {"max": planning.MAX_DAYS}]}
        )
    return days


# Recurring payments and the tax calendar ------------------------------------------------------


class RecurringViewSet(FinanceMixin, OwnerViewSet):
    """Recurring payments: bills to pay (reminders) and automatic posts, with the tax calendar."""

    perm = VIEW
    perms_by_action = {
        "create": VIEW_AND_MANAGE,
        "partial_update": VIEW_AND_MANAGE,
        "destroy": VIEW_AND_MANAGE,
        "skip": VIEW_AND_MANAGE,
        "run_now": VIEW_AND_MANAGE,
        "pay": VIEW_AND_RECORD,
    }
    serializer_class = s.RecurringRuleSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RecurringRule.objects.none()
        return recurring.visible_rules(self.company, branch_ids=self.branch_scope).select_related(
            *RULE_RELATIONS
        )

    def get_object(self) -> RecurringRule:
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def rule_context(self, rules) -> dict:
        rules = list(rules)
        starts = [rule.next_due_on for rule in rules if rule.next_due_on]
        days_off = (
            recurring.holidays(self.company, min(starts), max(starts) + HORIZON)
            if starts
            else set()
        )
        return self.context(days_off=days_off)

    def respond(self, rule: RecurringRule, code=status.HTTP_200_OK) -> Response:
        rule = self.get_queryset().get(pk=rule.pk)
        return Response(
            s.RecurringRuleSerializer(rule, context=self.rule_context([rule])).data, status=code
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("active", str, description="true (default), false or all"),
            OpenApiParameter("kind", str),
            OpenApiParameter("mode", str),
            OpenApiParameter("tax", bool),
        ],
        responses=s.RecurringRuleSerializer(many=True),
    )
    def list(self, request, company_id):
        rows = self.get_queryset()
        active = request.query_params.get("active", "true")
        if active == "true":
            rows = rows.filter(is_active=True)
        elif active == "false":
            rows = rows.filter(is_active=False)
        if kind := request.query_params.get("kind"):
            rows = rows.filter(kind=kind)
        if mode := request.query_params.get("mode"):
            rows = rows.filter(mode=mode)
        tax = request.query_params.get("tax")
        if tax == "true":
            rows = rows.filter(template_key__startswith="tax.")
        elif tax == "false":
            rows = rows.exclude(template_key__startswith="tax.")
        rules = list(rows.order_by("-is_active", "next_due_on", "name", "pk")[:500])
        return Response(
            s.RecurringRuleSerializer(rules, many=True, context=self.rule_context(rules)).data
        )

    def retrieve(self, request, company_id, pk=None):
        return self.respond(self.get_object())

    def _fields(self, data: dict) -> dict:
        fields = dict(data)
        if "category" in fields:
            fields["category"] = self.category(fields["category"])
            if fields["category"] is None:
                raise exceptions.ValidationError({"category": [_("Pick a category.")]})
        if "counterparty" in fields:
            fields["counterparty"] = self.party(fields["counterparty"])
        if "account" in fields:
            fields["account"] = (
                self.account(fields["account"]) if fields["account"] is not None else None
            )
        if "branch" in fields:
            fields["branch"] = self.write_branch(fields["branch"], default=False)
        if "payer" in fields:
            fields["payer"] = self.member(fields["payer"], "payer")
        return fields

    @extend_schema(
        request=s.RecurringRuleWriteSerializer, responses={201: s.RecurringRuleSerializer}
    )
    def create(self, request, company_id):
        serializer = s.RecurringRuleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = self._fields(serializer.validated_data)
        fields.pop("is_active", None)
        fields.setdefault("branch", self.write_branch(None))
        rule = domain(lambda: recurring.create_rule(self.company, by=self.membership, **fields))
        self.changed()
        return self.respond(rule, status.HTTP_201_CREATED)

    @extend_schema(request=s.RecurringRuleWriteSerializer, responses=s.RecurringRuleSerializer)
    def partial_update(self, request, company_id, pk=None):
        rule = self.get_object()
        serializer = s.RecurringRuleWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = self._fields(serializer.validated_data)
        rule = domain(lambda: recurring.update_rule(rule, by=self.membership, **fields))
        self.changed()
        return self.respond(rule)

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk=None):
        rule = self.get_object()
        domain(lambda: recurring.stop_rule(rule, by=self.membership))
        self.changed()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=s.RecurringPaySerializer, responses=s.RecurringPaymentSerializer)
    @action(detail=True, methods=["post"])
    def pay(self, request, company_id, pk=None):
        rule = self.get_object()
        serializer = s.RecurringPaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        paid_on = self.not_future(data.get("paid_on") or self.today, "paid_on")
        account = self.account(data["account"], access.recordable_accounts(self.membership))
        payment = domain(
            lambda: recurring.pay_occurrence(
                rule,
                by=self.membership,
                account=account,
                amount=data.get("amount"),
                paid_on=paid_on,
            )
        )
        self.changed(OVERDUE)
        return self._payment(payment)

    @extend_schema(request=None, responses=s.RecurringRuleSerializer)
    @action(detail=True, methods=["post"])
    def skip(self, request, company_id, pk=None):
        rule = domain(lambda: recurring.skip_occurrence(self.get_object(), by=self.membership))
        self.changed()
        return self.respond(rule)

    @extend_schema(request=None, responses=s.RecurringPaymentSerializer)
    @action(detail=True, methods=["post"], url_path="run-now")
    def run_now(self, request, company_id, pk=None):
        payment = domain(lambda: recurring.run_now(self.get_object(), by=self.membership))
        self.changed()
        return self._payment(payment)

    def _payment(self, payment) -> Response:
        rule = self.get_queryset().get(pk=payment.rule.pk)
        row = payment.transaction
        return Response(
            {
                "rule": s.RecurringRuleSerializer(rule, context=self.rule_context([rule])).data,
                "transaction_id": row.pk if row is not None else None,
            }
        )


class TemplatesView(FinanceMixin, OwnerAPIView):
    """The tax calendar: one template set per tax regime, the company's own first."""

    perm = VIEW

    @extend_schema(responses=s.TemplateSetSerializer(many=True))
    def get(self, request, company_id):
        return Response(tax_calendar.templates(self.company))


class TemplateApplyView(FinanceMixin, OwnerAPIView):
    """Add a regime's tax calendar as editable recurring bills (what is there already stays)."""

    perm = VIEW_AND_MANAGE

    @extend_schema(request=None, responses={201: s.RecurringRuleSerializer(many=True)})
    def post(self, request, company_id, key):
        if key not in tax_calendar.TEMPLATES:
            raise exceptions.NotFound
        made = domain(lambda: tax_calendar.apply(self.company, by=self.membership, key=key))
        self.changed()
        rules = list(
            RecurringRule.objects.filter(pk__in=[rule.pk for rule in made]).select_related(
                *RULE_RELATIONS
            )
        )
        starts = [rule.next_due_on for rule in rules if rule.next_due_on]
        days_off = (
            recurring.holidays(self.company, min(starts), max(starts) + HORIZON)
            if starts
            else set()
        )
        return Response(
            s.RecurringRuleSerializer(
                rules, many=True, context=self.context(days_off=days_off)
            ).data,
            status=status.HTTP_201_CREATED,
        )


# Upcoming payments and the forecast -----------------------------------------------------------


class UpcomingView(FinanceMixin, OwnerAPIView):
    """Bills, taxes, payables, receivables and pay due in the next days, overdue first."""

    perm = VIEW

    @extend_schema(
        parameters=[OpenApiParameter("days", int, description="1–120, default 30")],
        responses=s.UpcomingSerializer,
    )
    def get(self, request, company_id):
        days = _days(request, 30)
        return Response(
            planning.upcoming(self.company, days, branch_ids=self.branch_scope, today=self.today)
        )


class ForecastView(FinanceMixin, OwnerAPIView):
    """The cash balance day by day for 30, 60 or 90 days, its low point and the first day it
    goes below zero."""

    perm = VIEW

    @extend_schema(
        parameters=[OpenApiParameter("days", int, description="30, 60 or 90 (1–120)")],
        responses=s.ForecastSerializer,
    )
    def get(self, request, company_id):
        days = _days(request, 90)
        return Response(
            planning.forecast(self.company, days, branch_ids=self.branch_scope, today=self.today)
        )


# Budgets ----------------------------------------------------------------------------------------


class BudgetsView(FinanceMixin, OwnerAPIView):
    """Budgets against actual spending for a month; PUT sets or removes them."""

    perm = VIEW
    perms_by_action = {"put": VIEW_AND_MANAGE}

    def _month(self, value) -> date:
        if not value:
            return budgets.month_start(self.today)
        try:
            return budgets.parse_month(value)
        except DomainError as error:
            raise exceptions.ValidationError({"month": [str(error)]}) from None

    def _view(self, month: date) -> Response:
        return Response(
            budgets.month_view(self.company, month, branch_ids=self.branch_scope, today=self.today)
        )

    @extend_schema(
        parameters=[OpenApiParameter("month", str, description="YYYY-MM, default this month")],
        responses=s.BudgetMonthSerializer,
    )
    def get(self, request, company_id):
        return self._view(self._month(request.query_params.get("month")))

    @extend_schema(request=s.BudgetPutSerializer, responses=s.BudgetMonthSerializer)
    def put(self, request, company_id):
        serializer = s.BudgetPutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        month = self._month(data["month"])
        rows = []
        for row in data["rows"]:
            category = self.category(row["category"])
            rows.append((category, row.get("amount")))
        domain(
            lambda: budgets.set_budgets(self.company, by=self.membership, month=month, rows=rows)
        )
        self.changed()
        return self._view(month)


class BudgetCopyView(BudgetsView):
    """Copy the previous month's budgets into a month (categories without one only)."""

    perm = VIEW_AND_MANAGE

    @extend_schema(request=s.BudgetCopySerializer, responses=s.BudgetMonthSerializer)
    def post(self, request, company_id):
        serializer = s.BudgetCopySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = self._month(serializer.validated_data["month"])
        domain(lambda: budgets.copy_budgets(self.company, by=self.membership, month=month))
        self.changed()
        return self._view(month)


# Payables -----------------------------------------------------------------------------------------


class PayablesView(FinanceMixin, OwnerAPIView):
    """Open payables to distributors and other parties, grouped, overdue first."""

    perm = VIEW

    @extend_schema(responses=s.PayablesSerializer)
    def get(self, request, company_id):
        debts = list(payables.open_payables(self.company, branch_ids=self.branch_scope))
        data = payables.grouped(debts, self.today)
        context = self.context()
        groups = []
        for group in data["groups"]:
            rows = []
            for debt, part in group["debts"]:
                row = out.DebtSerializer(debt, context=context).data
                row["bucket"] = part
                row["bank_only"] = payables.bank_only(debt)
                rows.append(row)
            groups.append(
                {
                    "counterparty": group["counterparty"],
                    "total": str(group["total"]),
                    "overdue": str(group["overdue"]),
                    "debts": rows,
                }
            )
        return Response(
            {
                "today": self.today.isoformat(),
                "currency": self.company.base_currency,
                "groups": groups,
                "totals": data["totals"],
            }
        )


class PayablesPayView(FinanceMixin, OwnerAPIView):
    """Pay several payables from one account: one ledger row and audit row per debt."""

    perm = VIEW_AND_RECORD

    @extend_schema(request=s.PayablesPaySerializer, responses={201: s.PayablesPaidSerializer})
    def post(self, request, company_id):
        serializer = s.PayablesPaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        paid_on = self.not_future(data["paid_on"], "paid_on")
        account = self.account(data["account"], access.recordable_accounts(self.membership))
        visible = {
            debt.pk: debt
            for debt in payables.open_payables(self.company, branch_ids=self.branch_scope).filter(
                pk__in=[row["id"] for row in data["debts"]]
            )
        }
        items = []
        for row in data["debts"]:
            debt = visible.get(row["id"])
            if debt is None:
                raise exceptions.ValidationError(
                    {"debts": [_("One of these debts is paid already or isn't yours to pay.")]}
                )
            if debt.currency != account.currency:
                raise exceptions.ValidationError(
                    {
                        "account": [
                            _("Pay %(party)s from an account in %(currency)s.")
                            % {"party": debt.counterparty.name, "currency": debt.currency}
                        ]
                    }
                )
            items.append((debt, row["amount"]))
        rows = domain(
            lambda: payables.pay(
                self.company, by=self.membership, account=account, paid_on=paid_on, items=items
            )
        )
        self.changed(OVERDUE)
        return Response(
            {
                "paid": [
                    {"debt_id": debt.pk, "transaction_id": row.pk}
                    for (debt, _amount), row in zip(items, rows, strict=True)
                ],
                "warnings": payables.warnings([debt for debt, _amount in items], account),
            },
            status=status.HTTP_201_CREATED,
        )


class DebtCreditView(FinanceMixin, OwnerAPIView):
    """A credit note: settle part of a debt without money (a payable's cost goes down)."""

    perm = VIEW_AND_MANAGE

    @extend_schema(request=s.CreditSerializer, responses={201: out.TransactionSerializer})
    def post(self, request, company_id, pk):
        debt = get_object_or_404(access.visible_debts(self.membership), pk=pk)
        serializer = s.CreditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        credited_on = self.not_future(data.get("credited_on") or self.today, "credited_on")
        row = domain(
            lambda: services.credit_debt(
                debt,
                by=self.membership,
                amount=data["amount"],
                credited_on=credited_on,
                reason=data["reason"],
            )
        )
        self.changed(OVERDUE)
        row = Transaction.objects.select_related(
            "account", "category__parent", "counterparty", "membership", "branch", "debt"
        ).get(pk=row.pk)
        return Response(
            out.TransactionSerializer(row, context=self.context()).data,
            status=status.HTTP_201_CREATED,
        )


# Claims -------------------------------------------------------------------------------------------


class ClaimPagination(Pagination):
    page_size = 50


class ClaimViewSet(FinanceMixin, OwnerViewSet):
    """Expense claims: the approvers' queue, decisions and paying back in cash."""

    perm = AnyOf(APPROVE, VIEW)
    perms_by_action = {"approve": APPROVE, "reject": APPROVE, "pay": RECORD}
    serializer_class = s.ClaimSerializer
    pagination_class = ClaimPagination
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Claim.objects.none()
        return claims.with_relations(claims.visible_claims(self.membership))

    def get_object(self) -> Claim:
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def respond(self, claim: Claim) -> Response:
        claim = self.get_queryset().get(pk=claim.pk)
        return Response(s.ClaimSerializer(claim, context=self.context()).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status", str, description="submitted (default), approved, paid, …, all"
            ),
            OpenApiParameter("member", int),
        ],
        responses=s.ClaimSerializer(many=True),
    )
    def list(self, request, company_id):
        claims.sync_paid(self.company)
        rows = self.get_queryset()
        wanted = request.query_params.get("status", Claim.Status.SUBMITTED)
        if wanted != "all":
            if wanted not in Claim.Status.values:
                raise exceptions.ValidationError({"status": [_("Unknown status.")]})
            rows = rows.filter(status=wanted)
        if member := request.query_params.get("member"):
            if not member.isdigit():
                raise exceptions.ValidationError({"member": [_("Pick a person.")]})
            rows = rows.filter(membership_id=int(member))
        rows = rows.order_by("-created_at", "-pk")
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(
            s.ClaimSerializer(page, many=True, context=self.context()).data
        )

    def retrieve(self, request, company_id, pk=None):
        return self.respond(self.get_object())

    @extend_schema(request=None, responses=s.ClaimSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, company_id, pk=None):
        claim = domain(
            lambda: claims.decide_claim(self.get_object(), by=self.membership, approve=True)
        )
        self.changed(CLAIMS)
        return self.respond(claim)

    @extend_schema(request=s.ClaimRejectSerializer, responses=s.ClaimSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, company_id, pk=None):
        serializer = s.ClaimRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        claim = domain(
            lambda: claims.decide_claim(
                self.get_object(),
                by=self.membership,
                approve=False,
                reason=serializer.validated_data["reason"],
            )
        )
        self.changed(CLAIMS)
        return self.respond(claim)

    @extend_schema(request=s.ClaimPaySerializer, responses=s.ClaimSerializer)
    @action(detail=True, methods=["post"])
    def pay(self, request, company_id, pk=None):
        claim = self.get_object()
        serializer = s.ClaimPaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        paid_on = self.not_future(data.get("paid_on") or self.today, "paid_on")
        account = self.account(data["account"], access.recordable_accounts(self.membership))
        if not claims.can_pay(self.membership, claim):
            raise exceptions.ValidationError(
                {"detail": _("This expense isn't waiting to be paid back in cash.")}
            )
        claim = domain(
            lambda: claims.pay_claim(claim, by=self.membership, account=account, paid_on=paid_on)
        )
        self.changed(CLAIMS, OVERDUE)
        return self.respond(claim)
