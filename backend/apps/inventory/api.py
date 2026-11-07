"""Employee (mini app) endpoints of stock, routed in `urls.py` under
`/api/v1/companies/<id>/stock/…` (docs/PLAN-OWNER.md §14.6.4; P builds the screens in Wave 3).

    GET        stock/settings/                    the app's flags
    GET        stock/lookup/?q=                   my branches first, then the others (when shown)
    GET        stock/products/{id}/               batches here, analogs, other branches
    GET/POST   stock/receipts/                    my branches' drafts · a new draft
    POST       stock/receipts/{id}/lines/ · PATCH stock/receipts/{id}/lines/{line}/
    POST       stock/receipts/{id}/submit/
    GET/PATCH  stock/counts/{id}/lines/           blind: never the expected quantity
    GET        stock/expiry/ · POST stock/batches/{id}/expiry-action/
    GET        stock/transfers/incoming/ · POST stock/transfers/{id}/receive/
    POST       stock/defektura/ · stock/rx/

Reading needs sales.view, stock.manage or stock.operate; the rest stock.operate or
stock.manage. Costs never reach the app. While the stock module is off everything answers 403.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.console.perms import AnyOf, holds
from apps.core import uploads
from apps.finance.models import Counterparty
from apps.inventory import conf, engine, pricing, queries, services, shapes
from apps.inventory import serializers as s
from apps.inventory.audit_actions import InventoryAction
from apps.inventory.models import (
    BatchStock,
    GoodsReceipt,
    Product,
    RxRecord,
    StockBatch,
    StockCount,
    StockTransfer,
    WriteOff,
    WriteOffFile,
)
from apps.members import scope
from apps.members.api import IsCompanyMember
from apps.members.models import Membership
from apps.members.permissions import Perm

READ = AnyOf(Perm.SALES_VIEW, Perm.STOCK_MANAGE, Perm.STOCK_OPERATE)
OPERATE = AnyOf(Perm.STOCK_OPERATE, Perm.STOCK_MANAGE)


class StockOn(BasePermission):
    def has_permission(self, request, view):
        member = view.membership
        if not member.company.has_feature("stock"):
            raise PermissionDenied(_("Stock isn't switched on for this company."))
        if not holds(member, view.perm):
            raise PermissionDenied(_("You don't have permission to do this."))
        return True


class MemberView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, StockOn)
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    membership: Membership
    perm = READ

    @property
    def company(self):
        return self.membership.company

    @property
    def mine(self) -> list[int] | None:
        return scope.branch_ids(self.membership)

    def my_branch(self, pk=None):
        """The branch the person works at (`pk`, or their home branch / only branch)."""
        allowed = self.mine
        if pk is not None:
            found = self.company.branches.filter(pk=pk).first()
            if found is None or (allowed is not None and found.pk not in allowed):
                raise ValidationError({"branch": [_("Pick a pharmacy you work at.")]})
            return found
        home = self.membership.home_branch
        if home is not None and (allowed is None or home.pk in allowed):
            return home
        rows = self.company.branches.filter(is_active=True)
        if allowed is not None:
            rows = rows.filter(pk__in=allowed)
        found = rows.order_by("order", "pk").first()
        if found is None:
            raise ValidationError({"branch": [_("You don't work at any pharmacy yet.")]})
        return found

    def product(self, pk) -> Product:
        found = Product.objects.for_company(self.company).filter(pk=pk, is_active=True).first()
        if found is None:
            raise ValidationError({"product": [_("Pick an item of the catalogue.")]})
        return found


class AppSettingsSerializer(serializers.Serializer):
    camera_scanning = serializers.BooleanField()
    show_other_branches = serializers.BooleanField()
    rx_log = serializers.BooleanField()
    fefo_strict = serializers.BooleanField()

    class Meta:
        ref_name = "InventoryAppSettings"


class SettingsView(MemberView):
    @extend_schema(responses=AppSettingsSerializer)
    def get(self, request, company_id):
        row = conf.get_settings(self.company)
        return Response(
            AppSettingsSerializer(
                {
                    "camera_scanning": row.camera_scanning,
                    "show_other_branches": row.show_other_branches,
                    "rx_log": row.rx_log,
                    "fefo_strict": row.fefo_strict,
                }
            ).data
        )


class ElsewhereSerializer(serializers.Serializer):
    branch_id = serializers.IntegerField()
    branch = serializers.CharField()
    quantity = s.Qty()

    class Meta:
        ref_name = "InventoryElsewhere"


class LookupRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    trade_name = serializers.CharField()
    inn = serializers.CharField()
    barcode = serializers.CharField()
    rx_required = serializers.BooleanField()
    control_class = serializers.CharField()
    storage = serializers.CharField()
    units_per_pack = serializers.IntegerField()
    part_label = serializers.CharField()
    sale_price = s.Money()
    part_price = s.Money()
    quantity = s.Qty(allow_null=True, help_text="Parts at my pharmacies.")
    elsewhere = ElsewhereSerializer(many=True)

    class Meta:
        ref_name = "InventoryLookupRow"


def _elsewhere(company, product_ids, mine) -> dict[int, list[dict]]:
    rows = queries.levels(company, branch_ids=None).filter(
        product_id__in=list(product_ids), quantity__gt=0
    )
    if mine is not None:
        rows = rows.exclude(branch_id__in=mine)
    found: dict[int, list[dict]] = {}
    for level in rows:
        found.setdefault(level.product_id, []).append(
            {"branch_id": level.branch_id, "branch": level.branch.name, "quantity": level.quantity}
        )
    return found


class LookupView(MemberView):
    @extend_schema(
        parameters=[OpenApiParameter("q", str, required=True)],
        responses=LookupRowSerializer(many=True),
    )
    def get(self, request, company_id):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response([])
        settings = conf.get_settings(self.company)
        rows = queries.lookup(self.company, q, branch_ids=self.mine, limit=30)
        products = {
            row.pk: row for row in Product.objects.filter(pk__in=[row["id"] for row in rows])
        }
        others = (
            _elsewhere(self.company, products, self.mine)
            if settings.show_other_branches and self.mine is not None
            else {}
        )
        data = [
            {
                **row,
                "part_price": pricing.part_price(products[row["id"]], settings=settings),
                "elsewhere": others.get(row["id"], []),
            }
            for row in rows
        ]
        # What I have first.
        data.sort(key=lambda row: (not (row["quantity"] or 0) > 0, row["name"]))
        return Response(LookupRowSerializer(data, many=True).data)


class AppBatchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    batch_id = serializers.IntegerField()
    branch_id = serializers.IntegerField()
    branch = serializers.CharField()
    series = serializers.CharField()
    expires_on = serializers.DateField()
    days_left = serializers.IntegerField()
    expired = serializers.BooleanField()
    status = serializers.CharField()
    quantity = s.Qty()
    retail_price = s.Money()
    part_price = s.Money()

    class Meta:
        ref_name = "InventoryAppBatch"


class AppProductSerializer(serializers.Serializer):
    product = LookupRowSerializer()
    batches = AppBatchSerializer(many=True)
    analogs = s.AnalogSerializer(many=True)

    class Meta:
        ref_name = "InventoryAppProduct"


def _app_batch(stock, *, today, settings) -> dict:
    batch = stock.batch
    return {
        "id": stock.pk,
        "batch_id": batch.pk,
        "branch_id": stock.branch_id,
        "branch": stock.branch.name,
        "series": batch.series,
        "expires_on": batch.expires_on,
        "days_left": (batch.expires_on - today).days,
        "expired": engine.is_expired(batch, today),
        "status": batch.status,
        "quantity": stock.quantity,
        "retail_price": batch.retail_price,
        "part_price": pricing.part_price(batch.product, batch, settings=settings),
    }


class ProductView(MemberView):
    @extend_schema(responses=AppProductSerializer)
    def get(self, request, company_id, pk):
        product = Product.objects.for_company(self.company).filter(pk=pk).first()
        if product is None:
            raise NotFound
        settings = conf.get_settings(self.company)
        today = engine.local_today(self.company)
        held = queries.quantities(self.company, [product.pk], branch_ids=self.mine)
        others = (
            _elsewhere(self.company, [product.pk], self.mine)
            if settings.show_other_branches and self.mine is not None
            else {}
        )
        batches = queries.stock_rows(self.company, branch_ids=self.mine, product_id=product.pk)
        return Response(
            AppProductSerializer(
                {
                    "product": {
                        "id": product.pk,
                        "name": product.name,
                        "trade_name": product.trade_name,
                        "inn": product.inn,
                        "barcode": product.barcode,
                        "rx_required": product.rx_required,
                        "control_class": product.control_class,
                        "storage": product.storage,
                        "units_per_pack": product.units_per_pack,
                        "part_label": product.part_label,
                        "sale_price": product.sale_price,
                        "part_price": pricing.part_price(product, settings=settings),
                        "quantity": held.get(product.pk, Decimal(0))
                        if product.track_stock
                        else None,
                        "elsewhere": others.get(product.pk, []),
                    },
                    "batches": [
                        _app_batch(stock, today=today, settings=settings) for stock in batches
                    ],
                    "analogs": queries.analogs(product, branch_ids=self.mine),
                }
            ).data
        )


# Receipt drafts -------------------------------------------------------------------------------


class AppReceiptLineSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    product = s.Ref()
    units_per_pack = serializers.IntegerField()
    series = serializers.CharField()
    expires_on = serializers.DateField()
    packs = s.Qty()
    quantity = s.Qty()
    warnings = serializers.ListField(child=serializers.CharField())

    class Meta:
        ref_name = "InventoryAppReceiptLine"


class AppReceiptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    branch = s.BranchRef()
    supplier = s.Ref()
    supplier_invoice_number = serializers.CharField()
    supplier_invoice_date = serializers.DateField()
    lines = AppReceiptLineSerializer(many=True)
    created_at = serializers.DateTimeField()

    class Meta:
        ref_name = "InventoryAppReceipt"


class AppReceiptWriteSerializer(serializers.Serializer):
    branch = serializers.IntegerField(required=False)
    supplier = serializers.IntegerField()
    supplier_invoice_number = serializers.CharField(max_length=40, allow_blank=True, required=False)
    supplier_invoice_date = serializers.DateField()
    note = serializers.CharField(allow_blank=True, required=False)
    file = serializers.FileField(required=False)

    class Meta:
        ref_name = "InventoryAppReceiptWrite"


def _app_receipt(receipt: GoodsReceipt) -> dict:
    lines = list(receipt.lines.select_related("product"))
    return {
        "id": receipt.pk,
        "status": receipt.status,
        "branch": {
            "id": receipt.branch_id,
            "name": receipt.branch.name,
            "code": receipt.branch.code,
        },
        "supplier": shapes.ref(receipt.supplier),
        "supplier_invoice_number": receipt.supplier_invoice_number,
        "supplier_invoice_date": receipt.supplier_invoice_date,
        "lines": [
            {
                "id": line.pk,
                "product": shapes.ref(line.product),
                "units_per_pack": line.product.units_per_pack,
                "series": line.series,
                "expires_on": line.expires_on,
                "packs": line.packs,
                "quantity": line.quantity,
                "warnings": list(line.warnings),
            }
            for line in lines
        ],
        "created_at": receipt.created_at,
    }


class ReceiptsView(MemberView):
    perm = OPERATE

    def rows(self):
        rows = GoodsReceipt.objects.for_company(self.company).filter(
            status__in=(GoodsReceipt.Status.DRAFT, GoodsReceipt.Status.SUBMITTED)
        )
        if self.mine is not None:
            rows = rows.filter(branch_id__in=self.mine)
        return rows.select_related("branch", "supplier").order_by("-created_at")

    def get_receipt(self, pk) -> GoodsReceipt:
        found = self.rows().filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    @extend_schema(responses=AppReceiptSerializer(many=True))
    def get(self, request, company_id):
        return Response(
            AppReceiptSerializer([_app_receipt(row) for row in self.rows()[:50]], many=True).data
        )

    @extend_schema(request=AppReceiptWriteSerializer, responses={201: AppReceiptSerializer})
    def post(self, request, company_id):
        serializer = AppReceiptWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        supplier = (
            Counterparty.objects.for_company(self.company).filter(pk=data.pop("supplier")).first()
        )
        if supplier is None:
            raise ValidationError({"supplier": [_("Pick a distributor.")]})
        upload = data.pop("file", None)
        receipt = services.create_receipt(
            self.company,
            by=self.membership,
            branch=self.my_branch(data.pop("branch", None)),
            supplier=supplier,
            file=uploads.accept_document(upload, allowed=("pdf", "xlsx", "csv", "image"))
            if upload
            else None,
            **data,
        )
        return Response(
            AppReceiptSerializer(_app_receipt(self.get_receipt(receipt.pk))).data, status=201
        )


class AppLineWriteSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    series = serializers.CharField(max_length=40)
    expires_on = serializers.DateField()
    made_on = serializers.DateField(allow_null=True, required=False)
    packs = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0)
    unit_cost = s.Money(min_value=0, required=False, default=Decimal(0))
    supplier_rx = serializers.BooleanField(allow_null=True, required=False)

    class Meta:
        ref_name = "InventoryAppLineWrite"


class ReceiptLinesView(ReceiptsView):
    http_method_names = ["post", "options"]

    @extend_schema(request=AppLineWriteSerializer, responses={201: AppReceiptSerializer})
    def post(self, request, company_id, pk):
        receipt = self.get_receipt(pk)
        serializer = AppLineWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["product"] = self.product(data["product"])
        services.add_line(receipt, by=self.membership, **data)
        return Response(AppReceiptSerializer(_app_receipt(self.get_receipt(pk))).data, status=201)


class ReceiptLineView(ReceiptsView):
    http_method_names = ["patch", "delete", "options"]

    def _line(self, receipt, line_id):
        line = receipt.lines.filter(pk=line_id).select_related("product").first()
        if line is None:
            raise NotFound
        return line

    @extend_schema(request=AppLineWriteSerializer, responses=AppReceiptSerializer)
    def patch(self, request, company_id, pk, line_id):
        receipt = self.get_receipt(pk)
        line = self._line(receipt, line_id)
        serializer = AppLineWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "product" in data:
            data["product"] = self.product(data["product"])
        services.update_line(line, by=self.membership, **data)
        return Response(AppReceiptSerializer(_app_receipt(self.get_receipt(pk))).data)

    @extend_schema(responses=AppReceiptSerializer)
    def delete(self, request, company_id, pk, line_id):
        receipt = self.get_receipt(pk)
        services.remove_line(self._line(receipt, line_id), by=self.membership)
        return Response(AppReceiptSerializer(_app_receipt(self.get_receipt(pk))).data)


class ReceiptSubmitView(ReceiptsView):
    http_method_names = ["post", "options"]

    @extend_schema(request=None, responses=AppReceiptSerializer)
    def post(self, request, company_id, pk):
        receipt = services.submit_receipt(self.get_receipt(pk), by=self.membership)
        return Response(AppReceiptSerializer(_app_receipt(self.get_receipt(receipt.pk))).data)


# Counts (blind) -----------------------------------------------------------------------------


class AppCountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    status = serializers.CharField()
    branch = s.BranchRef()
    lines = s.CountLineSerializer(many=True)

    class Meta:
        ref_name = "InventoryAppCount"


class CountLinesView(MemberView):
    """The counter's view of a count: product, series and expiry, never the expected quantity."""

    perm = OPERATE

    def get_count(self, pk) -> StockCount:
        rows = StockCount.objects.for_company(self.company).select_related("branch")
        if self.mine is not None:
            rows = rows.filter(branch_id__in=self.mine)
        found = rows.filter(pk=pk).first()
        if found is None:
            raise NotFound
        return found

    def answer(self, count) -> Response:
        lines = list(count.lines.select_related("product", "batch"))
        return Response(
            AppCountSerializer(
                {
                    "id": count.pk,
                    "kind": count.kind,
                    "status": count.status,
                    "branch": {
                        "id": count.branch_id,
                        "name": count.branch.name,
                        "code": count.branch.code,
                    },
                    "lines": [
                        shapes.count_line_out(line, blind=True, cost=False) for line in lines
                    ],
                }
            ).data
        )

    @extend_schema(responses=AppCountSerializer)
    def get(self, request, company_id, pk):
        return self.answer(self.get_count(pk))

    @extend_schema(request=s.CountedSerializer, responses=AppCountSerializer)
    def patch(self, request, company_id, pk):
        count = self.get_count(pk)
        serializer = s.CountedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_counted(
            count,
            by=self.membership,
            counted={row["line"]: row["counted"] for row in serializer.validated_data["lines"]},
        )
        return self.answer(self.get_count(pk))


