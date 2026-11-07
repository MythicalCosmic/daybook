"""Shapes of the stock API (money as strings, quantities in parts as strings, days as
YYYY-MM-DD in company time).

Cost fields (a batch's cost, a receipt's total, values at cost) are left out of the answer for
anyone without finance.view (the field rule of §5): their serializer fields are optional.
"""

from rest_framework import serializers

from apps.core.models import Language
from apps.inventory.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    MissingRequest,
    Product,
    ProductCode,
    RecallNotice,
    RxRecord,
    StockBatch,
    StockCount,
    StockMovement,
    StockTransfer,
    SupplierProfile,
    WriteOff,
    WriteOffFile,
)

COST = {"required": False}
IMPORT_ACTIONS = [("create", "create"), ("update", "update"), ("skip", "skip")]


class Shape(serializers.Serializer):
    """An answer shape: an optional field the dict doesn't carry is left out of the answer (a
    cost field without finance.view), even when its value could be null."""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if isinstance(instance, dict):
            for name, field in self.fields.items():
                if not field.required and field.source not in instance:
                    data.pop(name, None)
        return data


def Money(**kwargs):
    return serializers.DecimalField(
        max_digits=18, decimal_places=2, coerce_to_string=True, **kwargs
    )


def Qty(**kwargs):
    return serializers.DecimalField(
        max_digits=14, decimal_places=3, coerce_to_string=True, **kwargs
    )


def Percent(**kwargs):
    return serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=True, **kwargs)


class Ref(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "InventoryRef"


class BranchRef(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()

    class Meta:
        ref_name = "InventoryBranchRef"


class PersonRef(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "InventoryPersonRef"


# Settings ---------------------------------------------------------------------------------------


class RxKeepSerializer(serializers.Serializer):
    regular = serializers.IntegerField(min_value=0, max_value=240)
    benefit = serializers.IntegerField(min_value=0, max_value=240)
    narcotic = serializers.IntegerField(min_value=0, max_value=240)
    psychotropic = serializers.IntegerField(min_value=0, max_value=240)
    listed = serializers.IntegerField(min_value=0, max_value=240)

    class Meta:
        ref_name = "InventoryRxKeep"


class SettingsSerializer(serializers.Serializer):
    expiry_steps = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=730), max_length=6
    )
    min_shelf_days = serializers.IntegerField(min_value=0, max_value=3650)
    fefo_strict = serializers.BooleanField()
    allow_negative = serializers.BooleanField()
    default_markup_percent = Percent(min_value=0, max_value=500)
    rx_max_markup_percent = Percent(min_value=0, max_value=500)
    social_max_markup_percent = Percent(min_value=0, max_value=500)
    cap_enforced = serializers.BooleanField()
    price_rounding = Money(min_value=0, max_value=1_000_000)
    price_jump_percent = Percent(min_value=0, max_value=500)
    writeoff_approval = serializers.BooleanField()
    show_other_branches = serializers.BooleanField()
    camera_scanning = serializers.BooleanField()
    rx_log = serializers.BooleanField()
    count_tolerance = Money(min_value=0)
    destroy_within_days = serializers.IntegerField(min_value=1, max_value=365)
    destroy_commission_min = serializers.IntegerField(min_value=1, max_value=20)
    rx_keep_months = RxKeepSerializer()
    rx_destroy_commission_min = serializers.IntegerField(min_value=1, max_value=20)
    narcotic_rx_valid_days = serializers.IntegerField(min_value=1, max_value=365)
    psychotropic_rx_valid_months = serializers.IntegerField(min_value=1, max_value=24)
    psychotropic_stock_months = serializers.IntegerField(min_value=1, max_value=24)
    controlled_close_day = serializers.IntegerField(min_value=1, max_value=28)
    controlled_report_days = serializers.IntegerField(min_value=1, max_value=60)

    class Meta:
        ref_name = "InventorySettings"


# The catalogue ------------------------------------------------------------------------------------


class CategorySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100)
    parent = serializers.IntegerField(allow_null=True, required=False)
    order = serializers.IntegerField(min_value=0, required=False)
    products = serializers.IntegerField(read_only=True)

    class Meta:
        ref_name = "InventoryCategory"


class ManufacturerSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=120)
    country = serializers.CharField(max_length=2, allow_blank=True, required=False)

    class Meta:
        ref_name = "InventoryManufacturer"


class CodeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    kind = serializers.ChoiceField(choices=ProductCode.Kind.choices)
    code = serializers.CharField(max_length=64)
    supplier = Ref(read_only=True, allow_null=True)
    supplier_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        ref_name = "InventoryProductCode"


