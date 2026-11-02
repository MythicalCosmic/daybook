"""Employee (mini app) endpoints of payroll; routed in `urls.py` under
`/api/v1/companies/<id>/payroll/…` (docs/PLAN-OWNER.md §4.11, prefix E).

Everything here is the signed-in person's own pay (no permission needed; nobody else's rows
are ever reachable). While the module is off the endpoints answer 403. A suspended person can
still read their wallet (`allow_suspended`), but not change anything.
"""

from django.db.models import Prefetch
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.members.api import IsCompanyMember
from apps.members.models import Membership
from apps.payroll import periods, queries, services
from apps.payroll import serializers as s
from apps.payroll.models import Adjustment, Advance, AdvanceRepayment, Payslip


class PayrollOn(BasePermission):
    """After IsCompanyMember: the module must be switched on."""

    def has_permission(self, request, view):
        if not view.membership.company.has_feature("payroll"):
            raise PermissionDenied(_("Payroll isn't switched on for this company."))
        return True


class WalletView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, PayrollOn)
    allow_suspended = True
    membership: Membership

    @property
    def company(self):
        return self.membership.company

    def context(self) -> dict:
        # Their own pay: the person always sees the amounts.
        return {"show_amounts": True, "request": self.request}


class MyAdjustmentsView(WalletView):
    """My bonuses, fines, allowances and deductions (proposed, approved, rejected, taken
    back), newest month first."""

    @extend_schema(
        parameters=[OpenApiParameter("period", str, description="A month: YYYY-MM.")],
        responses=s.AdjustmentSerializer(many=True),
    )
    def get(self, request, company_id):
        rows = Adjustment.objects.filter(membership=self.membership).select_related(
            "membership__user", "rule", "task", "proposed_by", "decided_by"
        )
        if value := request.query_params.get("period"):
            try:
                rows = rows.filter(period=periods.parse_period(value))
            except Exception as exc:
                raise ValidationError({"period": [_("Give a month as YYYY-MM.")]}) from exc
        rows = rows.order_by("-period", "-created_at", "-pk")[:200]
        return Response(s.AdjustmentSerializer(rows, many=True, context=self.context()).data)


class DisputeView(WalletView):
    """Dispute one of my fines or deductions, once, with a short explanation."""

    allow_suspended = False

    @extend_schema(request=s.DisputeSerializer, responses=s.AdjustmentSerializer)
    def post(self, request, company_id, pk):
        row = Adjustment.objects.filter(membership=self.membership, pk=pk).first()
        if row is None:
            raise NotFound
        serializer = s.DisputeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.dispute(row, by=self.membership, text=serializer.validated_data["text"])
        return Response(s.AdjustmentSerializer(row, context=self.context()).data)


def _my_advances(membership: Membership):
    return (
        Advance.objects.filter(membership=membership)
        .select_related("membership__user", "requested_by", "decided_by", "paid_by")
        .prefetch_related(
            Prefetch("repayments", queryset=AdvanceRepayment.objects.select_related("payslip_line"))
        )
        .order_by("-created_at", "-pk")
    )


class MyAdvancesView(WalletView):
    """My advances and how much more I may ask for now (`cap.available`)."""

    @extend_schema(responses=s.MyAdvancesSerializer)
    def get(self, request, company_id):
        cap = queries.advance_cap(self.membership)
        advances = _my_advances(self.membership)[:50]
        return Response(
            {
                "cap": s.AdvanceCapSerializer(cap).data,
                "advances": s.AdvanceSerializer(advances, many=True, context=self.context()).data,
            }
        )

    @extend_schema(request=s.AdvanceRequestSerializer, responses={201: s.AdvanceSerializer})
    def post(self, request, company_id):
        if self.membership.status != Membership.Status.APPROVED:
            raise PermissionDenied(_("Your access is paused."))
        serializer = s.AdvanceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = services.request_advance(
            self.membership,
            by=self.membership,
            amount=data["amount"],
            reason=data["reason"],
            installments=data["installments"],
        )
        row = _my_advances(self.membership).get(pk=row.pk)
        return Response(
            s.AdvanceSerializer(row, context=self.context()).data, status=status.HTTP_201_CREATED
        )


class CancelAdvanceView(WalletView):
    """Take back my advance request while nobody has decided it."""

    allow_suspended = False

    @extend_schema(request=None, responses=s.AdvanceSerializer)
    def post(self, request, company_id, pk):
        row = Advance.objects.filter(membership=self.membership, pk=pk).first()
        if row is None:
            raise NotFound
        services.cancel_advance(row, by=self.membership)
        row = _my_advances(self.membership).get(pk=row.pk)
        return Response(s.AdvanceSerializer(row, context=self.context()).data)


# Earned so far --------------------------------------------------------------------------


class EarningsView(WalletView):
    """This month so far and the month's estimate: base pay, extras, task pay, bonuses and
    fines, advances, expenses paid back, proposed bonuses and fines apart, and how far each
    bonus rule is (cached for 10 minutes)."""

    @extend_schema(responses=s.EarningsSerializer)
    def get(self, request, company_id):
        from apps.payroll import earnings

        return Response(earnings.current(self.membership))


# Payslips -------------------------------------------------------------------------------


def _my_payslips(membership: Membership):
    """My published and paid payslips (drafts are nobody's business yet), newest first."""
    return (
        Payslip.objects.filter(membership=membership, published_at__isnull=False)
        .exclude(status=Payslip.Status.DRAFT)
        .select_related(
            "membership__user", "membership__position", "membership__home_branch", "run"
        )
        .order_by("-run__period", "-pk")
    )


class MyPayslipsView(WalletView):
    """My payslips: the month, the net and whether it is paid and received."""

    @extend_schema(responses=s.PayslipRowSerializer(many=True))
    def get(self, request, company_id):
        rows = _my_payslips(self.membership).prefetch_related("lines")[:60]
        return Response(s.PayslipRowSerializer(rows, many=True, context=self.context()).data)


class MyPayslipView(WalletView):
    """One of my payslips with every line; opening it marks it seen."""

    def payslip(self, pk) -> Payslip:
        payslip = _my_payslips(self.membership).filter(pk=pk).first()
        if payslip is None:
            raise NotFound
        return payslip

    @extend_schema(responses=s.PayslipSerializer)
    def get(self, request, company_id, pk):
        payslip = services.mark_viewed(self.payslip(pk), by=self.membership)
        return Response(s.PayslipSerializer(payslip, context=self.context()).data)


class MyPayslipPdfView(MyPayslipView):
    """A short-lived link to my payslip as a PDF, in my language."""

    @extend_schema(responses=s.FileLinkSerializer)
    def get(self, request, company_id, pk):
        from apps.payroll.owner_api import pdf_link

        return Response(pdf_link(self.payslip(pk), request))


class ReceivedView(MyPayslipView):
    """I received this pay ("I received it")."""

    allow_suspended = False

    @extend_schema(request=None, responses=s.PayslipSerializer)
    def post(self, request, company_id, pk):
        payslip = services.confirm_received(self.payslip(pk), by=self.membership)
        payslip = self.payslip(payslip.pk)
        return Response(s.PayslipSerializer(payslip, context=self.context()).data)