# Expiry --------------------------------------------------------------------------------------


class ExpiryView(MemberView):
    @extend_schema(
        parameters=[OpenApiParameter("within", int)], responses=AppBatchSerializer(many=True)
    )
    def get(self, request, company_id):
        settings = conf.get_settings(self.company)
        try:
            within = int(request.query_params.get("within") or (settings.expiry_steps or [90])[0])
        except ValueError as exc:
            raise ValidationError({"within": [_("Give a number.")]}) from exc
        today = engine.local_today(self.company)
        branch = self.my_branch()
        rows = queries.stock_rows(self.company, branch_ids=[branch.pk]).filter(
            batch__expires_on__lte=today + timedelta(days=min(max(within, 1), 365))
        )
        return Response(
            AppBatchSerializer(
                [_app_batch(stock, today=today, settings=settings) for stock in rows], many=True
            ).data
        )


class ExpiryActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=[("on_shelf", "on_shelf"), ("propose_writeoff", "propose_writeoff")]
    )
    reason = serializers.ChoiceField(choices=WriteOff.Reason.choices, required=False)
    photo = serializers.ImageField(required=False)

    class Meta:
        ref_name = "InventoryExpiryAction"


class ExpiryResultSerializer(serializers.Serializer):
    action = serializers.CharField()
    writeoff_id = serializers.IntegerField(allow_null=True)

    class Meta:
        ref_name = "InventoryExpiryResult"


