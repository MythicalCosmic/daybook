"""Owner endpoints of the tax calendar (v12, `apps.finance.taxes`), under
`/api/v1/owner/companies/<id>/finance/taxes/`. Taxes are the whole company's, so every endpoint
needs a member who sees every branch (403 otherwise).

    GET    taxes/?back=&ahead=           the deadlines and what decides them      finance.view
    GET    taxes/candidates/?deadline=   ledger rows that may have paid one       finance.view
    POST   taxes/marks/                  mark a deadline done (paid or filed),
                                         linking or recording the payment        view + record
    DELETE taxes/marks/<id>/             take a mark back                         view + manage
    GET    taxes/compare/                turnover tax or VAT on the last 12 months finance.view
"""

from datetime import date

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, status
from rest_framework.response import Response

from apps.console.base import OwnerAPIView
from apps.finance import access, taxes
from apps.finance import loans_serializers as out
from apps.finance.models import TaxMark, Transaction
from apps.finance.owner_api import (
    VIEW,
    VIEW_AND_MANAGE,
    VIEW_AND_RECORD,
    FinanceMixin,
    _jsonable,
    domain,
)

PULSE = "finance.taxes"


class TaxMixin(FinanceMixin):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.branch_scope is not None:
            raise exceptions.PermissionDenied(
                _("Only someone who sees every branch sees the company's taxes.")
            )

    def deadline(self, key: str) -> taxes.Deadline:
        rule, _sep, start = (key or "").partition(":")
        try:
            day = date.fromisoformat(start)
        except ValueError:
            raise exceptions.ValidationError(
                {"deadline": [_("There is no such tax deadline.")]}
            ) from None
        return domain(lambda: taxes.find(self.company, rule, day))


def _months(value, default: int, top: int) -> int:
    try:
        return max(0, min(int(value), top))
    except TypeError, ValueError:
        return default


class TaxCalendarView(TaxMixin, OwnerAPIView):
    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("back", int, description="Months before this one (default 1)."),
            OpenApiParameter("ahead", int, description="Months after this one (default 12)."),
        ],
        responses=out.TaxCalendarSerializer,
    )
    def get(self, request, company_id):
        data = taxes.calendar_view(
            self.company,
            self.today,
            months_back=_months(request.query_params.get("back"), 1, 24),
            months_ahead=_months(request.query_params.get("ahead"), 12, 24),
        )
        return Response(_jsonable(data))


class TaxCandidatesView(TaxMixin, OwnerAPIView):
    perm = VIEW

    @extend_schema(
        parameters=[OpenApiParameter("deadline", str, description="<rule>:<period start>")],
        responses=out.TaxCandidateSerializer(many=True),
    )
    def get(self, request, company_id):
        deadline = self.deadline(request.query_params.get("deadline", ""))
        rows = taxes.candidates(self.company, deadline)
        return Response(
            _jsonable(
                [
                    {
                        "id": row.pk,
                        "occurred_on": row.occurred_on,
                        "amount": abs(row.base_amount),
                        "description": row.description,
                        "account": row.account.name if row.account_id else "",
                        "category": row.category.name if row.category_id else None,
                    }
                    for row in rows
                ]
            )
        )


class TaxMarksView(TaxMixin, OwnerAPIView):
    perm = VIEW_AND_RECORD

    @extend_schema(request=out.TaxMarkSerializer, responses={201: out.TaxMarkOutSerializer})
    def post(self, request, company_id):
        serializer = out.TaxMarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self.not_future(data["done_on"], "done_on")
        row = None
        if data.get("transaction") is not None:
            row = Transaction.objects.filter(company=self.company, pk=data["transaction"]).first()
            if row is None:
                raise exceptions.ValidationError({"transaction": [_("Pick one of the payments.")]})
        account = None
        if data.get("account") is not None:
            account = self.account(data["account"], access.recordable_accounts(self.membership))
        mark = domain(
            lambda: taxes.mark(
                self.company,
                by=self.membership,
                rule_key=data["rule"],
                period_start=data["period_start"],
                done_on=data["done_on"],
                transaction_row=row,
                account=account,
                amount=data.get("amount"),
                note=data.get("note", ""),
            )
        )
        self.changed(PULSE)
        return Response(out.TaxMarkOutSerializer(mark).data, status=status.HTTP_201_CREATED)


class TaxMarkView(TaxMixin, OwnerAPIView):
    perm = VIEW_AND_MANAGE

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, pk):
        mark = get_object_or_404(TaxMark.objects.filter(company=self.company), pk=pk)
        domain(lambda: taxes.unmark(mark, by=self.membership))
        self.changed(PULSE)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TaxCompareView(TaxMixin, OwnerAPIView):
    perm = VIEW

    @extend_schema(responses=out.TaxCompareSerializer)
    def get(self, request, company_id):
        return Response(_jsonable(taxes.compare(self.company, self.today)))
