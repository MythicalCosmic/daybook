"""Owner dashboard endpoints of fixed assets (`assets/…`).

    GET/PATCH  assets/settings/                      the asset policy (read / assets.manage)
    CRUD       assets/categories/                    (read / assets.manage)
    GET        assets/summary/?branch                what the company owns, worth and costs a month
    GET/POST   assets/items/?q&status&category&branch&custodian&disposed
    GET/PATCH/DELETE assets/items/{id}/              its page: values, schedule, tax book, timeline
    POST       assets/items/{id}/in-service|status|move|issue|return|service|verification|
               repair|addition|write-down|estimate|suspend|resume|usage|dispose|files/
    DELETE     assets/files/{id}/
    GET        assets/depreciation/?year&group&branch   by month and category or branch
    GET        assets/movement/?from&to&branch          the roll-forward
    GET        assets/planning/?branch                  replacements, repairs, idle, upkeep
    GET        assets/custody/?branch                   who holds what
    GET        assets/purchases/                        expenses to turn into assets
    GET/POST   assets/counts/  ·  GET assets/counts/{id}/  ·  POST …/{id}/lines/{line}/ · …/close/

Reading needs assets.manage or finance.view; writing assets.manage. Everything is company- and
branch-scoped (an asset outside the caller's branches answers 404) and answers 403 while the
module is off, except the settings.
"""

from datetime import date

from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.assets import conf, posting, queries, services
from apps.assets import serializers as s
from apps.assets.defaults import TAX_GROUPS
from apps.assets.models import (
    Asset,
    AssetCategory,
    AssetCount,
    AssetCountLine,
    AssetFile,
    DepreciationEntry,
)
from apps.assets.providers import MANAGE, READ
from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.members.models import Membership

BRANCH_PARAM = OpenApiParameter("branch", int, description="One branch (in scope).")


class ModuleOn:
    """403 while the assets module is switched off for the company."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.company.has_feature("assets"):
            raise PermissionDenied(_("Assets aren't switched on for this company."))


class Scope:
    def branches(self) -> list[int] | None:
        """The caller's branches, narrowed to `?branch=` when given (and allowed)."""
        asked = self.request.query_params.get("branch")
        allowed = self.branch_scope
        if not asked:
            return allowed
        try:
            branch = int(asked)
        except ValueError as exc:
            raise ValidationError({"branch": [_("Give a number.")]}) from exc
        if allowed is not None and branch not in allowed:
            raise NotFound
        return [branch]

    def asset(self, pk) -> Asset:
        found = (
            queries.scoped(self.company, branch_ids=self.branch_scope)
            .select_related("category", "branch", "custodian", "responsible", "company")
            .filter(pk=pk)
            .first()
        )
        if found is None:
            raise NotFound
        return found

    def branch(self, pk):
        if pk is None:
            return None
        found = self.company.branches.filter(pk=pk).first()
        scope = self.branch_scope
        if found is None or (scope is not None and found.pk not in scope):
            raise ValidationError({"branch": [_("Pick a branch you work with.")]})
        return found

    def person(self, pk, name: str = "person") -> Membership | None:
        if pk is None:
            return None
        found = Membership.objects.for_company(self.company).filter(pk=pk).first()
        if found is None:
            raise ValidationError({name: [_("Pick someone of this company.")]})
        return found


def _today(company) -> date:
    return posting.local_today(company)


def _rows(assets, view) -> list[dict]:
    today = _today(view.company)
    user = view.request.user
    return [s.row_of(asset, user=user, today=today, next_due=queries.next_due) for asset in assets]


# Settings and categories ---------------------------------------------------------------------


class SettingsView(OwnerAPIView):
    perm = READ
    perms_by_action = {"patch": MANAGE}

    def _data(self):
        row = conf.get_settings(self.company)
        return {
            "start_rule": row.start_rule,
            "number_prefix": row.number_prefix,
            "next_number": row.next_number,
            "capitalization_threshold": row.capitalization_threshold,
            "replacement_inflation": row.replacement_inflation,
            "tax_book": row.tax_book,
            "remind_days": row.remind_days,
            "tax_groups": [
                {"code": code, "rate": rate, "label": str(label)}
                for code, (rate, label) in TAX_GROUPS.items()
            ],
            "locked_rule": DepreciationEntry.objects.filter(
                company=self.company, opening=False
            ).exists(),
        }

    @extend_schema(responses=s.SettingsSerializer)
    def get(self, request, company_id):
        return Response(s.SettingsSerializer(self._data()).data)

    @extend_schema(request=s.SettingsSerializer, responses=s.SettingsSerializer)
    def patch(self, request, company_id):
        serializer = s.SettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_settings(self.company, by=self.membership, **serializer.validated_data)
        return Response(s.SettingsSerializer(self._data()).data)