class ExpiryActionView(MemberView):
    perm = OPERATE

    @extend_schema(request=ExpiryActionSerializer, responses=ExpiryResultSerializer)
    def post(self, request, company_id, pk):
        stock = (
            BatchStock.objects.filter(batch__company=self.company, pk=pk)
            .select_related("branch", "batch__product")
            .first()
        )
        if stock is None or (self.mine is not None and stock.branch_id not in self.mine):
            raise NotFound
        serializer = ExpiryActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        batch = stock.batch
        if data["action"] == "on_shelf":
            services._audit(
                InventoryAction.EXPIRY_CHECKED,
                self.company.pk,
                self.membership,
                batch,
                branch=stock.branch.name,
                series=batch.series,
                quantity=str(stock.quantity),
            )
            return Response(
                ExpiryResultSerializer({"action": "on_shelf", "writeoff_id": None}).data
            )
        if stock.quantity <= 0:
            raise ValidationError({"action": [_("None of this series is here any more.")]})
        today = engine.local_today(self.company)
        reason = data.get("reason") or (
            WriteOff.Reason.EXPIRED if engine.is_expired(batch, today) else WriteOff.Reason.OTHER
        )
        files = []
        if data.get("photo"):
            files.append((uploads.sanitize_image(data["photo"]), WriteOffFile.Kind.PHOTO))
        writeoff = services.propose_writeoff(
            self.company,
            by=self.membership,
            branch=stock.branch,
            reason=reason,
            lines=[{"batch": batch, "quantity": stock.quantity}],
            files=files,
        )
        return Response(
            ExpiryResultSerializer({"action": "propose_writeoff", "writeoff_id": writeoff.pk}).data
        )


