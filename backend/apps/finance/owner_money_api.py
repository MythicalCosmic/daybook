"""Owner endpoints of the owner's money (v11), under `/api/v1/owner/companies/<id>/finance/`:

    GET    owner-money/                          the safe amount with its reasons, this month's
                                                 draws, the suggestion, the history, the accounts
    POST   owner-money/take/  owner-money/put/   take money out / put money in (owner entries)
    PATCH  owner-money/settings/                 the cash buffer and the horizon
    POST   owner-money/purchases/                plan a purchase
    PATCH  DELETE owner-money/purchases/<id>/    change, mark bought, remove
    GET    PUT partners/                         the partners now and before; set them from a day
    GET    partners/profit-share/?from&to        each partner's part of a period's profit
    GET    POST dividends/                       dividend rounds; prepare one
    GET    dividends/suggest/?from&to            the amount a round for the period could pay
    PATCH  dividends/<id>/                       change a draft round
    POST   dividends/<id>/pay/  …/cancel/        pay its lines from an account; drop it
    POST   dividends/<id>/lines/<line>/undo/     take one line's payment back

The owner's money is the whole company's: every endpoint needs `finance.view` and
`finance.manage` (owners hold both) and a caller who sees every branch. Writes go through
`owner_draw` and `partners` (which audit), and bump `finance.ledger` after commit.
"""

from datetime import date

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, status
from rest_framework.response import Response

from apps.companies.models import Branch
from apps.console import pulse
from apps.console.base import AllOf, OwnerAPIView
from apps.finance import access, conf, owner_draw
from apps.finance import owner_money_serializers as s
from apps.finance import partners as partners_service
from apps.finance.models import Dividend, DividendLine, Partner, PlannedPurchase
from apps.finance.owner_api import LEDGER, FinanceMixin, _jsonable, domain
from apps.members.models import Membership
from apps.members.permissions import Perm

OWNER_MONEY = AllOf(Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE)
SUMMARY_TTL = 120


class OwnerMoneyMixin(FinanceMixin):
    """Finance on, both permissions (the view's `perm`), and every branch in sight."""

    perm = OWNER_MONEY

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.branch_scope is not None:
            raise exceptions.PermissionDenied(
                _("The owner's money is the whole company's: it needs access to every branch.")
            )

    def draw_account(self, pk):
        found = owner_draw.draw_accounts(self.membership).filter(pk=pk).first()
        if found is None:
            raise exceptions.ValidationError({"account": [_("Pick one of the business accounts.")]})
        return found

    def day(self, value, field: str) -> date:
        return self.not_future(value, field) if value is not None else self.today


def summary(company, member: Membership, today: date) -> dict:
    """Everything the owner's money page shows (cached per ledger version and day)."""
    version = pulse.versions(company.pk, [LEDGER])[LEDGER]
    key = f"finance:owner-money:{company.pk}:{member.pk}:{version}:{today.isoformat()}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = owner_draw.safe_amount(company, today)
    row = conf.get_settings(company)
    accounts = owner_draw.draw_accounts(member)
    payload = {
        **data,
        "purchases": {
            "kept": s.PurchaseSerializer(data["purchases"]["kept"], many=True).data,
            "later": s.PurchaseSerializer(data["purchases"]["later"], many=True).data,
        },
        "suggestion": owner_draw.suggested_monthly(company, today),
        "history": owner_draw.history(company, 6, today),
        "accounts": [
            {
                "id": account.pk,
                "name": account.name,
                "kind": account.kind,
                "currency": account.currency,
                "balance": account.balance,
                "branch_id": account.branch_id,
            }
            for account in accounts
        ],
        "settings": {"cash_buffer": row.cash_buffer, "draw_horizon_days": row.draw_horizon_days},
        "partners": len(partners_service.current(company)),
        "is_owner": access.is_owner(member),
    }
    result = _jsonable(payload)
    cache.set(key, result, SUMMARY_TTL)
    return result