PRODUCT_WRITE = (
    "name",
    "trade_name",
    "inn",
    "kind",
    "dosage_form",
    "strength",
    "units_per_pack",
    "part_label",
    "rx_required",
    "e_rx_group",
    "control_class",
    "restricted_channel",
    "storage",
    "light_sensitive",
    "barcode",
    "sku",
    "mxik_code",
    "package_code",
    "registration_number",
    "registration_until",
    "marking_required",
    "vat_percent",
    "socially_significant",
    "mandatory_list",
    "reference_price",
    "reference_price_on",
    "sale_price",
    "part_price",
    "track_stock",
    "is_active",
)


class ProductWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    trade_name = serializers.CharField(max_length=120, allow_blank=True, required=False)
    inn = serializers.CharField(max_length=200, allow_blank=True, required=False)
    kind = serializers.ChoiceField(choices=Product.Kind.choices, required=False)
    dosage_form = serializers.ChoiceField(
        choices=Product.DosageForm.choices, allow_blank=True, required=False
    )
    strength = serializers.CharField(max_length=40, allow_blank=True, required=False)
    units_per_pack = serializers.IntegerField(min_value=1, max_value=1000, required=False)
    part_label = serializers.CharField(max_length=12, allow_blank=True, required=False)
    manufacturer = serializers.IntegerField(allow_null=True, required=False)
    category = serializers.IntegerField(allow_null=True, required=False)
    rx_required = serializers.BooleanField(required=False)
    e_rx_group = serializers.BooleanField(required=False)
    control_class = serializers.ChoiceField(choices=Product.ControlClass.choices, required=False)
    restricted_channel = serializers.BooleanField(required=False)
    storage = serializers.ChoiceField(choices=Product.Storage.choices, required=False)
    light_sensitive = serializers.BooleanField(required=False)
    barcode = serializers.CharField(max_length=32, allow_blank=True, required=False)
    sku = serializers.CharField(max_length=64, allow_blank=True, required=False)
    mxik_code = serializers.CharField(max_length=17, allow_blank=True, required=False)
    package_code = serializers.CharField(max_length=20, allow_blank=True, required=False)
    registration_number = serializers.CharField(max_length=40, allow_blank=True, required=False)
    registration_until = serializers.DateField(allow_null=True, required=False)
    marking_required = serializers.BooleanField(required=False)
    vat_percent = serializers.DecimalField(
        max_digits=4, decimal_places=2, allow_null=True, required=False, min_value=0
    )
    socially_significant = serializers.BooleanField(required=False)
    mandatory_list = serializers.BooleanField(required=False)
    reference_price = Money(allow_null=True, required=False, min_value=0)
    reference_price_on = serializers.DateField(allow_null=True, required=False)
    sale_price = Money(required=False, min_value=0)
    part_price = Money(allow_null=True, required=False, min_value=0)
    track_stock = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)

    class Meta:
        ref_name = "InventoryProductWrite"


class ProductSerializer(Shape):
    id = serializers.IntegerField()
    name = serializers.CharField()
    trade_name = serializers.CharField()
    inn = serializers.CharField()
    kind = serializers.ChoiceField(choices=Product.Kind.choices)
    dosage_form = serializers.CharField()
    strength = serializers.CharField()
    units_per_pack = serializers.IntegerField()
    part_label = serializers.CharField()
    manufacturer = Ref(allow_null=True)
    category = Ref(allow_null=True)
    rx_required = serializers.BooleanField()
    e_rx_group = serializers.BooleanField()
    control_class = serializers.ChoiceField(choices=Product.ControlClass.choices)
    restricted_channel = serializers.BooleanField()
    storage = serializers.ChoiceField(choices=Product.Storage.choices)
    light_sensitive = serializers.BooleanField()
    barcode = serializers.CharField()
    sku = serializers.CharField()
    mxik_code = serializers.CharField()
    package_code = serializers.CharField()
    registration_number = serializers.CharField()
    registration_until = serializers.DateField(allow_null=True)
    marking_required = serializers.BooleanField()
    vat_percent = serializers.CharField(allow_null=True)
    socially_significant = serializers.BooleanField()
    mandatory_list = serializers.BooleanField()
    reference_price = Money(allow_null=True)
    reference_price_on = serializers.DateField(allow_null=True)
    sale_price = Money()
    part_price = Money(allow_null=True)
    effective_part_price = Money()
    cost_price = Money(allow_null=True, **COST)
    track_stock = serializers.BooleanField()
    is_active = serializers.BooleanField()
    quantity = Qty(allow_null=True)
    nearest_expiry = serializers.DateField(allow_null=True)

    class Meta:
        ref_name = "InventoryProduct"


class ProductPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = ProductSerializer(many=True)

    class Meta:
        ref_name = "InventoryProductPage"


class BranchQuantitySerializer(serializers.Serializer):
    branch_id = serializers.IntegerField()
    branch = serializers.CharField()
    quantity = Qty()
    shortfall = Qty()
    min_qty = Qty(allow_null=True)
    max_qty = Qty(allow_null=True)

    class Meta:
        ref_name = "InventoryBranchQuantity"


class AnalogSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    trade_name = serializers.CharField()
    inn = serializers.CharField()
    dosage_form = serializers.CharField()
    strength = serializers.CharField()
    manufacturer = serializers.CharField()
    units_per_pack = serializers.IntegerField()
    part_label = serializers.CharField()
    rx_required = serializers.BooleanField()
    sale_price = Money()
    quantity = Qty()

    class Meta:
        ref_name = "InventoryAnalog"


class ProductPageDetailSerializer(serializers.Serializer):
    product = ProductSerializer()
    branches = BranchQuantitySerializer(many=True)
    codes = CodeSerializer(many=True)
    analogs = AnalogSerializer(many=True)
    price_cap = Money(allow_null=True)

    class Meta:
        ref_name = "InventoryProductDetail"


class MergeSerializer(serializers.Serializer):
    other = serializers.IntegerField()

    class Meta:
        ref_name = "InventoryMerge"


class ImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    mapping = serializers.JSONField(required=False)
    dry_run = serializers.BooleanField(default=True)

    class Meta:
        ref_name = "InventoryImport"


class ImportRowSerializer(serializers.Serializer):
    row = serializers.IntegerField()
    action = serializers.ChoiceField(choices=IMPORT_ACTIONS)
    name = serializers.CharField()
    product_id = serializers.IntegerField(allow_null=True)
    errors = serializers.ListField(child=serializers.CharField())

    class Meta:
        ref_name = "InventoryImportRow"


class ImportResultSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField()
    columns = serializers.ListField(child=serializers.CharField())
    mapping = serializers.DictField(child=serializers.CharField())
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    skipped = serializers.IntegerField()
    rows = ImportRowSerializer(many=True)

    class Meta:
        ref_name = "InventoryImportResult"


# Distributors -------------------------------------------------------------------------------------


class SupplierSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text="The counterparty's id.")
    name = serializers.CharField(max_length=200)
    phone = serializers.CharField(read_only=True)
    tin = serializers.CharField(read_only=True)
    payment_terms_days = serializers.IntegerField(
        min_value=0, max_value=365, allow_null=True, required=False
    )
    official_dealer = serializers.BooleanField(required=False)
    delivery_days = serializers.IntegerField(min_value=0, max_value=60, required=False)
    min_order = Money(allow_null=True, required=False, min_value=0)
    order_channel = serializers.ChoiceField(choices=SupplierProfile.Channel.choices, required=False)
    telegram_username = serializers.CharField(max_length=64, allow_blank=True, required=False)
    notes = serializers.CharField(allow_blank=True, required=False)
    receipts = serializers.IntegerField(read_only=True)

    class Meta:
        ref_name = "InventorySupplier"


# Stock ------------------------------------------------------------------------------------------


class LevelSerializer(Shape):
    id = serializers.IntegerField()
    branch = BranchRef()
    product = Ref()
    inn = serializers.CharField()
    rx_required = serializers.BooleanField()
    control_class = serializers.CharField()
    storage = serializers.CharField()
    mandatory_list = serializers.BooleanField()
    units_per_pack = serializers.IntegerField()
    part_label = serializers.CharField()
    quantity = Qty()
    sellable = Qty()
    shortfall = Qty()
    min_qty = Qty(allow_null=True)
    max_qty = Qty(allow_null=True)
    low = serializers.BooleanField()
    nearest_expiry = serializers.DateField(allow_null=True)
    sale_price = Money()
    value = Money(**COST)

    class Meta:
        ref_name = "InventoryLevel"


class LevelLimitsSerializer(serializers.Serializer):
    min_qty = Qty(allow_null=True, min_value=0)
    max_qty = Qty(allow_null=True, min_value=0)

    class Meta:
        ref_name = "InventoryLevelLimits"