# Transfers -------------------------------------------------------------------------------------


class AppTransferSerializer(serializers.Serializer):
    transfer = s.TransferSerializer()
    lines = s.TransferLineSerializer(many=True)

    class Meta:
        ref_name = "InventoryAppTransfer"


def _app_transfer(transfer) -> dict:
    lines = list(transfer.lines.select_related("product", "batch"))
    return {
        "transfer": shapes.transfer_out(transfer, lines_count=len(lines)),
        "lines": [shapes.transfer_line_out(line) for line in lines],
    }


class IncomingView(MemberView):
    perm = OPERATE

    def rows(self):
        rows = StockTransfer.objects.for_company(self.company).select_related(
            "from_branch", "to_branch", "sent_by", "received_by"
        )
        if self.mine is not None:
            rows = rows.filter(to_branch_id__in=self.mine)
        return rows

    @extend_schema(responses=AppTransferSerializer(many=True))
    def get(self, request, company_id):
        rows = self.rows().filter(status=StockTransfer.Status.SENT).order_by("-sent_at")
        return Response(AppTransferSerializer([_app_transfer(row) for row in rows], many=True).data)


class ReceiveView(IncomingView):
    http_method_names = ["post", "options"]

    @extend_schema(request=s.ReceiveSerializer, responses=AppTransferSerializer)
    def post(self, request, company_id, pk):
        transfer = self.rows().filter(pk=pk).first()
        if transfer is None:
            raise NotFound
        serializer = s.ReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.receive_transfer(
            transfer,
            by=self.membership,
            received={
                row["line"]: row["quantity"] for row in serializer.validated_data.get("lines", [])
            },
        )
        return Response(AppTransferSerializer(_app_transfer(self.rows().get(pk=pk))).data)


