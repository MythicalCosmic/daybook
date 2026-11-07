"""Owner dashboard endpoints of stock (`stock/…`, docs/PLAN-OWNER.md §14.6.4).

    GET/PATCH   stock/settings/                              read / stock.manage
    GET         stock/summary/?branch
    GET/POST    stock/products/?q&category&rx&control&storage&kind&mandatory&active&page
    GET/PATCH   stock/products/{id}/   · GET {id}/batches/ · {id}/movements/ · {id}/analogs/
    GET/POST    stock/products/{id}/codes/  · POST {id}/merge/ · POST stock/products/import/
    CRUD        stock/categories/ · stock/manufacturers/ · stock/suppliers/
    GET         stock/levels/?branch&q&low&negative&rx&control&storage&mandatory&category
    PATCH       stock/levels/{id}/                           min and max
    GET         stock/batches/?branch&product&expires_before&status&q
    POST        stock/batches/{id}/quarantine|release|markdown/ · stock/batches/opening/
    GET         stock/expiry/?branch&within=90 · stock/movements/?from&to&branch&kind&product
    CRUD        stock/receipts/ + {id}/lines/ + {id}/file/ + POST {id}/submit|post|void/
    CRUD        stock/transfers/ + POST {id}/send|receive|resolve|void/
    CRUD        stock/write-offs/ + {id}/files/ + POST {id}/approve|destroyed|void/ + {id}/act/
    CRUD        stock/counts/ + {id}/lines/ + {id}/found/ + POST {id}/submit|apply/
    CRUD        stock/recalls/ + POST {id}/close/
    CRUD        stock/pricing-rules/ · stock/defektura/
    GET         stock/journals/rx/?branch&month (+ pdf/) · journals/controlled/?branch&month
                (+ pdf/) · POST journals/controlled/close/ · journals/controlled/{id}/reported/

Reading needs sales.view, stock.manage or stock.operate; receipt drafts, counting and receiving
a transfer stock.operate or stock.manage; posting, approving, prices, the catalogue and the
settings stock.manage; the journals stock.controlled. Cost fields need finance.view. Everything
is company- and branch-scoped (a record outside the caller's branches answers 404) and answers
403 while the stock module is off, except the settings.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.companies.models import Branch
from apps.console.base import OwnerAPIView
from apps.console.perms import AnyOf, holds
from apps.core import uploads
from apps.finance.models import Counterparty
from apps.inventory import conf, engine, importing, journals, queries, register, services, shapes
from apps.inventory import serializers as s
from apps.inventory.models import (
    BatchStock,
    ControlledPeriod,
    GoodsReceipt,
    GoodsReceiptLine,
    Manufacturer,
    MissingRequest,
    PricingRule,
    Product,
    ProductCategory,
    ProductCode,
    RecallNotice,
    RxRecord,
    StockBatch,
    StockCount,
    StockLevel,
    StockTransfer,
    SupplierProfile,
    WriteOff,
)
from apps.members.permissions import Perm

READ = AnyOf(Perm.SALES_VIEW, Perm.STOCK_MANAGE, Perm.STOCK_OPERATE)
OPERATE = AnyOf(Perm.STOCK_OPERATE, Perm.STOCK_MANAGE)
MANAGE = Perm.STOCK_MANAGE
CONTROLLED = Perm.STOCK_CONTROLLED
FILE_LINK = inline_serializer(
    "InventoryFileLink",
    {
        "url": serializers.CharField(),
        "name": serializers.CharField(),
        "expires_in": serializers.IntegerField(),
    },
)
BRANCH_PARAM = OpenApiParameter("branch", int, description="One branch (in scope).")
DOCUMENT_KINDS = ("pdf", "xlsx", "csv", "image")


def _flag(value) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


def _int(value, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: [_("Give a number.")]}) from exc


def _date(value, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValidationError({name: [_("Give a date as YYYY-MM-DD.")]}) from exc


def _month(value) -> date:
    text = str(value or "")
    try:
        if len(text) == 7:
            return date.fromisoformat(f"{text}-01")
        return date.fromisoformat(text[:10]).replace(day=1)
    except ValueError as exc:
        raise ValidationError({"month": [_("Give a month as YYYY-MM.")]}) from exc


class StockView(OwnerAPIView):
    """The base of the stock endpoints: the module switch, the branch scope and the cost rule."""

    module_required = True
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.module_required and not self.company.has_feature("stock"):
            raise PermissionDenied(_("Stock isn't switched on for this company."))

    @property
    def cost(self) -> bool:
        return self.membership.has_perm(Perm.FINANCE_VIEW)

    @property
    def stock_settings(self):
        if not hasattr(self, "_stock_settings"):
            self._stock_settings = conf.get_settings(self.company)
        return self._stock_settings

    def today(self) -> date:
        return engine.local_today(self.company)

    def branches(self) -> list[int] | None:
        """The caller's branches, narrowed to `?branch=` when given (and allowed)."""
        asked = self.request.query_params.get("branch")
        allowed = self.branch_scope
        if not asked:
            return allowed
        branch = _int(asked, "branch")
        if allowed is not None and branch not in allowed:
            raise NotFound
        if not self.company.branches.filter(pk=branch).exists():
            raise NotFound
        return [branch]

    def branch(self, pk, name: str = "branch") -> Branch:
        found = self.company.branches.filter(pk=pk).first() if pk is not None else None
        scope = self.branch_scope
        if found is None or (scope is not None and found.pk not in scope):
            raise ValidationError({name: [_("Pick a branch you work with.")]})
        return found

    def scoped_branch(self, pk) -> Branch:
        found = self.company.branches.filter(pk=pk).first()
        scope = self.branch_scope
        if found is None or (scope is not None and found.pk not in scope):
            raise NotFound
        return found

    def product(self, pk, name: str = "product") -> Product:
        found = Product.objects.for_company(self.company).filter(pk=pk).first()
        if found is None:
            raise ValidationError({name: [_("Pick an item of the catalogue.")]})
        return found

    def get_product(self, pk) -> Product:
        found = (
            Product.objects.for_company(self.company)
            .select_related("manufacturer", "category")
            .filter(pk=pk)
            .first()
        )
        if found is None:
            raise NotFound
        return found

    def supplier(self, pk, name: str = "supplier") -> Counterparty:
        found = Counterparty.objects.for_company(self.company).filter(pk=pk).first()
        if found is None:
            raise ValidationError({name: [_("Pick a distributor.")]})
        return found

    def in_scope(self, *branch_ids) -> bool:
        scope = self.branch_scope
        return scope is None or any(branch_id in scope for branch_id in branch_ids)


# Settings and summary ------------------------------------------------------------------------


class SettingsView(StockView):
    perm = READ
    perms_by_action = {"patch": MANAGE}
    module_required = False

    def _data(self):
        row = conf.get_settings(self.company)
        data = {field: getattr(row, field) for field in services.SETTINGS_FIELDS}
        keep = dict(row.rx_keep_months or {})
        data["rx_keep_months"] = {kind: row.keep_months(kind) for kind in RxRecord.RxKind.values}
        data["rx_keep_months"].update(
            {k: v for k, v in keep.items() if k in RxRecord.RxKind.values}
        )
        return data

    @extend_schema(responses=s.SettingsSerializer)
    def get(self, request, company_id):
        return Response(s.SettingsSerializer(self._data()).data)

    @extend_schema(request=s.SettingsSerializer, responses=s.SettingsSerializer)
    def patch(self, request, company_id):
        serializer = s.SettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_settings(self.company, by=self.membership, **serializer.validated_data)
        return Response(s.SettingsSerializer(self._data()).data)


class SummaryView(StockView):
    perm = READ

    @extend_schema(parameters=[BRANCH_PARAM], responses=s.SummarySerializer)
    def get(self, request, company_id):
        scope = self.branches()
        company = self.company
        today = self.today()
        expiring = queries.expiring_value(company, branch_ids=scope, within_days=30, as_of=today)
        value = queries.stock_value(company, branch_ids=scope)
        level_rows = queries.levels(company, branch_ids=scope)
        transfers = queries.transfers(company, branch_ids=scope)
        licensed = self.company.branches.filter(controlled_licence=True, is_active=True)
        if scope is not None:
            licensed = licensed.filter(pk__in=scope)
        data = {
            "products": Product.objects.for_company(company).filter(is_active=True).count(),
            "low": queries.low_count(company, branch_ids=scope),
            "negative": level_rows.filter(quantity__lt=0).count(),
            "expiring_30d": expiring["count"],
            "expiring_30d_retail": expiring["retail_value"],
            "expiring_30d_value": expiring["value"],
            "expired": expiring["expired_count"],
            "expired_value": expiring["expired_value"],
            "stock_value": value["value"],
            "stock_retail_value": value["retail_value"],
            "receipts_to_post": queries.to_post(company, branch_ids=scope).count(),
            "drafts": queries.receipts(company, branch_ids=scope)
            .filter(status=GoodsReceipt.Status.DRAFT)
            .count(),
            "writeoffs_to_approve": queries.writeoffs(company, branch_ids=scope)
            .filter(status=WriteOff.Status.PROPOSED)
            .count(),
            "transfers_disputed": transfers.filter(status=StockTransfer.Status.DISPUTED).count(),
            "transfers_incoming": transfers.filter(status=StockTransfer.Status.SENT).count(),
            "recalls_open": queries.recalls_open(company).count(),
            "mandatory_missing": len(
                queries.mandatory_missing(company, branch_ids=scope, day=today)
            ),
            "controlled_branches": licensed.count(),
            "estimate": not _has_sales_lines(company),
        }
        if not self.cost:
            for key in ("expiring_30d_value", "expired_value", "stock_value"):
                data.pop(key)
        return Response(s.SummarySerializer(data).data)


class StockBranchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()
    kind = serializers.CharField()
    controlled_licence = serializers.BooleanField()
    social_pharmacy = serializers.BooleanField()
    in_scope = serializers.BooleanField(help_text="One of the caller's branches.")

    class Meta:
        ref_name = "InventoryStockBranch"


class BranchesView(StockView):
    """Every active branch of the company, for picking where a transfer goes (a pharmacy's head
    sends to the others without seeing their stock)."""

    perm = READ

    @extend_schema(responses=StockBranchSerializer(many=True))
    def get(self, request, company_id):
        scope = self.branch_scope
        rows = self.company.branches.filter(is_active=True).order_by("order", "pk")
        return Response(
            StockBranchSerializer(
                [
                    {
                        "id": row.pk,
                        "name": row.name,
                        "code": row.code,
                        "kind": row.kind,
                        "controlled_licence": row.controlled_licence,
                        "social_pharmacy": row.social_pharmacy,
                        "in_scope": scope is None or row.pk in scope,
                    }
                    for row in rows
                ],
                many=True,
            ).data
        )


def _has_sales_lines(company) -> bool:
    from apps.inventory.models import StockMovement

    return StockMovement.objects.filter(
        company=company, kind=StockMovement.Kind.SALE, document_type__startswith="sales."
    ).exists()


# The catalogue --------------------------------------------------------------------------------

PRODUCT_PARAMS = [
    OpenApiParameter("q", str),
    OpenApiParameter("category", int),
    OpenApiParameter("rx", bool),
    OpenApiParameter("control", bool, description="Any controlled class."),
    OpenApiParameter("storage", str),
    OpenApiParameter("kind", str),
    OpenApiParameter("mandatory", bool),
    OpenApiParameter("active", bool, description="Default true."),
    OpenApiParameter("page", int),
    OpenApiParameter("page_size", int),
]


def _product_fields(view: StockView, data: dict) -> dict:
    fields = {key: value for key, value in data.items() if key in s.PRODUCT_WRITE}
    if "manufacturer" in data:
        fields["manufacturer"] = (
            Manufacturer.objects.for_company(view.company).filter(pk=data["manufacturer"]).first()
            if data["manufacturer"]
            else None
        )
        if data["manufacturer"] and fields["manufacturer"] is None:
            raise ValidationError({"manufacturer": [_("Pick a manufacturer.")]})
    if "category" in data:
        fields["category"] = (
            ProductCategory.objects.for_company(view.company).filter(pk=data["category"]).first()
            if data["category"]
            else None
        )
        if data["category"] and fields["category"] is None:
            raise ValidationError({"category": [_("Pick a category.")]})
    return fields


