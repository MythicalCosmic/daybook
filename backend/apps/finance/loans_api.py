"""Owner endpoints of loans (v12, `apps.finance.loans`), under
`/api/v1/owner/companies/<id>/finance/loans/`.

    GET  loans/                      the loans the caller sees, with totals          finance.view
    POST loans/                      record a loan (a loan from before the books:
                                     finance.manage)                       finance.view + record
    POST loans/preview/              the schedule terms would make, nothing saved     finance.view
    GET  loans/<id>/                 a loan: terms, schedule, payments                finance.view
    PUT  loans/<id>/schedule/        new terms or the bank's rows, before the first
                                     payment                                view + manage
    POST loans/<id>/pay/             pay one payment (principal and interest)         view + record
    POST loans/<id>/repay-early/     repay principal early, the rest planned again    view + record
    POST loans/<id>/undo/            take one payment back                            view + manage

A loan is visible with its debt (`access.visible_debts`: finance.view and the branch scope); one
outside them answers 404. Writes go through `loans` (audited there) and bump `finance.ledger` and
`finance.overdue`.
"""

from datetime import timedelta
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, status
from rest_framework.response import Response

from apps.console.base import OwnerAPIView
from apps.core.money import quantize
from apps.finance import access, loan_math, loans, queries
from apps.finance import loans_serializers as out
from apps.finance import owner_serializers as ledger_out
from apps.finance.models import Debt, DebtInstallment, Loan, Transaction
from apps.finance.owner_api import (
    OVERDUE,
    TRANSACTION_RELATIONS,
    VIEW,
    VIEW_AND_MANAGE,
    VIEW_AND_RECORD,
    FinanceMixin,
    _jsonable,
    domain,
)

ZERO = Decimal(0)


def loan_data(loan: Loan, today, rows: list[dict] | None = None) -> dict:
    debt = loan.debt
    rows = rows if rows is not None else loans.lines(loan, today)
    summary = loans.summary(loan, today, rows)
    return {
        "id": loan.pk,
        "debt_id": debt.pk,
        "direction": debt.direction,
        "direction_label": str(loans.DIRECTION_LABELS[debt.direction]),
        "counterparty": {"id": debt.counterparty_id, "name": debt.counterparty.name},
        "branch": {"id": debt.branch_id, "name": debt.branch.name} if debt.branch_id else None,
        "account": (
            {
                "id": loan.account_id,
                "name": loan.account.name,
                "kind": loan.account.kind,
                "currency": loan.account.currency,
            }
            if loan.account_id
            else None
        ),
        "description": debt.description,
        "currency": debt.currency,
        "status": debt.status,
        "is_opening": debt.is_opening,
        "issued_on": debt.issued_on,
        "ends_on": summary["ends_on"],
        "annual_rate": str(loan.annual_rate),
        "method": loan.method,
        "method_label": str(loan.get_method_display()),
        "basis": loan.basis,
        "term_months": loan.term_months,
        "first_due_on": loan.first_due_on,
        "grace_months": loan.grace_months,
        "fee": loan.fee,
        "amount": debt.amount,
        "owed": summary["owed"],
        "paid_principal": summary["paid_principal"],
        "interest_paid": summary["interest_paid"],
        "interest_left": summary["interest_left"],
        "next": summary["next"],
        "overdue_count": summary["overdue_count"],
        "overdue_amount": summary["overdue_amount"],
        "payments_left": summary["payments_left"],
        "payments": summary["payments"],
    }


def _rows(data: list[dict] | None) -> list[loan_math.Row] | None:
    if data is None:
        return None
    return [
        loan_math.Row(row["due_on"], Decimal(row["principal"]), Decimal(row.get("interest") or 0))
        for row in data
    ]