class BatchSerializer(Shape):
    id = serializers.IntegerField(help_text="The batch's stock row at the branch.")
    batch_id = serializers.IntegerField()
    branch = BranchRef()
    product = Ref()
    series = serializers.CharField()
    expires_on = serializers.DateField()
    made_on = serializers.DateField(allow_null=True)
    days_left = serializers.IntegerField()
    expired = serializers.BooleanField()
    status = serializers.ChoiceField(choices=StockBatch.Status.choices)
    supplier = Ref(allow_null=True)
    quantity = Qty()
    retail_price = Money()
    part_price = Money()
    price_cap = Money(allow_null=True)
    unit_cost = Money(**COST)
    value = Money(**COST)
    retail_value = Money()
    receipt_id = serializers.IntegerField(allow_null=True)

    class Meta:
        ref_name = "InventoryBatch"


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)

    class Meta:
        ref_name = "InventoryReason"


class OptionalReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, allow_blank=True, required=False)

    class Meta:
        ref_name = "InventoryOptionalReason"


class PriceSerializer(serializers.Serializer):
    price = Money(min_value=0)

    class Meta:
        ref_name = "InventoryPrice"


class OpeningSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
    product = serializers.IntegerField()
    series = serializers.CharField(max_length=40)
    expires_on = serializers.DateField()
    made_on = serializers.DateField(allow_null=True, required=False)
    packs = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0)
    parts = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=0, required=False, default=0
    )
    unit_cost = Money(min_value=0)
    retail_price = Money(allow_null=True, required=False, min_value=0)

    class Meta:
        ref_name = "InventoryOpening"


class ExpiryRowSerializer(Shape):
    id = serializers.IntegerField()
    batch_id = serializers.IntegerField()
    branch_id = serializers.IntegerField()
    branch = serializers.CharField()
    product_id = serializers.IntegerField()
    product = serializers.CharField()
    series = serializers.CharField()
    expires_on = serializers.DateField()
    days_left = serializers.IntegerField()
    expired = serializers.BooleanField()
    status = serializers.CharField()
    quantity = Qty()
    units_per_pack = serializers.IntegerField()
    value = Money(**COST)
    retail_value = Money()

    class Meta:
        ref_name = "InventoryExpiryRow"


class ExpiryBucketSerializer(Shape):
    key = serializers.CharField()
    days = serializers.IntegerField()
    count = serializers.IntegerField()
    value = Money(**COST)
    retail_value = Money()
    rows = ExpiryRowSerializer(many=True)

    class Meta:
        ref_name = "InventoryExpiryBucket"


class ExpiryBoardSerializer(serializers.Serializer):
    as_of = serializers.DateField()
    within = serializers.IntegerField()
    buckets = ExpiryBucketSerializer(many=True)

    class Meta:
        ref_name = "InventoryExpiryBoard"


class MovementSerializer(Shape):
    id = serializers.IntegerField()
    at = serializers.DateTimeField()
    branch = BranchRef()
    product = Ref()
    series = serializers.CharField(allow_null=True)
    kind = serializers.ChoiceField(choices=StockMovement.Kind.choices)
    quantity = Qty()
    unit_cost = Money(allow_null=True, **COST)
    document_type = serializers.CharField()
    document_id = serializers.IntegerField(allow_null=True)
    reason = serializers.CharField()
    by = PersonRef(allow_null=True)

    class Meta:
        ref_name = "InventoryMovement"


class SummarySerializer(Shape):
    products = serializers.IntegerField()
    low = serializers.IntegerField()
    negative = serializers.IntegerField()
    expiring_30d = serializers.IntegerField()
    expiring_30d_retail = Money()
    expiring_30d_value = Money(**COST)
    expired = serializers.IntegerField()
    expired_value = Money(**COST)
    stock_value = Money(**COST)
    stock_retail_value = Money()
    receipts_to_post = serializers.IntegerField()
    drafts = serializers.IntegerField()
    writeoffs_to_approve = serializers.IntegerField()
    transfers_disputed = serializers.IntegerField()
    transfers_incoming = serializers.IntegerField()
    recalls_open = serializers.IntegerField()
    mandatory_missing = serializers.IntegerField()
    controlled_branches = serializers.IntegerField()
    estimate = serializers.BooleanField(
        help_text="True until sales lines flow in: stock moves only by documents."
    )

    class Meta:
        ref_name = "InventorySummary"


# Receipts --------------------------------------------------------------------------------------


class ReceiptLineWriteSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    series = serializers.CharField(max_length=40)
    expires_on = serializers.DateField()
    made_on = serializers.DateField(allow_null=True, required=False)
    packs = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0)
    unit_cost = Money(min_value=0)
    vat_percent = serializers.DecimalField(
        max_digits=4, decimal_places=2, allow_null=True, required=False, min_value=0
    )
    retail_price = Money(allow_null=True, required=False, min_value=0)
    supplier_rx = serializers.BooleanField(allow_null=True, required=False)

    class Meta:
        ref_name = "InventoryReceiptLineWrite"