class ProductsView(StockView):
    perm = READ
    perms_by_action = {"post": MANAGE}

    @extend_schema(
        operation_id="companies_stock_products_list",
        parameters=PRODUCT_PARAMS,
        responses=s.ProductPageSerializer,
    )
    def get(self, request, company_id):
        params = request.query_params
        rows = Product.objects.for_company(self.company).select_related("manufacturer", "category")
        if q := (params.get("q") or "").strip():
            rows = queries._search(self.company, q)
            rows = rows.select_related("manufacturer", "category")
        if params.get("active", "true").lower() != "all":
            rows = rows.filter(is_active=_flag(params.get("active", "true")))
        if params.get("category"):
            category = _int(params["category"], "category")
            rows = rows.filter(Q(category_id=category) | Q(category__parent_id=category))
        if params.get("rx") is not None and params.get("rx") != "":
            rows = rows.filter(rx_required=_flag(params["rx"]))
        if _flag(params.get("control", "")):
            rows = rows.exclude(control_class=Product.ControlClass.NONE)
        if params.get("storage"):
            rows = rows.filter(storage=params["storage"])
        if params.get("kind"):
            rows = rows.filter(kind=params["kind"])
        if _flag(params.get("mandatory", "")):
            rows = rows.filter(mandatory_list=True)
        rows = rows.order_by("name", "pk")
        size = min(max(_int(params.get("page_size", 50), "page_size"), 1), 200)
        page = max(_int(params.get("page", 1), "page"), 1)
        total = rows.count()
        found = list(rows[(page - 1) * size : page * size])
        ids = [row.pk for row in found]
        held = queries.quantities(self.company, ids, branch_ids=self.branch_scope)
        nearest = queries.nearest_expiry(self.company, ids, branch_ids=self.branch_scope)
        results = [
            shapes.product_out(
                row,
                cost=self.cost,
                settings=self.stock_settings,
                quantity=held.get(row.pk, Decimal(0)),
                nearest=nearest.get(row.pk),
            )
            for row in found
        ]
        return Response(s.ProductPageSerializer({"count": total, "results": results}).data)

    @extend_schema(request=s.ProductWriteSerializer, responses={201: s.ProductSerializer})
    def post(self, request, company_id):
        serializer = s.ProductWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = services.create_product(
            self.company, by=self.membership, **_product_fields(self, serializer.validated_data)
        )
        product = self.get_product(product.pk)
        return Response(
            s.ProductSerializer(
                shapes.product_out(
                    product, cost=self.cost, settings=self.stock_settings, quantity=0
                )
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ProductView(StockView):
    perm = READ
    perms_by_action = {"patch": MANAGE}

    def _page(self, product):
        scope = self.branch_scope
        held = queries.quantities(self.company, [product.pk], branch_ids=scope)
        nearest = queries.nearest_expiry(self.company, [product.pk], branch_ids=scope)
        codes = [
            {
                "id": code.pk,
                "kind": code.kind,
                "code": code.code,
                "supplier": shapes.ref(code.supplier),
            }
            for code in product.codes.select_related("supplier")
        ]
        return {
            "product": shapes.product_out(
                product,
                cost=self.cost,
                settings=self.stock_settings,
                quantity=held.get(product.pk, Decimal(0)),
                nearest=nearest.get(product.pk),
            ),
            "branches": queries.by_branch(self.company, product, branch_ids=scope),
            "codes": codes,
            "analogs": queries.analogs(product, branch_ids=scope),
            "price_cap": queries.price_cap(product, unit_cost=product.cost_price),
        }

    @extend_schema(responses=s.ProductPageDetailSerializer)
    def get(self, request, company_id, pk):
        return Response(s.ProductPageDetailSerializer(self._page(self.get_product(pk))).data)

    @extend_schema(request=s.ProductWriteSerializer, responses=s.ProductPageDetailSerializer)
    def patch(self, request, company_id, pk):
        product = self.get_product(pk)
        serializer = s.ProductWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_product(
            product, by=self.membership, **_product_fields(self, serializer.validated_data)
        )
        return Response(s.ProductPageDetailSerializer(self._page(self.get_product(pk))).data)


class ProductAnalogsView(StockView):
    perm = READ

    @extend_schema(responses=s.AnalogSerializer(many=True))
    def get(self, request, company_id, pk):
        product = self.get_product(pk)
        rows = queries.analogs(product, branch_ids=self.branch_scope)
        return Response(s.AnalogSerializer(rows, many=True).data)


class ProductBatchesView(StockView):
    perm = READ

    @extend_schema(parameters=[BRANCH_PARAM], responses=s.BatchSerializer(many=True))
    def get(self, request, company_id, pk):
        product = self.get_product(pk)
        today = self.today()
        rows = queries.stock_rows(self.company, branch_ids=self.branches(), product_id=product.pk)
        return Response(
            s.BatchSerializer(
                [
                    shapes.batch_out(row, cost=self.cost, today=today, settings=self.stock_settings)
                    for row in rows.select_related("batch__receipt_line")
                ],
                many=True,
            ).data
        )


class ProductMovementsView(StockView):
    perm = READ

    @extend_schema(parameters=[BRANCH_PARAM], responses=s.MovementSerializer(many=True))
    def get(self, request, company_id, pk):
        product = self.get_product(pk)
        today = self.today()
        rows = queries.movements(
            self.company, today - timedelta(days=365), today, branch_ids=self.branches()
        ).filter(product=product)[:200]
        return Response(
            s.MovementSerializer(
                [shapes.movement_out(row, cost=self.cost) for row in rows], many=True
            ).data
        )


class ProductCodesView(StockView):
    perm = READ
    perms_by_action = {"post": MANAGE}

    @extend_schema(responses=s.CodeSerializer(many=True))
    def get(self, request, company_id, pk):
        product = self.get_product(pk)
        return Response(
            s.CodeSerializer(
                [
                    {
                        "id": code.pk,
                        "kind": code.kind,
                        "code": code.code,
                        "supplier": shapes.ref(code.supplier),
                    }
                    for code in product.codes.select_related("supplier")
                ],
                many=True,
            ).data
        )

    @extend_schema(request=s.CodeSerializer, responses=s.CodeSerializer(many=True))
    def post(self, request, company_id, pk):
        product = self.get_product(pk)
        serializer = s.CodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        supplier = (
            self.supplier(data["supplier_id"], "supplier_id") if data.get("supplier_id") else None
        )
        services.remember_code(
            product, by=self.membership, kind=data["kind"], code=data["code"], supplier=supplier
        )
        return self.get(request, company_id, pk)


class ProductCodeView(StockView):
    perm = MANAGE

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, pk, code_id):
        product = self.get_product(pk)
        code = ProductCode.objects.filter(product=product, pk=code_id).first()
        if code is None:
            raise NotFound
        code.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductMergeView(StockView):
    perm = MANAGE

    @extend_schema(request=s.MergeSerializer, responses=s.ProductSerializer)
    def post(self, request, company_id, pk):
        keep = self.get_product(pk)
        serializer = s.MergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        other = self.product(serializer.validated_data["other"], "other")
        keep = services.merge_products(keep, other, by=self.membership)
        return Response(
            s.ProductSerializer(
                shapes.product_out(
                    self.get_product(keep.pk), cost=self.cost, settings=self.stock_settings
                )
            ).data
        )


class ProductImportView(StockView):
    perm = MANAGE

    @extend_schema(request=s.ImportSerializer, responses=s.ImportResultSerializer)
    def post(self, request, company_id):
        serializer = s.ImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        upload = uploads.accept_document(data["file"], allowed=("xlsx", "csv"))
        mapping = data.get("mapping") or None
        if mapping is not None and not isinstance(mapping, dict):
            raise ValidationError({"mapping": [_("Give the columns as a map.")]})
        result = importing.import_products(
            self.company, upload, by=self.membership, mapping=mapping, dry_run=data["dry_run"]
        )
        return Response(s.ImportResultSerializer(result).data)


class CategoriesView(StockView):
    perm = READ
    perms_by_action = {"post": MANAGE}

    def rows(self):
        return [
            {
                "id": row.pk,
                "name": row.name,
                "parent": row.parent_id,
                "order": row.order,
                "products": row.product_count,
            }
            for row in ProductCategory.objects.for_company(self.company).annotate(
                product_count=Count("products")
            )
        ]

    @extend_schema(responses=s.CategorySerializer(many=True))
    def get(self, request, company_id):
        return Response(s.CategorySerializer(self.rows(), many=True).data)

    @extend_schema(request=s.CategorySerializer, responses={201: s.CategorySerializer(many=True)})
    def post(self, request, company_id):
        serializer = s.CategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "parent" in data:
            data["parent"] = self._category(data["parent"])
        services.save_category(self.company, by=self.membership, **data)
        return Response(s.CategorySerializer(self.rows(), many=True).data, status=201)

    def _category(self, pk):
        if pk is None:
            return None
        found = ProductCategory.objects.for_company(self.company).filter(pk=pk).first()
        if found is None:
            raise ValidationError({"parent": [_("Pick a category.")]})
        return found


class CategoryView(CategoriesView):
    perm = MANAGE
    perms_by_action = {}
    http_method_names = ["patch", "delete", "options"]

    def _get(self, pk):
        found = ProductCategory.objects.for_company(self.company).filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    @extend_schema(request=s.CategorySerializer, responses=s.CategorySerializer(many=True))
    def patch(self, request, company_id, pk):
        category = self._get(pk)
        serializer = s.CategorySerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "parent" in data:
            data["parent"] = self._category(data["parent"])
        services.save_category(self.company, by=self.membership, category=category, **data)
        return Response(s.CategorySerializer(self.rows(), many=True).data)

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, pk):
        services.delete_category(self._get(pk), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManufacturersView(StockView):
    perm = READ
    perms_by_action = {"post": MANAGE}

    @extend_schema(responses=s.ManufacturerSerializer(many=True))
    def get(self, request, company_id):
        rows = Manufacturer.objects.for_company(self.company).order_by("name")
        return Response(
            s.ManufacturerSerializer(
                [{"id": row.pk, "name": row.name, "country": row.country} for row in rows],
                many=True,
            ).data
        )

    @extend_schema(request=s.ManufacturerSerializer, responses={201: s.ManufacturerSerializer})
    def post(self, request, company_id):
        serializer = s.ManufacturerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.save_manufacturer(
            self.company, by=self.membership, **serializer.validated_data
        )
        return Response(
            s.ManufacturerSerializer({"id": row.pk, "name": row.name, "country": row.country}).data,
            status=201,
        )


class ManufacturerView(StockView):
    perm = MANAGE

    @extend_schema(request=s.ManufacturerSerializer, responses=s.ManufacturerSerializer)
    def patch(self, request, company_id, pk):
        row = Manufacturer.objects.for_company(self.company).filter(pk=pk).first()
        if row is None:
            raise NotFound
        serializer = s.ManufacturerSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = services.save_manufacturer(
            self.company, by=self.membership, manufacturer=row, **serializer.validated_data
        )
        return Response(
            s.ManufacturerSerializer({"id": row.pk, "name": row.name, "country": row.country}).data
        )


def _supplier_out(party: Counterparty, profile: SupplierProfile | None, receipts: int) -> dict:
    return {
        "id": party.pk,
        "name": party.name,
        "phone": party.phone,
        "tin": party.tin,
        "payment_terms_days": profile.payment_terms_days if profile else None,
        "official_dealer": profile.official_dealer if profile else False,
        "delivery_days": profile.delivery_days if profile else 1,
        "min_order": profile.min_order if profile else None,
        "order_channel": profile.order_channel if profile else SupplierProfile.Channel.PHONE,
        "telegram_username": profile.telegram_username if profile else "",
        "notes": profile.notes if profile else "",
        "receipts": receipts,
    }


class SuppliersView(StockView):
    perm = READ
    perms_by_action = {"post": MANAGE}

    def rows(self):
        parties = (
            Counterparty.objects.for_company(self.company)
            .filter(
                Q(kind__in=(Counterparty.Kind.SUPPLIER, Counterparty.Kind.BOTH))
                | Q(supplier_profile__isnull=False)
            )
            .filter(is_active=True)
            .annotate(receipt_count=Count("goods_receipts"))
            .order_by("name")
        )
        profiles = {
            row.counterparty_id: row for row in SupplierProfile.objects.for_company(self.company)
        }
        return [
            _supplier_out(party, profiles.get(party.pk), party.receipt_count) for party in parties
        ]

    @extend_schema(responses=s.SupplierSerializer(many=True))
    def get(self, request, company_id):
        return Response(s.SupplierSerializer(self.rows(), many=True).data)

    @extend_schema(request=s.SupplierSerializer, responses={201: s.SupplierSerializer})
    def post(self, request, company_id):
        from apps.finance import services as finance

        serializer = s.SupplierSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        name = data.pop("name")
        party = finance.create_counterparty(
            self.company, by=self.membership, name=name, kind=Counterparty.Kind.SUPPLIER
        )
        profile = services.save_supplier(party, by=self.membership, **data)
        return Response(s.SupplierSerializer(_supplier_out(party, profile, 0)).data, status=201)


class SupplierView(StockView):
    perm = MANAGE

    @extend_schema(request=s.SupplierSerializer, responses=s.SupplierSerializer)
    def patch(self, request, company_id, pk):
        party = Counterparty.objects.for_company(self.company).filter(pk=pk).first()
        if party is None:
            raise NotFound
        serializer = s.SupplierSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("name", None)
        profile = services.save_supplier(party, by=self.membership, **data)
        return Response(
            s.SupplierSerializer(
                _supplier_out(party, profile, GoodsReceipt.objects.filter(supplier=party).count())
            ).data
        )


# Stock ----------------------------------------------------------------------------------------

LEVEL_PARAMS = [
    BRANCH_PARAM,
    OpenApiParameter("q", str),
    OpenApiParameter("low", bool),
    OpenApiParameter("negative", bool),
    OpenApiParameter("rx", bool),
    OpenApiParameter("control", bool),
    OpenApiParameter("storage", str),
    OpenApiParameter("mandatory", bool),
    OpenApiParameter("category", int),
]


class LevelsView(StockView):
    perm = READ

    @extend_schema(parameters=LEVEL_PARAMS, responses=s.LevelSerializer(many=True))
    def get(self, request, company_id):
        params = request.query_params
        scope = self.branches()
        rows = queries.levels(self.company, branch_ids=scope, low=_flag(params.get("low", "")))
        if q := (params.get("q") or "").strip():
            rows = rows.filter(product__in=queries._search(self.company, q))
        if _flag(params.get("negative", "")):
            rows = rows.filter(quantity__lt=0)
        if params.get("rx") not in (None, ""):
            rows = rows.filter(product__rx_required=_flag(params["rx"]))
        if _flag(params.get("control", "")):
            rows = rows.exclude(product__control_class=Product.ControlClass.NONE)
        if params.get("storage"):
            rows = rows.filter(product__storage=params["storage"])
        if _flag(params.get("mandatory", "")):
            rows = rows.filter(product__mandatory_list=True)
        if params.get("category"):
            category = _int(params["category"], "category")
            rows = rows.filter(
                Q(product__category_id=category) | Q(product__category__parent_id=category)
            )
        rows = list(rows.exclude(quantity=0, shortfall=0, min_qty__isnull=True)[:500])
        today = self.today()
        sellable = queries.sellable_quantities(self.company, branch_ids=scope, day=today)
        stocks: dict[tuple[int, int], list] = {}
        for stock in queries.stock_rows(self.company, branch_ids=scope).filter(
            batch__product_id__in=[row.product_id for row in rows]
        ):
            stocks.setdefault((stock.branch_id, stock.batch.product_id), []).append(stock)
        data = []
        for row in rows:
            held = stocks.get((row.branch_id, row.product_id), [])
            data.append(
                shapes.level_out(
                    row,
                    cost=self.cost,
                    sellable=sellable.get((row.branch_id, row.product_id), Decimal(0)),
                    nearest=min((stock.batch.expires_on for stock in held), default=None),
                    value=sum(
                        (engine.value_of(stock.batch, stock.quantity) for stock in held),
                        Decimal(0),
                    ),
                )
            )
        return Response(s.LevelSerializer(data, many=True).data)


class LevelView(StockView):
    perm = MANAGE

    @extend_schema(request=s.LevelLimitsSerializer, responses=s.LevelLimitsSerializer)
    def patch(self, request, company_id, pk):
        level = (
            StockLevel.objects.filter(product__company=self.company, pk=pk)
            .select_related("branch", "product")
            .first()
        )
        if level is None or not self.in_scope(level.branch_id):
            raise NotFound
        serializer = s.LevelLimitsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        level = services.set_level_limits(
            level.branch, level.product, by=self.membership, **serializer.validated_data
        )
        return Response(
            s.LevelLimitsSerializer({"min_qty": level.min_qty, "max_qty": level.max_qty}).data
        )


BATCH_PARAMS = [
    BRANCH_PARAM,
    OpenApiParameter("product", int),
    OpenApiParameter("expires_before", str, description="YYYY-MM-DD"),
    OpenApiParameter("status", str, description="sellable, quarantine, recalled or expired"),
    OpenApiParameter("q", str, description="Series or product."),
]


class BatchesView(StockView):
    perm = READ

    @extend_schema(parameters=BATCH_PARAMS, responses=s.BatchSerializer(many=True))
    def get(self, request, company_id):
        params = request.query_params
        today = self.today()
        rows = queries.stock_rows(self.company, branch_ids=self.branches()).select_related(
            "batch__receipt_line"
        )
        if params.get("product"):
            rows = rows.filter(batch__product_id=_int(params["product"], "product"))
        if before := _date(params.get("expires_before"), "expires_before"):
            rows = rows.filter(batch__expires_on__lte=before)
        state = params.get("status")
        if state == "expired":
            rows = rows.filter(batch__expires_on__lt=today)
        elif state == StockBatch.Status.SELLABLE:
            rows = rows.filter(batch__status=state, batch__expires_on__gte=today)
        elif state:
            rows = rows.filter(batch__status=state)
        if q := (params.get("q") or "").strip():
            rows = rows.filter(
                Q(batch__series__icontains=q)
                | Q(batch__product__in=queries._search(self.company, q))
            )
        return Response(
            s.BatchSerializer(
                [
                    shapes.batch_out(row, cost=self.cost, today=today, settings=self.stock_settings)
                    for row in rows[:500]
                ],
                many=True,
            ).data
        )


class BatchActionView(StockView):
    """POST stock/batches/{id}/quarantine|release|markdown/ ({id}: the batch's stock row)."""

    perm = MANAGE
    action_name = ""

    def _stock(self, pk) -> BatchStock:
        stock = (
            BatchStock.objects.filter(batch__company=self.company, pk=pk)
            .select_related("branch", "batch__product__company", "batch__supplier")
            .first()
        )
        if stock is None or not self.in_scope(stock.branch_id):
            raise NotFound
        return stock

    def _answer(self, stock):
        stock = self._stock(stock.pk)
        return Response(
            s.BatchSerializer(
                shapes.batch_out(
                    stock, cost=self.cost, today=self.today(), settings=self.stock_settings
                )
            ).data
        )


class QuarantineView(BatchActionView):
    @extend_schema(request=s.ReasonSerializer, responses=s.BatchSerializer)
    def post(self, request, company_id, pk):
        stock = self._stock(pk)
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.quarantine(
            stock.batch, by=self.membership, reason=serializer.validated_data["reason"]
        )
        return self._answer(stock)


class ReleaseView(BatchActionView):
    @extend_schema(request=s.OptionalReasonSerializer, responses=s.BatchSerializer)
    def post(self, request, company_id, pk):
        stock = self._stock(pk)
        serializer = s.OptionalReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.release(
            stock.batch, by=self.membership, reason=serializer.validated_data.get("reason", "")
        )
        return self._answer(stock)


class MarkdownView(BatchActionView):
    @extend_schema(request=s.PriceSerializer, responses=s.BatchSerializer)
    def post(self, request, company_id, pk):
        stock = self._stock(pk)
        serializer = s.PriceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_markdown(
            stock.batch, by=self.membership, price=serializer.validated_data["price"]
        )
        return self._answer(stock)


class OpeningView(StockView):
    perm = MANAGE

    @extend_schema(request=s.OpeningSerializer, responses={201: s.BatchSerializer})
    def post(self, request, company_id):
        serializer = s.OpeningSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        branch = self.branch(data["branch"])
        product = self.product(data["product"])
        quantity = data["packs"] * product.units_per_pack + data.get("parts", 0)
        batch = services.add_opening_stock(
            branch,
            by=self.membership,
            product=product,
            series=data["series"],
            expires_on=data["expires_on"],
            made_on=data.get("made_on"),
            quantity=quantity,
            unit_cost=data["unit_cost"],
            retail_price=data.get("retail_price"),
        )
        stock = (
            BatchStock.objects.filter(branch=branch, batch=batch)
            .select_related("branch", "batch__product", "batch__supplier")
            .get()
        )
        return Response(
            s.BatchSerializer(
                shapes.batch_out(
                    stock, cost=self.cost, today=self.today(), settings=self.stock_settings
                )
            ).data,
            status=201,
        )


class ExpiryView(StockView):
    perm = READ

    @extend_schema(
        parameters=[BRANCH_PARAM, OpenApiParameter("within", int, description="Days, max 365.")],
        responses=s.ExpiryBoardSerializer,
    )
    def get(self, request, company_id):
        within = min(max(_int(request.query_params.get("within", 90), "within"), 1), 365)
        board = queries.expiry_board(
            self.company, branch_ids=self.branches(), within=within, as_of=self.today()
        )
        if not self.cost:
            for bucket in board["buckets"]:
                bucket.pop("value")
                for row in bucket["rows"]:
                    row.pop("value")
        return Response(s.ExpiryBoardSerializer(board).data)


class MovementsView(StockView):
    perm = READ

    @extend_schema(
        parameters=[
            BRANCH_PARAM,
            OpenApiParameter("from", str),
            OpenApiParameter("to", str),
            OpenApiParameter("kind", str),
            OpenApiParameter("product", int),
        ],
        responses=s.MovementSerializer(many=True),
    )
    def get(self, request, company_id):
        params = request.query_params
        today = self.today()
        end = _date(params.get("to"), "to") or today
        start = _date(params.get("from"), "from") or end - timedelta(days=30)
        kinds = [kind for kind in (params.get("kind") or "").split(",") if kind]
        rows = queries.movements(
            self.company, start, end, branch_ids=self.branches(), kinds=kinds or None
        )
        if params.get("product"):
            rows = rows.filter(product_id=_int(params["product"], "product"))
        return Response(
            s.MovementSerializer(
                [shapes.movement_out(row, cost=self.cost) for row in rows[:500]], many=True
            ).data
        )


# Receipts -----------------------------------------------------------------------------------


class ReceiptBase(StockView):
    def get_receipt(self, pk) -> GoodsReceipt:
        receipt = (
            queries.receipts(self.company, branch_ids=self.branch_scope)
            .select_related("received_by", "posted_by", "debt")
            .filter(pk=pk)
            .first()
        )
        if receipt is None:
            raise NotFound
        return receipt

    def detail(self, receipt: GoodsReceipt) -> Response:
        receipt = self.get_receipt(receipt.pk)
        lines = list(receipt.lines.select_related("product", "batch").order_by("order", "pk"))
        return Response(
            s.ReceiptDetailSerializer(
                {
                    "receipt": shapes.receipt_out(
                        receipt, cost=self.cost, user=self.request.user, lines=lines
                    ),
                    "lines": [
                        shapes.receipt_line_out(line, cost=self.cost, settings=self.stock_settings)
                        for line in lines
                    ],
                }
            ).data
        )

    def line_fields(self, data: dict) -> dict:
        fields = dict(data)
        if "product" in fields:
            fields["product"] = self.product(fields["product"])
        return fields


class ReceiptsView(ReceiptBase):
    perm = READ
    perms_by_action = {"post": OPERATE}

    @extend_schema(
        parameters=[
            BRANCH_PARAM,
            OpenApiParameter("status", str),
            OpenApiParameter("supplier", int),
            OpenApiParameter("q", str),
        ],
        responses=s.ReceiptSerializer(many=True),
    )
    def get(self, request, company_id):
        params = request.query_params
        rows = queries.receipts(self.company, branch_ids=self.branches()).select_related(
            "received_by", "posted_by", "debt"
        )
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("supplier"):
            rows = rows.filter(supplier_id=_int(params["supplier"], "supplier"))
        if q := (params.get("q") or "").strip():
            rows = rows.filter(
                Q(number__icontains=q)
                | Q(supplier_invoice_number__icontains=q)
                | Q(supplier__name__icontains=q)
            )
        rows = list(rows.prefetch_related("lines")[:300])
        return Response(
            s.ReceiptSerializer(
                [
                    shapes.receipt_out(
                        row, cost=self.cost, user=request.user, lines=list(row.lines.all())
                    )
                    for row in rows
                ],
                many=True,
            ).data
        )

    @extend_schema(request=s.ReceiptWriteSerializer, responses={201: s.ReceiptDetailSerializer})
    def post(self, request, company_id):
        serializer = s.ReceiptWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        lines = [self.line_fields(line) for line in data.pop("lines", [])]
        receipt = services.create_receipt(
            self.company,
            by=self.membership,
            branch=self.branch(data.pop("branch")),
            supplier=self.supplier(data.pop("supplier")),
            lines=lines,
            **data,
        )
        response = self.detail(receipt)
        response.status_code = 201
        return response


class ReceiptView(ReceiptBase):
    perm = READ
    perms_by_action = {"patch": OPERATE}

    @extend_schema(responses=s.ReceiptDetailSerializer)
    def get(self, request, company_id, pk):
        return self.detail(self.get_receipt(pk))

    @extend_schema(request=s.ReceiptWriteSerializer, responses=s.ReceiptDetailSerializer)
    def patch(self, request, company_id, pk):
        receipt = self.get_receipt(pk)
        serializer = s.ReceiptWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("lines", None)
        if "branch" in data:
            data["branch"] = self.branch(data["branch"])
        if "supplier" in data:
            data["supplier"] = self.supplier(data["supplier"])
        services.update_receipt(receipt, by=self.membership, **data)
        return self.detail(receipt)


class ReceiptLinesView(ReceiptBase):
    perm = OPERATE

    @extend_schema(request=s.ReceiptLineWriteSerializer, responses={201: s.ReceiptDetailSerializer})
    def post(self, request, company_id, pk):
        receipt = self.get_receipt(pk)
        serializer = s.ReceiptLineWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_line(
            receipt, by=self.membership, **self.line_fields(serializer.validated_data)
        )
        response = self.detail(receipt)
        response.status_code = 201
        return response


class ReceiptLineView(ReceiptBase):
    perm = OPERATE

    def _line(self, receipt, line_id) -> GoodsReceiptLine:
        line = receipt.lines.filter(pk=line_id).select_related("product").first()
        if line is None:
            raise NotFound
        return line

    @extend_schema(request=s.ReceiptLineWriteSerializer, responses=s.ReceiptDetailSerializer)
    def patch(self, request, company_id, pk, line_id):
        receipt = self.get_receipt(pk)
        line = self._line(receipt, line_id)
        serializer = s.ReceiptLineWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_line(
            line, by=self.membership, **self.line_fields(serializer.validated_data)
        )
        return self.detail(receipt)

    @extend_schema(responses=s.ReceiptDetailSerializer)
    def delete(self, request, company_id, pk, line_id):
        receipt = self.get_receipt(pk)
        services.remove_line(self._line(receipt, line_id), by=self.membership)
        return self.detail(receipt)


class ReceiptLinesImportView(ReceiptBase):
    """POST stock/receipts/{id}/lines/import/: the distributor's invoice spreadsheet into
    lines, a dry run first."""

    perm = OPERATE

    @extend_schema(request=s.ImportSerializer, responses=s.LineImportResultSerializer)
    def post(self, request, company_id, pk):
        receipt = self.get_receipt(pk)
        serializer = s.ImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        mapping = data.get("mapping") or None
        if mapping is not None and not isinstance(mapping, dict):
            raise ValidationError({"mapping": [_("Give the columns as a map.")]})
        upload = uploads.accept_document(data["file"], allowed=("xlsx", "csv"))
        result = importing.import_lines(
            receipt, upload, by=self.membership, mapping=mapping, dry_run=data["dry_run"]
        )
        return Response(s.LineImportResultSerializer(result).data)


class ReceiptFileView(ReceiptBase):
    perm = OPERATE

    @extend_schema(request=s.ReceiptFileSerializer, responses=s.ReceiptDetailSerializer)
    def post(self, request, company_id, pk):
        receipt = self.get_receipt(pk)
        serializer = s.ReceiptFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = uploads.accept_document(serializer.validated_data["file"], allowed=DOCUMENT_KINDS)
        services.update_receipt(receipt, by=self.membership, file=upload)
        return self.detail(receipt)


class ReceiptSubmitView(ReceiptBase):
    perm = OPERATE

    @extend_schema(request=None, responses=s.ReceiptDetailSerializer)
    def post(self, request, company_id, pk):
        receipt = services.submit_receipt(self.get_receipt(pk), by=self.membership)
        return self.detail(receipt)


class ReceiptPostView(ReceiptBase):
    perm = MANAGE

    @extend_schema(request=None, responses=s.ReceiptDetailSerializer)
    def post(self, request, company_id, pk):
        receipt = services.post_receipt(self.get_receipt(pk), by=self.membership)
        return self.detail(receipt)


class ReceiptVoidView(ReceiptBase):
    perm = MANAGE

    @extend_schema(request=s.ReasonSerializer, responses=s.ReceiptDetailSerializer)
    def post(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receipt = services.void_receipt(
            self.get_receipt(pk), by=self.membership, reason=serializer.validated_data["reason"]
        )
        return self.detail(receipt)


# Transfers -----------------------------------------------------------------------------------


class TransferBase(StockView):
    def get_transfer(self, pk) -> StockTransfer:
        transfer = (
            queries.transfers(self.company, branch_ids=self.branch_scope)
            .select_related("sent_by", "received_by")
            .filter(pk=pk)
            .first()
        )
        if transfer is None:
            raise NotFound
        return transfer

    def detail(self, transfer) -> Response:
        transfer = self.get_transfer(transfer.pk)
        lines = list(transfer.lines.select_related("product", "batch"))
        return Response(
            s.TransferDetailSerializer(
                {
                    "transfer": shapes.transfer_out(transfer, lines_count=len(lines)),
                    "lines": [shapes.transfer_line_out(line) for line in lines],
                }
            ).data
        )


class TransfersView(TransferBase):
    perm = READ
    perms_by_action = {"post": MANAGE}

    @extend_schema(
        parameters=[BRANCH_PARAM, OpenApiParameter("status", str)],
        responses=s.TransferSerializer(many=True),
    )
    def get(self, request, company_id):
        rows = queries.transfers(self.company, branch_ids=self.branches()).select_related(
            "sent_by", "received_by"
        )
        if request.query_params.get("status"):
            rows = rows.filter(status__in=request.query_params["status"].split(","))
        rows = rows.annotate(line_total=Count("lines"))[:300]
        return Response(
            s.TransferSerializer(
                [shapes.transfer_out(row, lines_count=row.line_total) for row in rows], many=True
            ).data
        )

    @extend_schema(request=s.TransferWriteSerializer, responses={201: s.TransferDetailSerializer})
    def post(self, request, company_id):
        serializer = s.TransferWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        source = self.branch(data["from_branch"], "from_branch")
        target = self.company.branches.filter(pk=data["to_branch"], is_active=True).first()
        if target is None:
            raise ValidationError({"to_branch": [_("Pick a pharmacy of this company.")]})
        lines = []
        for row in data["lines"]:
            product = self.product(row["product"])
            batch = None
            if row.get("batch"):
                batch = StockBatch.objects.for_company(self.company).filter(pk=row["batch"]).first()
                if batch is None:
                    raise ValidationError({"lines": [_("Pick a series of this company.")]})
            lines.append({"product": product, "batch": batch, "quantity": row["quantity"]})
        transfer = services.create_transfer(
            self.company,
            by=self.membership,
            from_branch=source,
            to_branch=target,
            lines=lines,
            note=data.get("note", ""),
        )
        if data.get("send"):
            transfer = services.send_transfer(transfer, by=self.membership)
        response = self.detail(transfer)
        response.status_code = 201
        return response


class TransferView(TransferBase):
    perm = READ

    @extend_schema(responses=s.TransferDetailSerializer)
    def get(self, request, company_id, pk):
        return self.detail(self.get_transfer(pk))


class TransferSendView(TransferBase):
    perm = MANAGE

    @extend_schema(request=None, responses=s.TransferDetailSerializer)
    def post(self, request, company_id, pk):
        transfer = self.get_transfer(pk)
        if not self.in_scope(transfer.from_branch_id):
            raise NotFound
        return self.detail(services.send_transfer(transfer, by=self.membership))


class TransferReceiveView(TransferBase):
    perm = OPERATE

    @extend_schema(request=s.ReceiveSerializer, responses=s.TransferDetailSerializer)
    def post(self, request, company_id, pk):
        transfer = self.get_transfer(pk)
        if not self.in_scope(transfer.to_branch_id):
            raise NotFound
        serializer = s.ReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        received = {
            row["line"]: row["quantity"] for row in serializer.validated_data.get("lines", [])
        }
        return self.detail(
            services.receive_transfer(transfer, by=self.membership, received=received)
        )


class TransferResolveView(TransferBase):
    perm = MANAGE

    @extend_schema(request=s.ResolveSerializer, responses=s.TransferDetailSerializer)
    def post(self, request, company_id, pk):
        serializer = s.ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer = services.resolve_transfer(
            self.get_transfer(pk), by=self.membership, **serializer.validated_data
        )
        return self.detail(transfer)


class TransferVoidView(TransferBase):
    perm = MANAGE

    @extend_schema(request=s.ReasonSerializer, responses=s.TransferDetailSerializer)
    def post(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer = services.void_transfer(
            self.get_transfer(pk), by=self.membership, reason=serializer.validated_data["reason"]
        )
        return self.detail(transfer)


# Write-offs ----------------------------------------------------------------------------------


def accept_writeoff_file(upload, kind: str):
    """Photos are re-encoded; a signed act or an order may also be a PDF."""
    if kind in ("photo", "video"):
        return uploads.sanitize_image(upload)
    return uploads.accept_document(upload, allowed=("pdf", "image"))


class WriteOffBase(StockView):
    def get_writeoff(self, pk) -> WriteOff:
        writeoff = (
            queries.writeoffs(self.company, branch_ids=self.branch_scope)
            .select_related("proposed_by", "approved_by")
            .filter(pk=pk)
            .first()
        )
        if writeoff is None:
            raise NotFound
        return writeoff

    def detail(self, writeoff) -> Response:
        writeoff = self.get_writeoff(writeoff.pk)
        lines = list(writeoff.lines.select_related("batch__product"))
        files = list(writeoff.files.all())
        return Response(
            s.WriteOffDetailSerializer(
                {
                    "writeoff": shapes.writeoff_out(
                        writeoff, cost=self.cost, user=self.request.user, lines_count=len(lines)
                    ),
                    "lines": [shapes.writeoff_line_out(line, cost=self.cost) for line in lines],
                    "files": [
                        shapes.writeoff_file_out(
                            row, user=self.request.user, company_id=self.company.pk
                        )
                        for row in files
                    ],
                    "commission_min": self.stock_settings.destroy_commission_min,
                }
            ).data
        )


class WriteOffsView(WriteOffBase):
    perm = READ
    perms_by_action = {"post": OPERATE}

    @extend_schema(
        parameters=[BRANCH_PARAM, OpenApiParameter("status", str), OpenApiParameter("reason", str)],
        responses=s.WriteOffSerializer(many=True),
    )
    def get(self, request, company_id):
        rows = queries.writeoffs(self.company, branch_ids=self.branches()).select_related(
            "proposed_by", "approved_by"
        )
        if request.query_params.get("status"):
            rows = rows.filter(status__in=request.query_params["status"].split(","))
        if request.query_params.get("reason"):
            rows = rows.filter(reason=request.query_params["reason"])
        rows = rows.annotate(line_total=Count("lines"))[:300]
        return Response(
            s.WriteOffSerializer(
                [
                    shapes.writeoff_out(
                        row, cost=self.cost, user=request.user, lines_count=row.line_total
                    )
                    for row in rows
                ],
                many=True,
            ).data
        )

    @extend_schema(request=s.WriteOffWriteSerializer, responses={201: s.WriteOffDetailSerializer})
    def post(self, request, company_id):
        serializer = s.WriteOffWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        branch = self.branch(data["branch"])
        lines = []
        for row in data["lines"]:
            batch = StockBatch.objects.for_company(self.company).filter(pk=row["batch"]).first()
            if batch is None:
                raise ValidationError({"lines": [_("Pick a series of this company.")]})
            lines.append({"batch": batch, "quantity": row["quantity"]})
        recall = None
        if data.get("recall"):
            recall = (
                RecallNotice.objects.for_company(self.company).filter(pk=data["recall"]).first()
            )
        writeoff = services.propose_writeoff(
            self.company,
            by=self.membership,
            branch=branch,
            reason=data["reason"],
            lines=lines,
            note=data.get("note", ""),
            recall=recall,
        )
        response = self.detail(writeoff)
        response.status_code = 201
        return response


class WriteOffView(WriteOffBase):
    perm = READ

    @extend_schema(responses=s.WriteOffDetailSerializer)
    def get(self, request, company_id, pk):
        return self.detail(self.get_writeoff(pk))


class WriteOffApproveView(WriteOffBase):
    perm = MANAGE

    @extend_schema(request=None, responses=s.WriteOffDetailSerializer)
    def post(self, request, company_id, pk):
        return self.detail(services.approve_writeoff(self.get_writeoff(pk), by=self.membership))


class WriteOffVoidView(WriteOffBase):
    perm = MANAGE

    @extend_schema(request=s.ReasonSerializer, responses=s.WriteOffDetailSerializer)
    def post(self, request, company_id, pk):
        serializer = s.ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        writeoff = services.void_writeoff(
            self.get_writeoff(pk), by=self.membership, reason=serializer.validated_data["reason"]
        )
        return self.detail(writeoff)


class WriteOffDestroyedView(WriteOffBase):
    perm = MANAGE

    @extend_schema(request=s.DestroyedSerializer, responses=s.WriteOffDetailSerializer)
    def post(self, request, company_id, pk):
        serializer = s.DestroyedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        writeoff = services.mark_destroyed(
            self.get_writeoff(pk), by=self.membership, **serializer.validated_data
        )
        return self.detail(writeoff)


class WriteOffFilesView(WriteOffBase):
    perm = OPERATE

    @extend_schema(request=s.WriteOffUploadSerializer, responses={201: s.WriteOffDetailSerializer})
    def post(self, request, company_id, pk):
        writeoff = self.get_writeoff(pk)
        serializer = s.WriteOffUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kind = serializer.validated_data["kind"]
        upload = accept_writeoff_file(serializer.validated_data["file"], kind)
        services.add_writeoff_file(writeoff, by=self.membership, upload=upload, kind=kind)
        response = self.detail(writeoff)
        response.status_code = 201
        return response


class WriteOffActView(WriteOffBase):
    perm = READ

    @extend_schema(
        parameters=[
            OpenApiParameter("language", str, description="uz or ru; your own by default.")
        ],
        responses=FILE_LINK,
    )
    def get(self, request, company_id, pk):
        writeoff = self.get_writeoff(pk)
        if writeoff.status not in (WriteOff.Status.APPROVED, WriteOff.Status.DESTROYED):
            raise ValidationError(
                {"status": [_("The act is made once the write-off is approved.")]}
            )
        language = request.query_params.get("language") or request.user.language
        if language not in ("uz", "ru", "en"):
            language = self.company.default_language
        data = journals.act_pdf(writeoff, language=language)
        name = f"akt-{writeoff.number or writeoff.pk}-{language}.pdf"
        return Response(
            _store_pdf(
                self.company,
                request.user,
                f"acts/{writeoff.pk}",
                data,
                name,
                f"inventory.writeoff_act:{writeoff.pk}",
            )
        )


def _store_pdf(company, user, key: str, data: bytes, name: str, check: str) -> dict:
    from django.core.files.base import ContentFile

    from apps.core.files import DEFAULT_TTL, signed_url
    from apps.core.storage import private_storage

    path = f"inventory/print/{company.pk}/{key.replace('/', '-')}-{name}"
    if private_storage.exists(path):
        private_storage.delete(path)
    stored = private_storage.save(path, ContentFile(data))
    url = signed_url(stored, user=user, company_id=company.pk, check=check, filename=name)
    return {"url": url, "name": name, "expires_in": DEFAULT_TTL}


# Counts ---------------------------------------------------------------------------------------


class CountBase(StockView):
    def get_count(self, pk) -> StockCount:
        count = queries.counts(self.company, branch_ids=self.branch_scope).filter(pk=pk).first()
        if count is None:
            raise NotFound
        return count

    def detail(self, count) -> Response:
        count = self.get_count(count.pk)
        blind = count.status == StockCount.Status.OPEN or not self.membership.has_perm(MANAGE)
        lines = list(count.lines.select_related("product", "batch"))
        return Response(
            s.CountDetailSerializer(
                {
                    "count": shapes.count_out(
                        count,
                        cost=self.cost,
                        counted=sum(1 for line in lines if line.counted is not None),
                    ),
                    "lines": [
                        shapes.count_line_out(line, blind=blind, cost=self.cost) for line in lines
                    ],
                }
            ).data
        )


class CountsView(CountBase):
    perm = READ
    perms_by_action = {"post": OPERATE}

    @extend_schema(
        parameters=[BRANCH_PARAM, OpenApiParameter("status", str)],
        responses=s.CountSerializer(many=True),
    )
    def get(self, request, company_id):
        rows = queries.counts(self.company, branch_ids=self.branches())
        if request.query_params.get("status"):
            rows = rows.filter(status__in=request.query_params["status"].split(","))
        rows = rows.annotate(counted_total=Count("lines", filter=Q(lines__counted__isnull=False)))
        return Response(
            s.CountSerializer(
                [
                    shapes.count_out(row, cost=self.cost, counted=row.counted_total)
                    for row in rows[:200]
                ],
                many=True,
            ).data
        )

    @extend_schema(request=s.CountWriteSerializer, responses={201: s.CountDetailSerializer})
    def post(self, request, company_id):
        serializer = s.CountWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        category = None
        if data.get("category"):
            category = (
                ProductCategory.objects.for_company(self.company)
                .filter(pk=data["category"])
                .first()
            )
            if category is None:
                raise ValidationError({"category": [_("Pick a category.")]})
        count = services.start_count(
            self.branch(data["branch"]), by=self.membership, kind=data["kind"], category=category
        )
        response = self.detail(count)
        response.status_code = 201
        return response


class CountView(CountBase):
    perm = READ

    @extend_schema(responses=s.CountDetailSerializer)
    def get(self, request, company_id, pk):
        return self.detail(self.get_count(pk))


class CountLinesView(CountBase):
    perm = OPERATE

    @extend_schema(request=s.CountedSerializer, responses=s.CountDetailSerializer)
    def post(self, request, company_id, pk):
        count = self.get_count(pk)
        serializer = s.CountedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_counted(
            count,
            by=self.membership,
            counted={row["line"]: row["counted"] for row in serializer.validated_data["lines"]},
        )
        return self.detail(count)


class CountFoundView(CountBase):
    perm = OPERATE

    @extend_schema(request=s.FoundSerializer, responses={201: s.CountDetailSerializer})
    def post(self, request, company_id, pk):
        count = self.get_count(pk)
        serializer = s.FoundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["product"] = self.product(data["product"])
        services.add_found(count, by=self.membership, **data)
        response = self.detail(count)
        response.status_code = 201
        return response


class CountSubmitView(CountBase):
    perm = OPERATE

    @extend_schema(request=None, responses=s.CountDetailSerializer)
    def post(self, request, company_id, pk):
        return self.detail(services.submit_count(self.get_count(pk), by=self.membership))


class CountApplyView(CountBase):
    perm = MANAGE

    @extend_schema(request=None, responses=s.CountDetailSerializer)
    def post(self, request, company_id, pk):
        return self.detail(services.apply_count(self.get_count(pk), by=self.membership))


# Recalls --------------------------------------------------------------------------------------


class RecallBase(StockView):
    def get_recall(self, pk) -> RecallNotice:
        recall = (
            RecallNotice.objects.for_company(self.company)
            .select_related("product")
            .filter(pk=pk)
            .first()
        )
        if recall is None:
            raise NotFound
        return recall

    def out(self, recall) -> dict:
        batch_ids = [row.get("batch_id") for row in recall.found or []]
        left = {
            (row.branch_id, row.batch_id): row.quantity
            for row in BatchStock.objects.filter(batch_id__in=batch_ids)
        }
        return shapes.recall_out(
            recall, branch_ids=self.branch_scope, user=self.request.user, left_by_batch=left
        )


class RecallsView(RecallBase):
    perm = READ
    perms_by_action = {"post": MANAGE}

    @extend_schema(
        parameters=[OpenApiParameter("status", str)], responses=s.RecallSerializer(many=True)
    )
    def get(self, request, company_id):
        rows = RecallNotice.objects.for_company(self.company).select_related("product")
        if request.query_params.get("status"):
            rows = rows.filter(status=request.query_params["status"])
        return Response(s.RecallSerializer([self.out(row) for row in rows[:200]], many=True).data)

    @extend_schema(request=s.RecallWriteSerializer, responses={201: s.RecallSerializer})
    def post(self, request, company_id):
        serializer = s.RecallWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        product = self.product(data.pop("product")) if data.get("product") else None
        data.pop("product", None)
        upload = data.pop("file", None)
        file = uploads.accept_document(upload, allowed=DOCUMENT_KINDS) if upload else None
        recall = services.register_recall(
            self.company, by=self.membership, product=product, file=file, **data
        )
        return Response(s.RecallSerializer(self.out(recall)).data, status=201)


class RecallView(RecallBase):
    perm = READ

    @extend_schema(responses=s.RecallSerializer)
    def get(self, request, company_id, pk):
        return Response(s.RecallSerializer(self.out(self.get_recall(pk))).data)


class RecallCloseView(RecallBase):
    perm = MANAGE

    @extend_schema(request=None, responses=s.RecallSerializer)
    def post(self, request, company_id, pk):
        recall = services.close_recall(self.get_recall(pk), by=self.membership)
        return Response(s.RecallSerializer(self.out(recall)).data)


# Pricing rules and defektura --------------------------------------------------------------------


def _rule_out(rule: PricingRule) -> dict:
    return {
        "id": rule.pk,
        "category": rule.category_id,
        "category_name": rule.category.name if rule.category_id else None,
        "cost_from": rule.cost_from,
        "cost_to": rule.cost_to,
        "markup_percent": rule.markup_percent,
        "order": rule.order,
        "is_active": rule.is_active,
    }


class PricingRulesView(StockView):
    perm = READ
    perms_by_action = {"post": MANAGE}

    def rows(self):
        return [
            _rule_out(rule)
            for rule in PricingRule.objects.for_company(self.company).select_related("category")
        ]

    def fields(self, data):
        data = dict(data)
        if "category" in data:
            data["category"] = (
                ProductCategory.objects.for_company(self.company)
                .filter(pk=data["category"])
                .first()
                if data["category"]
                else None
            )
        return data

    @extend_schema(responses=s.PricingRuleSerializer(many=True))
    def get(self, request, company_id):
        return Response(s.PricingRuleSerializer(self.rows(), many=True).data)

    @extend_schema(
        request=s.PricingRuleSerializer, responses={201: s.PricingRuleSerializer(many=True)}
    )
    def post(self, request, company_id):
        serializer = s.PricingRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.save_pricing_rule(
            self.company, by=self.membership, **self.fields(serializer.validated_data)
        )
        return Response(s.PricingRuleSerializer(self.rows(), many=True).data, status=201)


class PricingRuleView(PricingRulesView):
    perm = MANAGE
    perms_by_action = {}
    http_method_names = ["patch", "delete", "options"]

    def _rule(self, pk):
        rule = PricingRule.objects.for_company(self.company).filter(pk=pk).first()
        if rule is None:
            raise NotFound
        return rule

    @extend_schema(request=s.PricingRuleSerializer, responses=s.PricingRuleSerializer(many=True))
    def patch(self, request, company_id, pk):
        rule = self._rule(pk)
        serializer = s.PricingRuleSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.save_pricing_rule(
            self.company, by=self.membership, rule=rule, **self.fields(serializer.validated_data)
        )
        return Response(s.PricingRuleSerializer(self.rows(), many=True).data)

    @extend_schema(responses={204: None})
    def delete(self, request, company_id, pk):
        services.delete_pricing_rule(self._rule(pk), by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PriceTagsView(StockView):
    """POST stock/price-tags/: the shelf's price tags as a PDF (prescription items on a counter
    list, not for public display): the items named, else those whose price changed lately."""

    perm = READ

    @extend_schema(request=s.PriceTagsSerializer, responses=FILE_LINK)
    def post(self, request, company_id):
        serializer = s.PriceTagsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        branch = self.branch(data["branch"])
        if data.get("products"):
            products = list(
                Product.objects.for_company(self.company)
                .filter(pk__in=data["products"], is_active=True)
                .select_related("manufacturer")
                .order_by("name", "pk")
            )
        else:
            since = data.get("changed_since") or self.today() - timedelta(days=7)
            products = queries.price_changes(self.company, branch, since)
        language = data.get("language") or request.user.language or self.company.default_language
        pdf = journals.price_tags_pdf(branch, products, language=language)
        name = f"narx-{branch.code or branch.pk}-{self.today():%Y-%m-%d}-{language}.pdf"
        return Response(
            _store_pdf(
                self.company,
                request.user,
                f"tags/{branch.pk}",
                pdf,
                name,
                f"inventory.journal:{branch.pk}",
            )
        )


class DefekturaView(StockView):
    perm = READ
    perms_by_action = {"post": OPERATE}

    @extend_schema(
        parameters=[BRANCH_PARAM, OpenApiParameter("status", str)],
        responses=s.RequestSerializer(many=True),
    )
    def get(self, request, company_id):
        rows = MissingRequest.objects.for_company(self.company).select_related(
            "branch", "product", "requested_by"
        )
        scope = self.branches()
        if scope is not None:
            rows = rows.filter(branch_id__in=scope)
        if request.query_params.get("status"):
            rows = rows.filter(status__in=request.query_params["status"].split(","))
        return Response(
            s.RequestSerializer([shapes.request_out(row) for row in rows[:300]], many=True).data
        )

    @extend_schema(request=s.RequestSerializer, responses={201: s.RequestSerializer})
    def post(self, request, company_id):
        serializer = s.RequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = services.add_request(
            self.branch(data["branch"]),
            by=self.membership,
            product=self.product(data["product"]) if data.get("product") else None,
            name=data.get("name", ""),
            packs=data.get("packs") or 1,
            customer_phone=data.get("customer_phone", ""),
        )
        return Response(s.RequestSerializer(shapes.request_out(row)).data, status=201)


class DefekturaItemView(StockView):
    perm = OPERATE

    @extend_schema(request=s.RequestStatusSerializer, responses=s.RequestSerializer)
    def patch(self, request, company_id, pk):
        row = (
            MissingRequest.objects.for_company(self.company)
            .select_related("branch", "product")
            .filter(pk=pk)
            .first()
        )
        if row is None or not self.in_scope(row.branch_id):
            raise NotFound
        serializer = s.RequestStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.set_request_status(row, by=self.membership, **serializer.validated_data)
        return Response(s.RequestSerializer(shapes.request_out(row)).data)


# Journals --------------------------------------------------------------------------------------

JOURNAL_PARAMS = [
    OpenApiParameter("branch", int, required=True),
    OpenApiParameter("month", str, required=True, description="YYYY-MM"),
]


class JournalBase(StockView):
    perm = CONTROLLED

    def target(self) -> tuple[Branch, date]:
        params = self.request.query_params
        branch = self.scoped_branch(_int(params.get("branch"), "branch"))
        return branch, _month(params.get("month"))


class RxJournalView(JournalBase):
    @extend_schema(parameters=JOURNAL_PARAMS, responses=s.RxJournalSerializer)
    def get(self, request, company_id):
        branch, month = self.target()
        start, end = register._bounds(self.company, month)
        rows = (
            RxRecord.objects.filter(branch=branch, recorded_at__gte=start, recorded_at__lt=end)
            .select_related("branch", "product", "batch", "recorded_by")
            .order_by("recorded_at", "pk")
        )
        return Response(
            s.RxJournalSerializer(
                {
                    "branch": {"id": branch.pk, "name": branch.name, "code": branch.code},
                    "month": month,
                    "rows": [shapes.rx_out(row, settings=self.stock_settings) for row in rows],
                }
            ).data
        )

    @extend_schema(request=s.RxWriteSerializer, responses={201: s.RxRecordSerializer})
    def post(self, request, company_id):
        serializer = s.RxWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        branch = self.branch(data.pop("branch"))
        product = self.product(data.pop("product"))
        if data.get("batch"):
            data["batch"] = (
                StockBatch.objects.for_company(self.company).filter(pk=data["batch"]).first()
            )
        else:
            data.pop("batch", None)
        record = services.record_rx(
            by=self.membership,
            branch=branch,
            product=product,
            quantity=data.pop("quantity"),
            **data,
        )
        if record is None:
            raise ValidationError(
                {"product": [_("The prescription log is off, or this item needs no prescription.")]}
            )
        record = RxRecord.objects.select_related("branch", "product", "batch", "recorded_by").get(
            pk=record.pk
        )
        return Response(
            s.RxRecordSerializer(shapes.rx_out(record, settings=self.stock_settings)).data,
            status=201,
        )


class RxJournalPdfView(JournalBase):
    @extend_schema(
        parameters=[*JOURNAL_PARAMS, OpenApiParameter("invalid", bool)],
        responses=FILE_LINK,
    )
    def get(self, request, company_id):
        branch, month = self.target()
        kind = "rx_invalid" if _flag(request.query_params.get("invalid", "")) else "rx"
        language = request.user.language or self.company.default_language
        data = services.journal_pdf(kind, branch=branch, month=month, language=language)
        name = f"{kind}-{branch.code or branch.pk}-{month:%Y-%m}-{language}.pdf"
        return Response(
            _store_pdf(
                self.company,
                request.user,
                f"{kind}/{branch.pk}",
                data,
                name,
                f"inventory.journal:{branch.pk}",
            )
        )


class ControlledJournalView(JournalBase):
    @extend_schema(
        parameters=[*JOURNAL_PARAMS, OpenApiParameter("product", int)],
        responses=s.ControlledRegisterSerializer,
    )
    def get(self, request, company_id):
        branch, month = self.target()
        product = None
        if request.query_params.get("product"):
            product = self.get_product(_int(request.query_params["product"], "product"))
        return self.answer(branch, month, product)

    def answer(self, branch, month, product=None) -> Response:
        rows = register.rows(branch, month, product=product)
        licensed = self.company.branches.filter(controlled_licence=True, is_active=True)
        if self.branch_scope is not None:
            licensed = licensed.filter(pk__in=self.branch_scope)
        close_by = register.next_month(month).replace(day=self.stock_settings.controlled_close_day)
        return Response(
            s.ControlledRegisterSerializer(
                {
                    "branch": {"id": branch.pk, "name": branch.name, "code": branch.code},
                    "month": month,
                    "closed": any(row["closed_at"] for row in rows),
                    "close_by": close_by,
                    "rows": rows,
                    "branches": [
                        {"id": row.pk, "name": row.name, "code": row.code} for row in licensed
                    ],
                }
            ).data
        )


class ControlledPdfView(JournalBase):
    @extend_schema(
        parameters=[*JOURNAL_PARAMS, OpenApiParameter("product", int)], responses=FILE_LINK
    )
    def get(self, request, company_id):
        branch, month = self.target()
        product = None
        if request.query_params.get("product"):
            product = self.get_product(_int(request.query_params["product"], "product"))
        language = request.user.language or self.company.default_language
        data = services.journal_pdf(
            "controlled", branch=branch, month=month, product=product, language=language
        )
        name = f"controlled-{branch.code or branch.pk}-{month:%Y-%m}-{language}.pdf"
        return Response(
            _store_pdf(
                self.company,
                request.user,
                f"controlled/{branch.pk}",
                data,
                name,
                f"inventory.journal:{branch.pk}",
            )
        )


class ControlledCloseView(ControlledJournalView):
    http_method_names = ["post", "options"]

    @extend_schema(request=s.CloseMonthSerializer, responses=s.ControlledRegisterSerializer)
    def post(self, request, company_id):
        serializer = s.CloseMonthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        branch = self.scoped_branch(data["branch"])
        register.close_month(
            branch,
            data["month"],
            by=self.membership,
            counted={row["product"]: row["counted"] for row in data.get("counted", [])},
            note=data.get("note", ""),
        )
        return self.answer(branch, register.month_start(data["month"]))


class ControlledReportedView(JournalBase):
    @extend_schema(request=s.ReportedSerializer, responses=s.ControlledRowSerializer(many=True))
    def post(self, request, company_id, pk):
        period = (
            ControlledPeriod.objects.for_company(self.company)
            .select_related("branch", "product")
            .filter(pk=pk)
            .first()
        )
        if period is None or not self.in_scope(period.branch_id):
            raise NotFound
        serializer = s.ReportedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        register.mark_reported(period, by=self.membership, **serializer.validated_data)
        return Response(
            s.ControlledRowSerializer(
                register.rows(period.branch, period.month, product=period.product), many=True
            ).data
        )


def holds_any(member, *perms) -> bool:
    return holds(member, AnyOf(*perms))