class LoanMixin(FinanceMixin):
    def loans(self):
        return loans.visible_loans(self.membership)

    def loan(self, pk) -> Loan:
        return get_object_or_404(self.loans(), pk=pk)

    def detail(self, loan: Loan) -> dict:
        today = self.today
        rows = loans.lines(loan, today)
        context = self.context()
        payments = loans.payments(loan)
        open_ = loan.debt.status == Debt.Status.OPEN
        started = loans.started(loan)
        return _jsonable(
            {
                "loan": loan_data(loan, today, rows),
                "schedule": rows,
                "payments": ledger_out.TransactionSerializer(
                    Transaction.objects.filter(pk__in=[row.pk for row in payments])
                    .select_related(*TRANSACTION_RELATIONS)
                    .prefetch_related("receipts")
                    .order_by("occurred_on", "pk"),
                    many=True,
                    context=context,
                ).data,
                "can_pay": open_ and access.can_record(self.membership),
                "can_edit_schedule": open_ and not started and access.can_manage(self.membership),
                "can_undo": access.can_manage(self.membership),
            }
        )

    def written(self, loan: Loan, *, created: bool = False) -> Response:
        self.changed(OVERDUE)
        loan = self.loans().get(pk=loan.pk)
        return Response(
            self.detail(loan), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class LoansView(LoanMixin, OwnerAPIView):
    perm = VIEW
    perms_by_action = {"post": VIEW_AND_RECORD}

    @extend_schema(operation_id="finance_loans_list", responses=out.LoanListSerializer)
    def get(self, request, company_id):
        today = self.today
        value = queries.valuation(self.company, today)
        found = []
        owed = owed_to_us = due = overdue = ZERO
        for loan in self.loans():
            rows = loans.lines(loan, today)
            data = loan_data(loan, today, rows)
            found.append(data)
            if loan.debt.status != Debt.Status.OPEN:
                continue
            base = value.to_base(data["owed"], loan.debt.currency) or ZERO
            if loan.debt.direction == Debt.Direction.PAYABLE:
                owed += base
            else:
                owed_to_us += base
            for row in rows:
                if row["status"] == "paid" or loan.debt.direction != Debt.Direction.PAYABLE:
                    continue
                rest = value.to_base(row["rest"], loan.debt.currency) or ZERO
                if row["status"] == "overdue":
                    overdue += rest
                elif row["due_on"] <= today + timedelta(days=30):
                    due += rest
        found.sort(key=lambda row: (row["status"] != Debt.Status.OPEN, row["ends_on"] or today))
        return Response(
            _jsonable(
                {
                    "currency": self.company.base_currency,
                    "owed": quantize(owed),
                    "owed_to_us": quantize(owed_to_us),
                    "due_30": quantize(due),
                    "overdue": quantize(overdue),
                    "loans": found,
                }
            )
        )

    @extend_schema(request=out.LoanCreateSerializer, responses={201: out.LoanSerializer})
    def post(self, request, company_id):
        serializer = out.LoanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self.not_future(data["issued_on"], "issued_on")
        account = None
        if data.get("account") is not None:
            account = self.account(data["account"], access.recordable_accounts(self.membership))
        elif not access.can_manage(self.membership):
            raise exceptions.PermissionDenied(
                _("A loan from before the books needs finance.manage.")
            )
        method = data["method"]
        if method != Loan.Method.CUSTOM and not data.get("first_due_on"):
            raise exceptions.ValidationError({"first_due_on": [_("Pick the first payment's day.")]})
        if method == Loan.Method.CUSTOM and not data.get("rows"):
            raise exceptions.ValidationError({"rows": [_("Add at least one payment.")]})
        party = self.party(data["counterparty"])
        loan = domain(
            lambda: loans.create(
                self.company,
                by=self.membership,
                direction=data["direction"],
                counterparty=party,
                amount=data["amount"],
                currency=data["currency"],
                issued_on=data["issued_on"],
                annual_rate=data["annual_rate"],
                method=method,
                basis=data["basis"],
                term_months=data["term_months"],
                first_due_on=data.get("first_due_on") or data["issued_on"],
                grace_months=data["grace_months"],
                fee=data.get("fee") or 0,
                rows=_rows(data.get("rows")),
                account=account,
                branch=self.write_branch(data.get("branch")),
                responsible=self.member(data.get("responsible"), "responsible"),
                description=data.get("description", ""),
            )
        )
        self.changed(OVERDUE)
        loan = self.loans().get(pk=loan.pk)
        return Response(_jsonable(loan_data(loan, self.today)), status=status.HTTP_201_CREATED)


class LoanPreviewView(LoanMixin, OwnerAPIView):
    perm = VIEW

    @extend_schema(request=out.LoanTermsSerializer, responses=out.LoanPreviewSerializer)
    def post(self, request, company_id):
        serializer = out.LoanTermsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        method = data["method"]
        if method != Loan.Method.CUSTOM and not data.get("first_due_on"):
            raise exceptions.ValidationError({"first_due_on": [_("Pick the first payment's day.")]})
        result = domain(
            lambda: loans.preview(
                amount=data["amount"],
                currency=data["currency"],
                issued_on=data["issued_on"],
                annual_rate=data["annual_rate"],
                method=method,
                basis=data["basis"],
                term_months=data["term_months"],
                first_due_on=data.get("first_due_on") or data["issued_on"],
                grace_months=data["grace_months"],
                fee=data.get("fee") or 0,
                rows=_rows(data.get("rows")),
            )
        )
        return Response(_jsonable(result))


class LoanView(LoanMixin, OwnerAPIView):
    perm = VIEW

    @extend_schema(responses=out.LoanDetailSerializer)
    def get(self, request, company_id, pk):
        return Response(self.detail(self.loan(pk)))


class LoanScheduleView(LoanMixin, OwnerAPIView):
    perm = VIEW_AND_MANAGE

    @extend_schema(request=out.ScheduleUpdateSerializer, responses=out.LoanDetailSerializer)
    def put(self, request, company_id, pk):
        loan = self.loan(pk)
        serializer = out.ScheduleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        rows = _rows(data.pop("rows", None))
        domain(lambda: loans.replace_schedule(loan, by=self.membership, rows=rows, **data))
        return self.written(loan)


class LoanPayView(LoanMixin, OwnerAPIView):
    perm = VIEW_AND_RECORD

    @extend_schema(request=out.LoanPaySerializer, responses=out.LoanDetailSerializer)
    def post(self, request, company_id, pk):
        loan = self.loan(pk)
        serializer = out.LoanPaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self.not_future(data["paid_on"], "paid_on")
        installment = DebtInstallment.objects.filter(debt=loan.debt, pk=data["installment"]).first()
        if installment is None:
            raise exceptions.ValidationError({"installment": [_("Pick one of its payments.")]})
        account = self.account(data["account"], access.recordable_accounts(self.membership))
        domain(
            lambda: loans.pay(
                installment,
                by=self.membership,
                account=account,
                paid_on=data["paid_on"],
                principal=data.get("principal"),
                interest=data.get("interest"),
            )
        )
        return self.written(loan)


class LoanEarlyView(LoanMixin, OwnerAPIView):
    perm = VIEW_AND_RECORD

    @extend_schema(request=out.LoanEarlySerializer, responses=out.LoanDetailSerializer)
    def post(self, request, company_id, pk):
        loan = self.loan(pk)
        serializer = out.LoanEarlySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self.not_future(data["paid_on"], "paid_on")
        account = self.account(data["account"], access.recordable_accounts(self.membership))
        domain(
            lambda: loans.repay_early(
                loan,
                by=self.membership,
                account=account,
                paid_on=data["paid_on"],
                amount=data["amount"],
                interest=data.get("interest") or 0,
                mode=data["mode"],
            )
        )
        return self.written(loan)


class LoanUndoView(LoanMixin, OwnerAPIView):
    perm = VIEW_AND_MANAGE

    @extend_schema(request=out.LoanUndoSerializer, responses=out.LoanDetailSerializer)
    def post(self, request, company_id, pk):
        loan = self.loan(pk)
        serializer = out.LoanUndoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = Transaction.objects.filter(
            company=self.company, pk=serializer.validated_data["transaction"]
        ).first()
        if row is None:
            raise exceptions.ValidationError({"transaction": [_("Pick one of its payments.")]})
        domain(
            lambda: loans.undo_payment(
                loan, row, by=self.membership, reason=serializer.validated_data["reason"]
            )
        )
        return self.written(loan)