class CategoryViewSet(ModuleOn, OwnerViewSet):
    queryset = AssetCategory.objects.none()  # for the schema: ids are integers
    perm = READ
    perms_by_action = {"create": MANAGE, "partial_update": MANAGE, "destroy": MANAGE}
    serializer_class = s.CategorySerializer

    def get_queryset(self):
        return AssetCategory.objects.for_company(self.company).annotate(assets=Count("assets"))

    def _out(self, category):
        data = {
            field: getattr(category, field)
            for field in (
                "id",
                "name",
                "kind",
                "life_months",
                "method",
                "salvage_percent",
                "tax_group",
                "tax_rate",
                "service_months",
                "verify_months",
                "icon",
                "order",
                "is_active",
                "system_code",
            )
        }
        data["assets"] = getattr(category, "assets", None)
        if data["assets"] is None:
            data["assets"] = category.assets.count()
        return s.CategorySerializer(data).data

    @extend_schema(responses=s.CategorySerializer(many=True))
    def list(self, request, company_id):
        return Response([self._out(category) for category in self.get_queryset()])

    @extend_schema(request=s.CategorySerializer, responses={201: s.CategorySerializer})
    def create(self, request, company_id):
        serializer = s.CategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = services.create_category(
            self.company, by=self.membership, **serializer.validated_data
        )
        return Response(self._out(category), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.CategorySerializer, responses=s.CategorySerializer)
    def partial_update(self, request, company_id, pk=None):
        category = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = s.CategorySerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        category = services.update_category(
            category, by=self.membership, **serializer.validated_data
        )
        return Response(self._out(category))

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk=None):
        category = get_object_or_404(self.get_queryset(), pk=pk)
        services.delete_category(category, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


# The register ---------------------------------------------------------------------------------


class SummaryView(ModuleOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(parameters=[BRANCH_PARAM], responses=s.SummarySerializer)
    def get(self, request, company_id):
        data = queries.summary(self.company, branch_ids=self.branches())
        return Response(s.SummarySerializer(data).data)


LIST_PARAMS = [
    OpenApiParameter("q", str),
    OpenApiParameter("status", str),
    OpenApiParameter("category", int),
    BRANCH_PARAM,
    OpenApiParameter("custodian", int),
    OpenApiParameter("disposed", bool, description="Include disposed assets."),
]
ACTION_PERMS = {
    name: MANAGE
    for name in (
        "create",
        "partial_update",
        "destroy",
        "in_service",
        "set_status",
        "move",
        "issue",
        "take_back",
        "service",
        "verification",
        "repair",
        "addition",
        "write_down",
        "estimate",
        "suspend",
        "resume",
        "usage",
        "dispose",
        "files",
    )
}


class AssetViewSet(ModuleOn, Scope, OwnerViewSet):
    queryset = Asset.objects.none()  # for the schema: ids are integers
    perm = READ
    perms_by_action = ACTION_PERMS
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    serializer_class = s.AssetRowSerializer

    def _int(self, name):
        value = self.request.query_params.get(name)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise ValidationError({name: [_("Give a number.")]}) from exc

    @extend_schema(parameters=LIST_PARAMS, responses=s.AssetRowSerializer(many=True))
    def list(self, request, company_id):
        params = request.query_params
        rows = queries.register(
            self.company,
            branch_ids=self.branches(),
            q=params.get("q", ""),
            status=params.get("status", ""),
            category=self._int("category"),
            custodian=self._int("custodian"),
            include_disposed=params.get("disposed") in ("1", "true"),
        ).prefetch_related(Prefetch("files", queryset=AssetFile.objects.order_by("-created_at")))
        return Response(s.AssetRowSerializer(_rows(rows[:1000], self), many=True).data)

    def _fields(self, data: dict) -> dict:
        """API ids → objects of this company (and of the caller's branches)."""
        from apps.finance.models import Counterparty, Transaction

        fields = dict(data)
        if "category" in fields:
            category = AssetCategory.objects.for_company(self.company).filter(pk=fields["category"])
            if not category.exists():
                raise ValidationError({"category": [_("Pick a category of this company.")]})
            fields["category"] = category.get()
        if "branch" in fields:
            fields["branch"] = self.branch(fields["branch"])
        for name in ("custodian", "responsible"):
            if name in fields:
                fields[name] = self.person(fields[name], name)
        if "supplier" in fields:
            pk = fields["supplier"]
            fields["supplier"] = (
                Counterparty.objects.for_company(self.company).filter(pk=pk).first() if pk else None
            )
            if pk and fields["supplier"] is None:
                raise ValidationError({"supplier": [_("Pick a supplier of this company.")]})
        if "purchase_transaction" in fields:
            pk = fields["purchase_transaction"]
            txn = (
                Transaction.objects.for_company(self.company).filter(pk=pk).first() if pk else None
            )
            scope = self.branch_scope
            if pk and (txn is None or (scope is not None and txn.branch_id not in scope)):
                raise ValidationError({"purchase_transaction": [_("That purchase isn't yours.")]})
            fields["purchase_transaction"] = txn
        return fields

    @extend_schema(request=s.AssetWriteSerializer, responses={201: s.AssetDetailSerializer})
    def create(self, request, company_id):
        serializer = s.AssetWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = self._fields(serializer.validated_data)
        category = fields.pop("category", None)
        name = fields.pop("name", "")
        if category is None:
            raise ValidationError({"category": [_("Pick a category.")]})
        if self.branch_scope is not None and fields.get("branch") is None:
            raise ValidationError({"branch": [_("Pick the branch it is at.")]})
        asset = services.create_asset(
            self.company, by=self.membership, category=category, name=name, **fields
        )
        return Response(self._detail(self.asset(asset.pk)), status=status.HTTP_201_CREATED)

    def _detail(self, asset: Asset) -> dict:
        page = queries.detail(asset)
        user = self.request.user
        row = queries.with_values(Asset.objects.filter(pk=asset.pk)).select_related(
            "category", "branch", "custodian"
        )
        row = row.prefetch_related("files").get()
        txn = asset.purchase_transaction
        values = page["values"]
        return s.AssetDetailSerializer(
            {
                "asset": s.row_of(
                    row, user=user, today=_today(asset.company), next_due=queries.next_due
                ),
                "serial": asset.serial,
                "notes": asset.notes,
                "purchased_on": asset.purchased_on,
                "price": asset.price,
                "price_currency": asset.price_currency,
                "price_rate": asset.price_rate,
                "life_months": asset.life_months,
                "method": asset.method,
                "declining_factor": asset.declining_factor,
                "total_units": asset.total_units,
                "unit": asset.unit,
                "opening_accumulated": asset.opening_accumulated,
                "books_depreciation": asset.books_depreciation,
                "booked": services._booked(asset),
                "supplier": s.ref(asset.supplier),
                "supplier_name": asset.supplier_name,
                "purchase": {
                    "id": txn.pk,
                    "occurred_on": txn.occurred_on,
                    "amount": -txn.amount,
                    "currency": txn.currency,
                    "description": txn.description,
                    "account": txn.account.name if txn.account_id else None,
                    "capitalized": txn.capitalized,
                }
                if txn is not None
                else None,
                "responsible": s.ref(asset.responsible),
                "warranty_until": asset.warranty_until,
                "insurance_until": asset.insurance_until,
                "service_months": asset.service_months,
                "next_service_on": asset.next_service_on,
                "verify_months": asset.verify_months,
                "next_verification_on": asset.next_verification_on,
                "disposed_on": asset.disposed_on,
                "disposal": asset.disposal,
                "disposal_amount": asset.disposal_amount,
                "disposal_reason": asset.disposal_reason,
                "qr_link": f"asset_{asset.qr_token}",
                "values": {**values.__dict__, "salvage_value": asset.salvage_value},
                "schedule": page["schedule"],
                "tax": page["tax"],
                "events": [s.event_of(event) for event in reversed(page["events"])],
                "assignments": [s.assignment_of(row) for row in page["assignments"]],
                "files": [s.file_of(row, user) for row in page["files"]],
            }
        ).data

    @extend_schema(responses=s.AssetDetailSerializer)
    def retrieve(self, request, company_id, pk=None):
        return Response(self._detail(self.asset(pk)))

    @extend_schema(request=s.AssetWriteSerializer, responses=s.AssetDetailSerializer)
    def partial_update(self, request, company_id, pk=None):
        asset = self.asset(pk)
        serializer = s.AssetWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = self._fields(serializer.validated_data)
        for name in ("custodian", "purchase_transaction", "status"):
            if name in fields:
                raise ValidationError({name: [_("Use its own action for this.")]})
        services.update_asset(asset, by=self.membership, **fields)
        return Response(self._detail(self.asset(pk)))

    @extend_schema(responses={204: None})
    def destroy(self, request, company_id, pk=None):
        services.delete_asset(self.asset(pk), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # One step each, every one answering with the asset's page.

    def _run(self, request, pk, serializer_class, call):
        asset = self.asset(pk)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        call(asset, dict(serializer.validated_data))
        return Response(self._detail(self.asset(pk)))

    @extend_schema(request=s.DaySerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"], url_path="in-service")
    def in_service(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.DaySerializer,
            lambda asset, data: services.put_into_service(asset, by=self.membership, on=data["on"]),
        )

    @extend_schema(request=s.StatusSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.StatusSerializer,
            lambda asset, data: services.set_status(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.MoveSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def move(self, request, company_id, pk=None):
        def call(asset, data):
            services.move(
                asset,
                by=self.membership,
                branch=self.branch(data["branch"]),
                on=data["on"],
                note=data.get("note", ""),
            )

        return self._run(request, pk, s.MoveSerializer, call)

    @extend_schema(request=s.IssueSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def issue(self, request, company_id, pk=None):
        def call(asset, data):
            services.issue(
                asset,
                by=self.membership,
                membership=self.person(data["person"]),
                on=data["on"],
                condition=data.get("condition", ""),
                note=data.get("note", ""),
            )

        return self._run(request, pk, s.IssueSerializer, call)

    @extend_schema(request=s.ReturnSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"], url_path="return")
    def take_back(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.ReturnSerializer,
            lambda asset, data: services.take_back(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.ServiceSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def service(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.ServiceSerializer,
            lambda asset, data: services.record_service(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.VerificationSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def verification(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.VerificationSerializer,
            lambda asset, data: services.record_verification(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.RepairSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def repair(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.RepairSerializer,
            lambda asset, data: services.record_repair(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.AdditionSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def addition(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.AdditionSerializer,
            lambda asset, data: services.add_to_cost(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.AmountSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"], url_path="write-down")
    def write_down(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.AmountSerializer,
            lambda asset, data: services.write_down(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.EstimateSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def estimate(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.EstimateSerializer,
            lambda asset, data: services.change_estimate(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.DaySerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def suspend(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.DaySerializer,
            lambda asset, data: services.suspend(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.DaySerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def resume(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.DaySerializer,
            lambda asset, data: services.resume(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.UsageSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def usage(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.UsageSerializer,
            lambda asset, data: services.record_usage(asset, by=self.membership, **data),
        )

    @extend_schema(request=s.DisposeSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def dispose(self, request, company_id, pk=None):
        from apps.finance.models import MoneyAccount

        def call(asset, data):
            account = None
            if data.get("account"):
                account = (
                    MoneyAccount.objects.for_company(self.company)
                    .filter(pk=data["account"])
                    .first()
                )
                if account is None:
                    raise ValidationError({"account": [_("Pick an account of this company.")]})
            services.dispose(
                asset,
                by=self.membership,
                on=data["on"],
                kind=data["kind"],
                amount=data.get("amount"),
                account=account,
                reason=data.get("reason", ""),
            )

        return self._run(request, pk, s.DisposeSerializer, call)

    @extend_schema(request=s.FileUploadSerializer, responses=s.AssetDetailSerializer)
    @action(detail=True, methods=["post"])
    def files(self, request, company_id, pk=None):
        return self._run(
            request,
            pk,
            s.FileUploadSerializer,
            lambda asset, data: services.add_file(asset, by=self.membership, **data),
        )


class FileView(ModuleOn, Scope, OwnerAPIView):
    perm = MANAGE

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, file_id):
        row = AssetFile.objects.for_company(self.company).filter(pk=file_id).first()
        if row is None:
            raise NotFound
        self.asset(row.asset_id)  # in the caller's branches
        services.remove_file(row, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


# Reports ---------------------------------------------------------------------------------------


class DepreciationView(ModuleOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(
        parameters=[
            OpenApiParameter("year", int),
            OpenApiParameter("group", str, enum=["category", "branch"]),
            BRANCH_PARAM,
        ],
        responses=s.DepreciationReportSerializer,
    )
    def get(self, request, company_id):
        try:
            year = int(request.query_params.get("year") or _today(self.company).year)
        except ValueError as exc:
            raise ValidationError({"year": [_("Give a year.")]}) from exc
        if not 2000 <= year <= 2100:
            raise ValidationError({"year": [_("Give a year.")]})
        group = request.query_params.get("group") or "category"
        if group not in ("category", "branch"):
            raise ValidationError({"group": [_("By category or by branch.")]})
        data = queries.depreciation_report(
            self.company, branch_ids=self.branches(), year=year, group=group
        )
        return Response(s.DepreciationReportSerializer(data).data)


class MovementView(ModuleOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, description="YYYY-MM-DD"),
            OpenApiParameter("to", str, description="YYYY-MM-DD"),
            BRANCH_PARAM,
        ],
        responses=s.MovementSerializer,
    )
    def get(self, request, company_id):
        today = _today(self.company)
        try:
            start = date.fromisoformat(request.query_params.get("from") or f"{today.year}-01-01")
            end = date.fromisoformat(request.query_params.get("to") or today.isoformat())
        except ValueError as exc:
            raise ValidationError({"range": [_("Give the days as YYYY-MM-DD.")]}) from exc
        if end < start or (end - start).days > 366 * 5:
            raise ValidationError({"range": [_("Pick a range of at most five years.")]})
        data = queries.movement(self.company, branch_ids=self.branches(), start=start, end=end)
        return Response(s.MovementSerializer(data).data)


def _plan_item(item: dict, view) -> dict:
    today = _today(view.company)
    out = {
        "asset": s.row_of(
            item["asset"], user=view.request.user, today=today, next_due=queries.next_due
        )
    }
    for key in ("end_month", "estimate", "repairs", "replacement", "share"):
        if key in item:
            out[key] = item[key]
    return out


class PlanningView(ModuleOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(parameters=[BRANCH_PARAM], responses=s.PlanningSerializer)
    def get(self, request, company_id):
        data = queries.planning(self.company, branch_ids=self.branches())
        today = _today(self.company)
        user = request.user
        row = lambda asset: s.row_of(asset, user=user, today=today, next_due=queries.next_due)  # noqa: E731
        return Response(
            s.PlanningSerializer(
                {
                    "replacements": [_plan_item(item, self) for item in data["replacements"]],
                    "quarters": data["quarters"],
                    "replacement_total": data["replacement_total"],
                    "repairs": [_plan_item(item, self) for item in data["repairs"]],
                    "idle": [row(asset) for asset in data["idle"]],
                    "idle_value": data["idle_value"],
                    "free": [row(asset) for asset in data["free"]],
                    "upkeep": [
                        {
                            "asset": row(item["asset"]),
                            "what": item["what"],
                            "day": item["day"],
                            "overdue": item["overdue"],
                        }
                        for item in data["upkeep"]
                    ],
                    "unconfirmed": [
                        {
                            "asset": s.ref(assignment.asset),
                            "person": s.ref(assignment.membership),
                            "issued_on": assignment.issued_on,
                        }
                        for assignment in data["unconfirmed"]
                    ],
                    "inflation": data["inflation"],
                }
            ).data
        )


class CustodyView(ModuleOn, Scope, OwnerAPIView):
    perm = READ

    @extend_schema(parameters=[BRANCH_PARAM], responses=s.CustodySerializer(many=True))
    def get(self, request, company_id):
        today = _today(self.company)
        user = request.user
        out = []
        for person in queries.custody(self.company, branch_ids=self.branches()):
            out.append(
                {
                    "person": s.ref(person["membership"]),
                    "value": person["value"],
                    "unconfirmed": person["unconfirmed"],
                    "assets": [
                        s.row_of(item["asset"], user=user, today=today, next_due=queries.next_due)
                        for item in person["assets"]
                    ],
                }
            )
        return Response(s.CustodySerializer(out, many=True).data)


class PurchasesView(ModuleOn, Scope, OwnerAPIView):
    perm = MANAGE

    @extend_schema(responses=s.PurchaseSerializer(many=True))
    def get(self, request, company_id):
        rows = queries.purchases(self.company, branch_ids=self.branch_scope)
        return Response(
            s.PurchaseSerializer(
                [
                    {
                        "id": txn.pk,
                        "occurred_on": txn.occurred_on,
                        "amount": -txn.amount,
                        "currency": txn.currency,
                        "base_amount": -txn.base_amount,
                        "category": txn.category.name if txn.category_id else None,
                        "counterparty": s.ref(txn.counterparty),
                        "branch": s.ref(txn.branch),
                        "account": txn.account.name if txn.account_id else None,
                        "description": txn.description,
                    }
                    for txn in rows
                ],
                many=True,
            ).data
        )


# Counts ------------------------------------------------------------------------------------------


def _count_out(count: AssetCount, *, lines: bool) -> dict:
    rows = list(count.lines.select_related("asset", "checked_by"))
    totals = {result: 0 for result in AssetCountLine.Result.values}
    for line in rows:
        totals[line.result] += 1
    data = {
        "id": count.pk,
        "branch": s.ref(count.branch),
        "status": count.status,
        "started_on": count.started_on,
        "closed_at": count.closed_at,
        "note": count.note,
        "totals": totals,
    }
    if lines:
        data["lines"] = [
            {
                "id": line.pk,
                "asset": s.ref(line.asset),
                "number": line.asset.number,
                "result": line.result,
                "note": line.note,
                "checked_by": s.ref(line.checked_by),
                "checked_at": line.checked_at,
            }
            for line in rows
        ]
    return data


class CountsView(ModuleOn, Scope, OwnerAPIView):
    perm = READ
    perms_by_action = {"post": MANAGE}

    def _counts(self):
        rows = AssetCount.objects.for_company(self.company).select_related("branch")
        scope = self.branch_scope
        if scope is not None:
            rows = rows.filter(branch_id__in=scope)
        return rows

    @extend_schema(responses=s.CountSerializer(many=True))
    def get(self, request, company_id):
        return Response(
            s.CountSerializer(
                [_count_out(count, lines=False) for count in self._counts()[:50]], many=True
            ).data
        )

    @extend_schema(request=s.CountStartSerializer, responses={201: s.CountSerializer})
    def post(self, request, company_id):
        serializer = s.CountStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        branch = self.branch(serializer.validated_data.get("branch"))
        if branch is None and self.branch_scope is not None:
            raise ValidationError({"branch": [_("Pick the branch to count.")]})
        count = services.start_count(
            self.company,
            by=self.membership,
            branch=branch,
            note=serializer.validated_data.get("note", ""),
        )
        return Response(
            s.CountSerializer(_count_out(count, lines=True)).data, status=status.HTTP_201_CREATED
        )


class CountView(CountsView):
    http_method_names = ["get"]

    def _one(self, count_id) -> AssetCount:
        found = self._counts().filter(pk=count_id).first()
        if found is None:
            raise NotFound
        return found

    @extend_schema(responses=s.CountSerializer)
    def get(self, request, company_id, count_id):
        return Response(s.CountSerializer(_count_out(self._one(count_id), lines=True)).data)


class CountCloseView(CountView):
    perm = MANAGE
    http_method_names = ["post"]

    @extend_schema(request=None, responses=s.CountSerializer)
    def post(self, request, company_id, count_id):
        count = self._one(count_id)
        services.close_count(count, by=self.membership)
        count.refresh_from_db()
        return Response(s.CountSerializer(_count_out(count, lines=True)).data)


class CountLineView(CountView):
    perm = MANAGE
    http_method_names = ["post"]

    @extend_schema(request=s.CountMarkSerializer, responses=s.CountSerializer)
    def post(self, request, company_id, count_id, line_id):
        count = self._one(count_id)
        line = count.lines.filter(pk=line_id).first()
        if line is None:
            raise NotFound
        serializer = s.CountMarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.mark(line, by=self.membership, **serializer.validated_data)
        return Response(s.CountSerializer(_count_out(count, lines=True)).data)