class ReceiptLineSerializer(Shape):
    id = serializers.IntegerField()
    product = Ref()
    units_per_pack = serializers.IntegerField()
    rx_required = serializers.BooleanField()
    control_class = serializers.CharField()
    series = serializers.CharField()
    expires_on = serializers.DateField()
    made_on = serializers.DateField(allow_null=True)
    packs = Qty()
    quantity = Qty()
    vat_percent = serializers.CharField(allow_null=True)
    retail_price = Money(allow_null=True)
    price_cap = Money(allow_null=True)
    supplier_rx = serializers.BooleanField(allow_null=True)
    warnings = serializers.ListField(
        child=serializers.ChoiceField(choices=GoodsReceiptLine.Warning.choices)
    )
    unit_cost = Money(**COST)
    total = Money(**COST)
    batch_id = serializers.IntegerField(allow_null=True)

    class Meta:
        ref_name = "InventoryReceiptLine"


class ReceiptWriteSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
    supplier = serializers.IntegerField()
    supplier_invoice_number = serializers.CharField(max_length=40, allow_blank=True, required=False)
    supplier_invoice_date = serializers.DateField()
    currency = serializers.CharField(max_length=3, required=False)
    due_on = serializers.DateField(allow_null=True, required=False)
    note = serializers.CharField(allow_blank=True, required=False)
    e_invoice_ref = serializers.CharField(max_length=64, allow_blank=True, required=False)
    lines = ReceiptLineWriteSerializer(many=True, required=False)

    class Meta:
        ref_name = "InventoryReceiptWrite"


class ReceiptSerializer(Shape):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=GoodsReceipt.Status.choices)
    branch = BranchRef()
    supplier = Ref()
    supplier_invoice_number = serializers.CharField()
    supplier_invoice_date = serializers.DateField()
    currency = serializers.CharField()
    due_on = serializers.DateField(allow_null=True)
    note = serializers.CharField()
    e_invoice_ref = serializers.CharField()
    lines_count = serializers.IntegerField()
    warnings = serializers.ListField(child=serializers.CharField())
    received_by = PersonRef(allow_null=True)
    posted_by = PersonRef(allow_null=True)
    submitted_at = serializers.DateTimeField(allow_null=True)
    posted_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    file_url = serializers.CharField(allow_null=True)
    total = Money(**COST)
    vat_total = Money(**COST)
    debt_id = serializers.IntegerField(allow_null=True, **COST)
    debt_status = serializers.CharField(allow_null=True, **COST)
    debt_paid = Money(allow_null=True, **COST)
    void_reason = serializers.CharField()

    class Meta:
        ref_name = "InventoryReceipt"


class ReceiptDetailSerializer(serializers.Serializer):
    receipt = ReceiptSerializer()
    lines = ReceiptLineSerializer(many=True)

    class Meta:
        ref_name = "InventoryReceiptDetail"


LINE_IMPORT_ACTIONS = [("add", "add"), ("unmatched", "unmatched"), ("skip", "skip")]


class LineImportRowSerializer(serializers.Serializer):
    row = serializers.IntegerField()
    action = serializers.ChoiceField(choices=LINE_IMPORT_ACTIONS)
    name = serializers.CharField()
    product_id = serializers.IntegerField(allow_null=True)
    errors = serializers.ListField(child=serializers.CharField())

    class Meta:
        ref_name = "InventoryLineImportRow"


class LineImportResultSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField()
    columns = serializers.ListField(child=serializers.CharField())
    mapping = serializers.DictField(child=serializers.CharField())
    added = serializers.IntegerField()
    unmatched = serializers.IntegerField()
    skipped = serializers.IntegerField()
    rows = LineImportRowSerializer(many=True)

    class Meta:
        ref_name = "InventoryLineImportResult"


class ReceiptFileSerializer(serializers.Serializer):
    file = serializers.FileField()

    class Meta:
        ref_name = "InventoryReceiptFile"


# Transfers -------------------------------------------------------------------------------------


class TransferLineWriteSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    batch = serializers.IntegerField(allow_null=True, required=False)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)

    class Meta:
        ref_name = "InventoryTransferLineWrite"


class TransferWriteSerializer(serializers.Serializer):
    from_branch = serializers.IntegerField()
    to_branch = serializers.IntegerField()
    note = serializers.CharField(allow_blank=True, required=False)
    lines = TransferLineWriteSerializer(many=True)
    send = serializers.BooleanField(default=False)

    class Meta:
        ref_name = "InventoryTransferWrite"


class TransferLineSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    product = Ref()
    units_per_pack = serializers.IntegerField()
    batch_id = serializers.IntegerField(allow_null=True)
    series = serializers.CharField(allow_null=True)
    expires_on = serializers.DateField(allow_null=True)
    quantity_sent = Qty()
    quantity_received = Qty(allow_null=True)

    class Meta:
        ref_name = "InventoryTransferLine"


class TransferSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=StockTransfer.Status.choices)
    from_branch = BranchRef()
    to_branch = BranchRef()
    note = serializers.CharField()
    lines_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    sent_at = serializers.DateTimeField(allow_null=True)
    sent_by = PersonRef(allow_null=True)
    received_at = serializers.DateTimeField(allow_null=True)
    received_by = PersonRef(allow_null=True)
    resolution = serializers.CharField()
    resolved_at = serializers.DateTimeField(allow_null=True)
    void_reason = serializers.CharField()

    class Meta:
        ref_name = "InventoryTransfer"


class TransferDetailSerializer(serializers.Serializer):
    transfer = TransferSerializer()
    lines = TransferLineSerializer(many=True)

    class Meta:
        ref_name = "InventoryTransferDetail"


class ReceivedLineSerializer(serializers.Serializer):
    line = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)

    class Meta:
        ref_name = "InventoryReceivedLine"


class ReceiveSerializer(serializers.Serializer):
    lines = ReceivedLineSerializer(many=True, required=False)

    class Meta:
        ref_name = "InventoryReceive"


class ResolveSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=StockTransfer.Resolution.choices)
    note = serializers.CharField(allow_blank=True, required=False)

    class Meta:
        ref_name = "InventoryResolve"


# Write-offs -------------------------------------------------------------------------------------


class WriteOffLineWriteSerializer(serializers.Serializer):
    batch = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)

    class Meta:
        ref_name = "InventoryWriteOffLineWrite"


class WriteOffWriteSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
    reason = serializers.ChoiceField(choices=WriteOff.Reason.choices)
    note = serializers.CharField(allow_blank=True, required=False)
    recall = serializers.IntegerField(allow_null=True, required=False)
    lines = WriteOffLineWriteSerializer(many=True)

    class Meta:
        ref_name = "InventoryWriteOffWrite"


class WriteOffLineSerializer(Shape):
    id = serializers.IntegerField()
    batch_id = serializers.IntegerField()
    product = Ref()
    units_per_pack = serializers.IntegerField()
    series = serializers.CharField()
    expires_on = serializers.DateField()
    quantity = Qty()
    unit_cost = Money(**COST)
    value = Money(**COST)

    class Meta:
        ref_name = "InventoryWriteOffLine"


class WriteOffFileOutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=WriteOffFile.Kind.choices)
    url = serializers.CharField()
    at = serializers.DateTimeField()

    class Meta:
        ref_name = "InventoryWriteOffFileOut"


class CommissionMemberSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    organisation = serializers.CharField(max_length=150, allow_blank=True, required=False)
    role = serializers.CharField(max_length=100, allow_blank=True, required=False)

    class Meta:
        ref_name = "InventoryCommissionMember"


class WriteOffSerializer(Shape):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.ChoiceField(choices=WriteOff.Status.choices)
    reason = serializers.ChoiceField(choices=WriteOff.Reason.choices)
    branch = BranchRef()
    note = serializers.CharField()
    lines_count = serializers.IntegerField()
    needs_destruction = serializers.BooleanField()
    proposed_by = PersonRef(allow_null=True)
    approved_by = PersonRef(allow_null=True)
    approved_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    destroy_by = serializers.DateField(allow_null=True)
    responsible = serializers.CharField()
    order_number = serializers.CharField()
    commission = CommissionMemberSerializer(many=True)
    method = serializers.CharField()
    place = serializers.CharField()
    destroyed_at = serializers.DateTimeField(allow_null=True)
    sent_to = serializers.ListField(child=serializers.CharField())
    act_url = serializers.CharField(allow_null=True)
    recall_id = serializers.IntegerField(allow_null=True)
    transfer_id = serializers.IntegerField(allow_null=True)
    value = Money(**COST)
    void_reason = serializers.CharField()

    class Meta:
        ref_name = "InventoryWriteOff"