class OwnerMoneyView(OwnerMoneyMixin, OwnerAPIView):
    """The safe amount to take out today with its reasons, this month's draws and
    contributions, a monthly amount the forecast carries, six months of profit against draws,
    planned purchases and the accounts money can be taken from."""

    @extend_schema(responses=s.OwnerMoneySerializer)
    def get(self, request, company_id):
        return Response(summary(self.company, self.membership, self.today))


class TakeView(OwnerMoneyMixin, OwnerAPIView):
    """Take money out of the business (an owner draw). Above the safe amount it needs
    `confirmed: true`."""

    @extend_schema(request=s.MoveInputSerializer, responses={201: s.MoveResultSerializer})
    def post(self, request, company_id):
        data = self._valid(request)
        try:
            row = owner_draw.take(
                self.company,
                by=self.membership,
                account=self.draw_account(data["account"]),
                amount=data["amount"],
                occurred_on=self.day(data.get("occurred_on"), "occurred_on"),
                description=data.get("description", ""),
                confirmed=data.get("confirmed", False),
            )
        except owner_draw.OverSafe as error:
            raise exceptions.ValidationError(
                {"amount": [str(error)], "safe": [str(error.safe)], "code": ["over_safe"]}
            ) from None
        return self._done(row)

    def _valid(self, request) -> dict:
        serializer = s.MoveInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _done(self, row) -> Response:
        self.changed()
        safe = owner_draw.safe_amount(self.company)["safe"]
        return Response(
            _jsonable(
                {
                    "id": row.pk,
                    "occurred_on": row.occurred_on,
                    "amount": abs(row.amount),
                    "account": row.account_id,
                    "safe": safe,
                }
            ),
            status=status.HTTP_201_CREATED,
        )


class PutView(TakeView):
    """Put the owner's own money into the business (an owner contribution)."""

    @extend_schema(request=s.MoveInputSerializer, responses={201: s.MoveResultSerializer})
    def post(self, request, company_id):
        data = self._valid(request)
        row = domain(
            lambda: owner_draw.put(
                self.company,
                by=self.membership,
                account=self.draw_account(data["account"]),
                amount=data["amount"],
                occurred_on=self.day(data.get("occurred_on"), "occurred_on"),
                description=data.get("description", ""),
            )
        )
        return self._done(row)


class OwnerMoneySettingsView(OwnerMoneyMixin, OwnerAPIView):
    """The cash buffer (empty: one month of fixed costs) and how many days of payments due the
    safe amount keeps back."""

    @extend_schema(request=s.SettingsInputSerializer, responses=s.OwnerMoneySettingsSerializer)
    def patch(self, request, company_id):
        serializer = s.SettingsInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = domain(
            lambda: owner_draw.update_settings(
                self.company, by=self.membership, **serializer.validated_data
            )
        )
        self.changed()
        return Response(
            _jsonable({"cash_buffer": row.cash_buffer, "draw_horizon_days": row.draw_horizon_days})
        )


class PurchasesView(OwnerMoneyMixin, OwnerAPIView):
    """Plan a purchase the safe amount keeps money back for."""

    @extend_schema(request=s.PurchaseInputSerializer, responses={201: s.PurchaseSerializer})
    def post(self, request, company_id):
        serializer = s.PurchaseInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = domain(
            lambda: owner_draw.plan_purchase(
                self.company,
                by=self.membership,
                title=data["title"],
                amount=data["amount"],
                due_on=data.get("due_on"),
                branch=self._branch(data.get("branch")),
            )
        )
        self.changed()
        return Response(s.PurchaseSerializer(row).data, status=status.HTTP_201_CREATED)

    def _branch(self, pk) -> Branch | None:
        if pk is None:
            return None
        found = Branch.objects.filter(company=self.company, pk=pk).first()
        if found is None:
            raise exceptions.ValidationError({"branch": [_("Pick a branch.")]})
        return found