# Defektura and prescriptions ----------------------------------------------------------------------


class AppRequestSerializer(serializers.Serializer):
    product = serializers.IntegerField(allow_null=True, required=False)
    name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    packs = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0, required=False)
    customer_phone = serializers.CharField(max_length=16, allow_blank=True, required=False)

    class Meta:
        ref_name = "InventoryAppRequest"


class DefekturaView(MemberView):
    perm = OPERATE

    @extend_schema(request=AppRequestSerializer, responses={201: s.RequestSerializer})
    def post(self, request, company_id):
        serializer = AppRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row = services.add_request(
            self.my_branch(),
            by=self.membership,
            product=self.product(data["product"]) if data.get("product") else None,
            name=data.get("name", ""),
            packs=data.get("packs") or 1,
            customer_phone=data.get("customer_phone", ""),
        )
        row = type(row).objects.select_related("branch", "product", "requested_by").get(pk=row.pk)
        return Response(s.RequestSerializer(shapes.request_out(row)).data, status=201)


class AppRxSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    batch = serializers.IntegerField(allow_null=True, required=False)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)
    prescription_number = serializers.CharField(max_length=40, allow_blank=True, required=False)
    prescribed_on = serializers.DateField(allow_null=True, required=False)
    prescriber = serializers.CharField(max_length=120, allow_blank=True, required=False)
    facility = serializers.CharField(max_length=120, allow_blank=True, required=False)
    rx_kind = serializers.ChoiceField(choices=RxRecord.RxKind.choices, required=False)
    status = serializers.ChoiceField(choices=RxRecord.Status.choices, required=False)
    invalid_reason = serializers.CharField(max_length=200, allow_blank=True, required=False)
    e_prescription_id = serializers.CharField(max_length=64, allow_blank=True, required=False)
    photo = serializers.ImageField(required=False)

    class Meta:
        ref_name = "InventoryAppRx"


class RxView(MemberView):
    perm = OPERATE

    @extend_schema(request=AppRxSerializer, responses={201: s.RxRecordSerializer})
    def post(self, request, company_id):
        serializer = AppRxSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        product = self.product(data.pop("product"))
        batch = None
        if data.get("batch"):
            batch = StockBatch.objects.for_company(self.company).filter(pk=data["batch"]).first()
        data.pop("batch", None)
        if data.get("photo"):
            data["photo"] = uploads.sanitize_image(data["photo"])
        record = services.record_rx(
            by=self.membership,
            branch=self.my_branch(),
            product=product,
            quantity=data.pop("quantity"),
            batch=batch,
            **data,
        )
        if record is None:
            raise ValidationError(
                {"product": [_("The prescription log is off, or this item needs no prescription.")]}
            )
        record = (
            type(record)
            .objects.select_related("branch", "product", "batch", "recorded_by")
            .get(pk=record.pk)
        )
        return Response(
            s.RxRecordSerializer(
                shapes.rx_out(record, settings=conf.get_settings(self.company))
            ).data,
            status=201,
        )