class WriteOffDetailSerializer(serializers.Serializer):
    writeoff = WriteOffSerializer()
    lines = WriteOffLineSerializer(many=True)
    files = WriteOffFileOutSerializer(many=True)
    commission_min = serializers.IntegerField()

    class Meta:
        ref_name = "InventoryWriteOffDetail"


class DestroyedSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=WriteOff.Method.choices)
    place = serializers.CharField(max_length=200)
    destroyed_at = serializers.DateTimeField()
    responsible = serializers.CharField(max_length=150)
    order_number = serializers.CharField(max_length=40)
    commission = CommissionMemberSerializer(many=True)
    sent_to = serializers.ListField(
        child=serializers.CharField(max_length=150), required=False, default=list
    )

    class Meta:
        ref_name = "InventoryDestroyed"


class WriteOffUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    kind = serializers.ChoiceField(choices=WriteOffFile.Kind.choices, default="photo")

    class Meta:
        ref_name = "InventoryWriteOffUpload"


# Counts -------------------------------------------------------------------------------------


class CountWriteSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=StockCount.Kind.choices, default="partial")
    category = serializers.IntegerField(allow_null=True, required=False)

    class Meta:
        ref_name = "InventoryCountWrite"


class CountLineSerializer(Shape):
    id = serializers.IntegerField()
    product = Ref()
    units_per_pack = serializers.IntegerField()
    part_label = serializers.CharField()
    batch_id = serializers.IntegerField(allow_null=True)
    series = serializers.CharField()
    expires_on = serializers.DateField(allow_null=True)
    counted = Qty(allow_null=True)
    expected = Qty(required=False, help_text="Only once the count is counted, never while open.")
    difference = Qty(allow_null=True, required=False)
    value_difference = Money(required=False)

    class Meta:
        ref_name = "InventoryCountLine"


class CountSerializer(Shape):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=StockCount.Kind.choices)
    status = serializers.ChoiceField(choices=StockCount.Status.choices)
    branch = BranchRef()
    category = Ref(allow_null=True)
    lines_count = serializers.IntegerField()
    counted_count = serializers.IntegerField()
    started_by = PersonRef(allow_null=True)
    created_at = serializers.DateTimeField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    applied_at = serializers.DateTimeField(allow_null=True)
    value_difference = Money(allow_null=True, **COST)

    class Meta:
        ref_name = "InventoryCount"


class CountDetailSerializer(serializers.Serializer):
    count = CountSerializer()
    lines = CountLineSerializer(many=True)

    class Meta:
        ref_name = "InventoryCountDetail"


class CountedLineSerializer(serializers.Serializer):
    line = serializers.IntegerField()
    counted = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=0, allow_null=True
    )

    class Meta:
        ref_name = "InventoryCountedLine"


class CountedSerializer(serializers.Serializer):
    lines = CountedLineSerializer(many=True)

    class Meta:
        ref_name = "InventoryCounted"


class FoundSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    series = serializers.CharField(max_length=40)
    expires_on = serializers.DateField()
    counted = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)

    class Meta:
        ref_name = "InventoryFound"


# Recalls ----------------------------------------------------------------------------------------


class RecallWriteSerializer(serializers.Serializer):
    product = serializers.IntegerField(allow_null=True, required=False)
    inn_or_name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    series = serializers.CharField(max_length=40)
    reason = serializers.CharField(max_length=200)
    source = serializers.CharField(max_length=200)
    received_on = serializers.DateField()
    file = serializers.FileField(required=False)

    class Meta:
        ref_name = "InventoryRecallWrite"


class FoundRowSerializer(serializers.Serializer):
    branch_id = serializers.IntegerField()
    branch = serializers.CharField()
    batch_id = serializers.IntegerField()
    product_id = serializers.IntegerField()
    product = serializers.CharField()
    series = serializers.CharField()
    quantity = serializers.CharField()
    task_id = serializers.IntegerField(allow_null=True)
    left = Qty()
    units_per_pack = serializers.IntegerField()
    part_label = serializers.CharField()

    class Meta:
        ref_name = "InventoryFoundRow"


class RecallSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    product = Ref(allow_null=True)
    inn_or_name = serializers.CharField()
    series = serializers.CharField()
    reason = serializers.CharField()
    source = serializers.CharField()
    received_on = serializers.DateField()
    status = serializers.ChoiceField(choices=RecallNotice.Status.choices)
    found = FoundRowSerializer(many=True)
    left = Qty()
    file_url = serializers.CharField(allow_null=True)
    closed_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()

    class Meta:
        ref_name = "InventoryRecall"


# Pricing rules, defektura, prescriptions ---------------------------------------------------------


class PricingRuleSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    category = serializers.IntegerField(allow_null=True, required=False)
    category_name = serializers.CharField(read_only=True, allow_null=True)
    cost_from = Money(allow_null=True, required=False, min_value=0)
    cost_to = Money(allow_null=True, required=False, min_value=0)
    markup_percent = Percent(min_value=0, max_value=500)
    order = serializers.IntegerField(min_value=0, required=False)
    is_active = serializers.BooleanField(required=False)

    class Meta:
        ref_name = "InventoryPricingRule"


class PriceTagsSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
    products = serializers.ListField(
        child=serializers.IntegerField(), required=False, max_length=500
    )
    changed_since = serializers.DateField(
        required=False, help_text="Items whose price changed since this day (default: 7 days)."
    )
    language = serializers.ChoiceField(choices=Language.choices, required=False)

    class Meta:
        ref_name = "InventoryPriceTags"


class RequestSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    branch = serializers.IntegerField(write_only=True)
    branch_ref = BranchRef(read_only=True)
    product = serializers.IntegerField(allow_null=True, required=False, write_only=True)
    product_ref = Ref(read_only=True, allow_null=True)
    name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    packs = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=0, required=False, coerce_to_string=True
    )
    source = serializers.ChoiceField(choices=MissingRequest.Source.choices, read_only=True)
    status = serializers.ChoiceField(choices=MissingRequest.Status.choices, required=False)
    customer_phone = serializers.CharField(max_length=16, allow_blank=True, required=False)
    requested_at = serializers.DateTimeField(read_only=True)
    requested_by = PersonRef(read_only=True, allow_null=True)

    class Meta:
        ref_name = "InventoryRequest"


class RequestStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=MissingRequest.Status.choices)

    class Meta:
        ref_name = "InventoryRequestStatus"


class RxRecordSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    branch = BranchRef()
    product = Ref()
    series = serializers.CharField(allow_null=True)
    quantity = Qty()
    prescription_number = serializers.CharField()
    prescribed_on = serializers.DateField(allow_null=True)
    prescriber = serializers.CharField()
    facility = serializers.CharField()
    rx_kind = serializers.ChoiceField(choices=RxRecord.RxKind.choices)
    status = serializers.ChoiceField(choices=RxRecord.Status.choices)
    invalid_reason = serializers.CharField()
    facility_notified_at = serializers.DateTimeField(allow_null=True)
    e_prescription_id = serializers.CharField()
    keep_until = serializers.DateField()
    recorded_at = serializers.DateTimeField()
    recorded_by = PersonRef(allow_null=True)
    flags = serializers.ListField(child=serializers.CharField())

    class Meta:
        ref_name = "InventoryRxRecord"


class RxWriteSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
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

    class Meta:
        ref_name = "InventoryRxWrite"


# Journals ------------------------------------------------------------------------------------


class ControlledRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    product_id = serializers.IntegerField()
    product = serializers.CharField()
    inn = serializers.CharField()
    control_class = serializers.CharField()
    units_per_pack = serializers.IntegerField()
    opening = Qty()
    received = Qty()
    issued = Qty()
    written_off = Qty()
    adjusted = Qty()
    closing = Qty()
    unrecorded_issues = serializers.IntegerField()
    period_id = serializers.IntegerField(allow_null=True)
    counted = Qty(allow_null=True)
    difference = Qty(allow_null=True)
    closed_at = serializers.DateTimeField(allow_null=True)
    reported_on = serializers.DateField(allow_null=True)

    class Meta:
        ref_name = "InventoryControlledRow"


class ControlledRegisterSerializer(serializers.Serializer):
    branch = BranchRef()
    month = serializers.DateField()
    closed = serializers.BooleanField()
    close_by = serializers.DateField()
    rows = ControlledRowSerializer(many=True)
    branches = BranchRef(many=True, help_text="The licensed branches in scope.")

    class Meta:
        ref_name = "InventoryControlledRegister"


class CountedProductSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    counted = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)

    class Meta:
        ref_name = "InventoryCountedProduct"


class CloseMonthSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
    month = serializers.DateField()
    counted = CountedProductSerializer(many=True, required=False)
    note = serializers.CharField(allow_blank=True, required=False)

    class Meta:
        ref_name = "InventoryCloseMonth"


class ReportedSerializer(serializers.Serializer):
    reported_on = serializers.DateField()

    class Meta:
        ref_name = "InventoryReported"


class RxJournalSerializer(serializers.Serializer):
    branch = BranchRef()
    month = serializers.DateField()
    rows = RxRecordSerializer(many=True)

    class Meta:
        ref_name = "InventoryRxJournal"