class PurchaseView(PurchasesView):
    """Change a planned purchase, mark it bought (or dropped), or remove it."""

    def _row(self, pk) -> PlannedPurchase:
        return get_object_or_404(PlannedPurchase.objects.for_company(self.company), pk=pk)

    @extend_schema(request=s.PurchasePatchSerializer, responses=s.PurchaseSerializer)
    def patch(self, request, company_id, pk):
        row = self._row(pk)
        serializer = s.PurchasePatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        if "branch" in fields:
            fields["branch"] = self._branch(fields["branch"])
        row = domain(lambda: owner_draw.update_purchase(row, by=self.membership, **fields))
        self.changed()
        return Response(s.PurchaseSerializer(row).data)

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, company_id, pk):
        row = self._row(pk)
        domain(lambda: owner_draw.remove_purchase(row, by=self.membership))
        self.changed()
        return Response(status=status.HTTP_204_NO_CONTENT)


# Partners ----------------------------------------------------------------------------------------


class PartnersView(OwnerMoneyMixin, OwnerAPIView):
    """The partners now (their shares add up to 100 %) and before; PUT sets them from a day."""

    @extend_schema(responses=s.PartnersSerializer)
    def get(self, request, company_id):
        return Response(self._payload())

    @extend_schema(request=s.PartnersInputSerializer, responses=s.PartnersSerializer)
    def put(self, request, company_id):
        serializer = s.PartnersInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        people = {
            member.pk: member
            for member in Membership.objects.for_company(self.company).filter(
                pk__in=[row["member"] for row in data["partners"] if row.get("member")]
            )
        }
        rows = []
        for row in data["partners"]:
            member = None
            if row.get("member"):
                member = people.get(row["member"])
                if member is None:
                    raise exceptions.ValidationError(
                        {"partners": [_("Pick a person of the company.")]}
                    )
            rows.append({"membership": member, "name": row.get("name", ""), "share": row["share"]})
        domain(
            lambda: partners_service.set_partners(
                self.company, by=self.membership, effective_on=data["effective_on"], rows=rows
            )
        )
        self.changed()
        return Response(self._payload())

    def _payload(self) -> dict:
        company = self.company
        now = partners_service.current(company)
        before = (
            Partner.objects.for_company(company)
            .filter(ends_on__isnull=False)
            .select_related("membership")
            .order_by("-starts_on", "-share", "pk")
        )
        people = (
            Membership.objects.for_company(company)
            .filter(status__in=(Membership.Status.APPROVED, Membership.Status.SUSPENDED))
            .order_by("first_name", "last_name", "pk")
        )
        return {
            "current": s.PartnerSerializer(now, many=True).data,
            "history": s.PartnerSerializer(before[:50], many=True).data,
            "since": min((row.starts_on for row in now), default=None),
            "people": [{"id": person.pk, "name": str(person)} for person in people],
        }


class ProfitShareView(OwnerMoneyMixin, OwnerAPIView):
    """Each partner's part of a period's net profit, by the days they held each share, with
    the dividends paid to them for rounds of the period (default: this year so far)."""

    @extend_schema(
        parameters=[OpenApiParameter("from", str), OpenApiParameter("to", str)],
        responses=s.ProfitShareSerializer,
    )
    def get(self, request, company_id):
        start, end = _period(request, self.today)
        data = domain(lambda: partners_service.profit_share(self.company, start, end))
        return Response(_jsonable(data))


# Dividends ---------------------------------------------------------------------------------------


def _period(request, today: date) -> tuple[date, date]:
    """`from`/`to` of the query (YYYY-MM-DD), this year so far by default."""
    values = []
    for key, default in (("from", today.replace(month=1, day=1)), ("to", today)):
        raw = request.query_params.get(key)
        if not raw:
            values.append(default)
            continue
        try:
            values.append(date.fromisoformat(raw))
        except ValueError:
            raise exceptions.ValidationError({key: [_("A day like 2026-10-01.")]}) from None
    if values[1] < values[0]:
        raise exceptions.ValidationError({"to": [_("The period ends before it starts.")]})
    return values[0], values[1]


