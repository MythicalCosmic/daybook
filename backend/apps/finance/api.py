"""Employee (mini app) endpoints of the finance ledger; routed in `urls.py` under
`/api/v1/companies/<id>/finance/…` (docs/PLAN-OWNER.md §4.7, prefix E, Package I).

A person's own expense claims: list, submit (with receipt photos) and cancel; the expense
categories to pick from; and their wallet (company cash they hold, what the company owes them
back). Needs `finance.claim` and the finance module on (403 otherwise); nobody else's claims
are ever reachable.
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import DomainError
from apps.finance import claims
from apps.finance import planning_serializers as s
from apps.finance.models import Category, Claim
from apps.members.api import IsCompanyMember
from apps.members.models import Membership
from apps.members.permissions import Perm


class ClaimsOn(BasePermission):
    """After IsCompanyMember: the finance module is on and the person may claim expenses."""

    def has_permission(self, request, view):
        membership = view.membership
        if not membership.company.has_feature("finance"):
            raise PermissionDenied(_("Finance isn't switched on for this company."))
        if not membership.has_perm(Perm.FINANCE_CLAIM):
            raise PermissionDenied(_("You don't have permission to do this."))
        return True


class ClaimView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, ClaimsOn)
    membership: Membership

    @property
    def company(self):
        return self.membership.company

    def context(self) -> dict:
        return {"request": self.request, "membership": self.membership}

    def mine(self):
        return claims.with_relations(Claim.objects.filter(membership=self.membership))


class MyClaimsView(ClaimView):
    """My expense claims, newest first; POST submits one (multipart, with receipts)."""

    parser_classes = (MultiPartParser, FormParser, JSONParser)

    @extend_schema(
        parameters=[OpenApiParameter("status", str)],
        responses=s.ClaimSerializer(many=True),
    )
    def get(self, request, company_id):
        claims.sync_paid(self.company)
        rows = self.mine()
        if wanted := request.query_params.get("status"):
            if wanted not in Claim.Status.values:
                raise ValidationError({"status": [_("Unknown status.")]})
            rows = rows.filter(status=wanted)
        rows = rows.order_by("-created_at", "-pk")[:100]
        return Response(s.ClaimSerializer(rows, many=True, context=self.context()).data)

    @extend_schema(request=s.ClaimCreateSerializer, responses={201: s.ClaimSerializer})
    def post(self, request, company_id):
        files = request.FILES.getlist("receipts")
        data = {key: request.data.get(key) for key in request.data if key != "receipts"}
        serializer = s.ClaimCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if len(files) > claims.MAX_RECEIPTS:
            raise ValidationError(
                {"receipts": [_("Attach at most %(n)s receipts.") % {"n": claims.MAX_RECEIPTS}]}
            )
        category = claims.expense_categories(self.company).filter(pk=values["category"]).first()
        if category is None:
            raise ValidationError({"category": [_("Pick an expense category.")]})
        try:
            claim = claims.submit_claim(
                self.company,
                by=self.membership,
                amount=values["amount"],
                category=category,
                spent_on=values["spent_on"],
                paid_from=values["paid_from"],
                description=values.get("description", ""),
                receipt_files=files,
                via=Claim.Via.MINIAPP,
            )
        except DomainError as error:
            raise ValidationError({"detail": str(error)}) from None
        claim = self.mine().get(pk=claim.pk)
        return Response(
            s.ClaimSerializer(claim, context=self.context()).data, status=status.HTTP_201_CREATED
        )


class CancelClaimView(ClaimView):
    """Take back my claim while nobody has decided it."""

    @extend_schema(request=None, responses=s.ClaimSerializer)
    def post(self, request, company_id, pk):
        claim = Claim.objects.filter(membership=self.membership, pk=pk).first()
        if claim is None:
            raise NotFound
        try:
            claims.cancel_claim(claim, by=self.membership)
        except DomainError as error:
            raise ValidationError({"detail": str(error)}) from None
        claim = self.mine().get(pk=claim.pk)
        return Response(s.ClaimSerializer(claim, context=self.context()).data)


class ClaimCategoriesView(ClaimView):
    """The expense categories a person may claim (what the system books itself is left out)."""

    @extend_schema(responses=s.ClaimCategorySerializer(many=True))
    def get(self, request, company_id):
        rows: list[Category] = list(claims.expense_categories(self.company))
        return Response(
            [
                {
                    "id": row.pk,
                    "name": row.name,
                    "parent_id": row.parent_id,
                    "icon": row.icon,
                    "color": row.color,
                }
                for row in rows
            ]
        )


class WalletView(ClaimView):
    """Company cash I hold and what the company owes me back."""

    @extend_schema(responses=s.WalletSerializer)
    def get(self, request, company_id):
        return Response(claims.wallet(self.membership))
