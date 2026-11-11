"""Owner endpoints of the reports for banks and investors (v12), under
`/api/v1/owner/companies/<id>/finance/`:

    GET   reports/balance-sheet/?on=&branch=     the balance sheet on a day (finance.view)
    GET   valuation/?on=                         what the business is worth (finance.view,
    PATCH valuation/                             every branch; changing the multiples needs
                                                 finance.manage)
    GET   statements/options/                    what the "Prepare a report" dialog offers
    GET   statements/                            your statement packs (kept 7 days)
    POST  statements/                            prepare one (finance.view + data.export, 202)
    GET   statements/{id}/                       its progress and, once ready, a signed link

Branch scope applies (§2.6): a member limited to some branches gets their branches' balance
sheet and packs; the valuation is the whole company's, so it needs every branch.
"""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import exceptions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.console.base import AllOf, OwnerAPIView
from apps.finance import conf, filters, statement_pack, statements
from apps.finance import statements_serializers as out
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import StatementPack
from apps.finance.owner_api import VIEW, FinanceMixin
from apps.members.permissions import Perm

VIEW_AND_MANAGE = AllOf(Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE)
LEDGER = "finance.ledger"


class BalanceSheetView(FinanceMixin, OwnerAPIView):
    """The balance sheet at the end of a day (today by default): assets, liabilities and
    equity in the base currency, how retained earnings are made, and what the books leave out."""

    perm = VIEW

    @extend_schema(
        parameters=[
            OpenApiParameter("on", str, description="The day, YYYY-MM-DD (today by default)."),
            OpenApiParameter("branch", int, many=True),
        ],
        responses=out.BalanceSheetSerializer,
    )
    def get(self, request, company_id):
        on = filters.day(request.query_params, "on") or self.today
        sheet = statements.balance_sheet(
            self.company, min(on, self.today), branch_ids=self.wanted_branches(), today=self.today
        )
        return Response(out.BalanceSheetSerializer(sheet).data)


class ValuationView(FinanceMixin, OwnerAPIView):
    """What the business is worth: the earnings method's range and the net assets, an estimate
    from the books (the whole company, so it needs every branch)."""

    perm = VIEW
    perms_by_action = {"patch": VIEW_AND_MANAGE}

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.branch_scope is not None:
            raise exceptions.PermissionDenied(
                _("Only someone who sees every branch can value the whole business.")
            )

    @extend_schema(
        parameters=[OpenApiParameter("on", str, description="The day (today by default).")],
        responses=out.ValuationSerializer,
    )
    def get(self, request, company_id):
        on = min(filters.day(request.query_params, "on") or self.today, self.today)
        return Response(self.valued(on))

    @extend_schema(request=out.ValuationUpdateSerializer, responses=out.ValuationSerializer)
    def patch(self, request, company_id):
        serializer = out.ValuationUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            row = conf.get_settings(self.company)
            row = type(row).objects.select_for_update().get(pk=row.pk)
            before = {
                "multiple_low": _text(row.valuation_multiple_low),
                "multiple_high": _text(row.valuation_multiple_high),
            }
            for field in ("multiple_low", "multiple_high"):
                if field in data:
                    setattr(row, f"valuation_{field}", data[field])
            low, high = row.valuation_multiple_low, row.valuation_multiple_high
            if low is not None and high is not None and low > high:
                row.valuation_multiple_low, row.valuation_multiple_high = high, low
            row.save(update_fields=["valuation_multiple_low", "valuation_multiple_high"])
            after = {
                "multiple_low": _text(row.valuation_multiple_low),
                "multiple_high": _text(row.valuation_multiple_high),
            }
            if after != before:
                self.audit(FinanceAction.VALUATION_SET, row, before=before, after=after)
        self.bump(LEDGER)
        return Response(self.valued(self.today))

    def valued(self, on) -> dict:
        worth = statements.worth(self.company, on)
        worth["editable"] = self.membership.has_perm(Perm.FINANCE_MANAGE)
        return out.ValuationSerializer(worth).data


def _text(value) -> str | None:
    return str(value) if value is not None else None


class StatementOptionsView(FinanceMixin, OwnerAPIView):
    """What the "Prepare a report" dialog offers the caller: how far back the books go,
    whether they may prepare a pack, and whether it can go to their Telegram."""

    perm = VIEW

    @extend_schema(responses=out.StatementOptionsSerializer)
    def get(self, request, company_id):
        language = request.user.language or self.company.default_language
        return Response(
            out.StatementOptionsSerializer(
                {
                    "today": self.today,
                    "books_start": statements.books_start(self.company),
                    "last_activity": statements.last_activity(self.company),
                    "language": language if language in statement_pack.LANGUAGES else "uz",
                    "whole_company": self.branch_scope is None,
                    "may_prepare": statement_pack.may_prepare(self.membership),
                    "telegram": request.user.telegram_id is not None,
                }
            ).data
        )


class StatementPacksView(FinanceMixin, OwnerAPIView):
    """Your statement packs in this company, the latest first (kept 7 days); POST prepares one
    in the background (poll its detail for the progress)."""

    perm = VIEW

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "export_create"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    @extend_schema(responses=out.StatementPackSerializer(many=True))
    def get(self, request, company_id):
        packs = (
            StatementPack.objects.filter(
                requested_by=self.membership,
                created_at__gte=timezone.now() - statement_pack.KEEP,
            )
            .select_related("company")
            .order_by("-created_at", "-pk")[:20]
        )
        return Response(out.StatementPackSerializer(packs, many=True, context=self.context()).data)

    @extend_schema(
        request=out.StatementPackRequestSerializer,
        responses={
            202: inline_serializer(
                "FinanceStatementPackCreated", {"id": serializers.IntegerField()}
            )
        },
    )
    def post(self, request, company_id):
        serializer = out.StatementPackRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            pack = statement_pack.request_pack(
                self.membership,
                period=data["period"],
                of=data["of"],
                purpose=data["purpose"],
                language=data["language"],
                branch_ids=self.picked_branches(data["branch"]),
                multiple_low=data.get("multiple_low"),
                multiple_high=data.get("multiple_high"),
                deliver_telegram=data["deliver_telegram"],
            )
        except DjangoPermissionDenied as exc:
            raise exceptions.PermissionDenied(str(exc)) from exc
        # request_pack bumps the statements pulse key after commit.
        return Response({"id": pack.pk}, status=status.HTTP_202_ACCEPTED)

    def picked_branches(self, picked: list[int]) -> list[int] | None:
        """The caller's scope narrowed to the branches picked (none picked: the whole scope);
        a branch outside it is refused."""
        if not picked:
            return self.branch_scope
        known = set(self.company.branches.values_list("pk", flat=True))
        allowed = known if self.branch_scope is None else known & set(self.branch_scope)
        if not set(picked) <= allowed:
            raise exceptions.ValidationError({"branch": [_("Pick one of your branches.")]})
        if self.branch_scope is None and set(picked) == known:
            return None
        return sorted(set(picked))


class StatementPackView(FinanceMixin, OwnerAPIView):
    """One of your statement packs: its progress, and a signed link once it is ready."""

    perm = VIEW

    @extend_schema(responses=out.StatementPackSerializer)
    def get(self, request, company_id, pk):
        pack = get_object_or_404(
            StatementPack.objects.select_related("company"),
            pk=pk,
            company=self.company,
            requested_by=self.membership,
        )
        return Response(out.StatementPackSerializer(pack, context=self.context()).data)