class DividendsView(OwnerMoneyMixin, OwnerAPIView):
    """Every dividend round, the latest first; POST prepares one (a draft)."""

    @extend_schema(responses=s.DividendSerializer(many=True))
    def get(self, request, company_id):
        rows = partners_service.dividends(self.company)[:100]
        return Response(s.DividendSerializer(rows, many=True).data)

    @extend_schema(request=s.DividendInputSerializer, responses={201: s.DividendSerializer})
    def post(self, request, company_id):
        serializer = s.DividendInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = domain(
            lambda: partners_service.create_dividend(
                self.company,
                by=self.membership,
                period_start=data["period_start"],
                period_end=data["period_end"],
                amount=data["amount"],
                note=data.get("note", ""),
            )
        )
        self.changed()
        return Response(_dividend(row), status=status.HTTP_201_CREATED)


def _dividend(row: Dividend) -> dict:
    fresh = partners_service.dividends(row.company).get(pk=row.pk)
    return s.DividendSerializer(fresh).data


class DividendSuggestView(OwnerMoneyMixin, OwnerAPIView):
    """What a round for the period could pay (its net profit less rounds already made for it,
    at most what is safe to take out today) and how it splits by the shares."""

    @extend_schema(
        parameters=[OpenApiParameter("from", str), OpenApiParameter("to", str)],
        responses=s.SuggestSerializer,
    )
    def get(self, request, company_id):
        start, end = _period(request, self.today)
        data = domain(lambda: partners_service.suggest(self.company, start, end))
        return Response(_jsonable(data))


class DividendMixin(OwnerMoneyMixin):
    def dividend(self, pk) -> Dividend:
        return get_object_or_404(Dividend.objects.for_company(self.company), pk=pk)


class DividendView(DividendMixin, OwnerAPIView):
    """One round; PATCH changes the amount or the note while nothing of it is paid."""

    @extend_schema(responses=s.DividendSerializer)
    def get(self, request, company_id, pk):
        return Response(_dividend(self.dividend(pk)))

    @extend_schema(request=s.DividendPatchSerializer, responses=s.DividendSerializer)
    def patch(self, request, company_id, pk):
        row = self.dividend(pk)
        serializer = s.DividendPatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = domain(
            lambda: partners_service.update_dividend(
                row, by=self.membership, amount=data.get("amount"), note=data.get("note")
            )
        )
        self.changed()
        return Response(_dividend(row))


class DividendPayView(DividendMixin, OwnerAPIView):
    """Pay the round's unpaid lines (or the listed ones) from a business account in the base
    currency: one owner draw per partner."""

    @extend_schema(request=s.DividendPayInputSerializer, responses=s.DividendSerializer)
    def post(self, request, company_id, pk):
        row = self.dividend(pk)
        serializer = s.DividendPayInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account = self.draw_account(data["account"])
        paid_on = self.day(data.get("paid_on"), "paid_on")
        row = domain(
            lambda: partners_service.pay_dividend(
                row,
                by=self.membership,
                account=account,
                paid_on=paid_on,
                line_ids=data.get("lines"),
            )
        )
        self.changed()
        return Response(_dividend(row))


class DividendCancelView(DividendMixin, OwnerAPIView):
    """Drop a round nothing of which is paid."""

    @extend_schema(request=s.ReasonInputSerializer, responses=s.DividendSerializer)
    def post(self, request, company_id, pk):
        row = self.dividend(pk)
        serializer = s.ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = domain(
            lambda: partners_service.cancel_dividend(
                row, by=self.membership, reason=serializer.validated_data["reason"]
            )
        )
        self.changed()
        return Response(_dividend(row))


class DividendUndoView(DividendMixin, OwnerAPIView):
    """Take one line's payment back: its owner draw is voided."""

    @extend_schema(request=s.ReasonInputSerializer, responses=s.DividendSerializer)
    def post(self, request, company_id, pk, line_id):
        row = self.dividend(pk)
        line = get_object_or_404(DividendLine.objects.filter(dividend=row), pk=line_id)
        serializer = s.ReasonInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = domain(
            lambda: partners_service.undo_payment(
                line, by=self.membership, reason=serializer.validated_data["reason"]
            )
        )
        self.changed()
        return Response(_dividend(row))
