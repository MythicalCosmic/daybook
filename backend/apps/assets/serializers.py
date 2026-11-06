"""Shapes of the fixed assets API (money as strings, days as YYYY-MM-DD in company time)."""

from rest_framework import serializers

from apps.assets.models import (
    Asset,
    AssetCategory,
    AssetCount,
    AssetCountLine,
    AssetEvent,
    AssetFile,
    Method,
    StartRule,
)
from apps.core.files import signed_url
from apps.core.money import Currency

UPKEEP_KINDS = [
    ("service", "service"),
    ("verification", "verification"),
    ("warranty", "warranty"),
    ("insurance", "insurance"),
]
MONTH_STATES = [
    ("opening", "opening"),
    ("booked", "booked"),
    ("posted", "posted"),
    ("planned", "planned"),
]
REPORT_GROUPS = [("category", "category"), ("branch", "branch")]
WRITABLE_STATUSES = [
    (Asset.Status.IN_USE.value, Asset.Status.IN_USE.label),
    (Asset.Status.IN_STORAGE.value, Asset.Status.IN_STORAGE.label),
    (Asset.Status.REPAIR.value, Asset.Status.REPAIR.label),
]


Money = lambda **kwargs: serializers.DecimalField(  # noqa: E731
    max_digits=18, decimal_places=2, coerce_to_string=True, **kwargs
)


class Ref(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "AssetsRef"


def ref(item):
    if item is None:
        return None
    return {"id": item.pk, "name": str(getattr(item, "name", None) or item)}


# Settings and categories -------------------------------------------------------------------


class TaxGroupSerializer(serializers.Serializer):
    code = serializers.CharField()
    rate = serializers.CharField()
    label = serializers.CharField()


class SettingsSerializer(serializers.Serializer):
    start_rule = serializers.ChoiceField(choices=StartRule.choices)
    number_prefix = serializers.CharField(max_length=8)
    next_number = serializers.IntegerField(min_value=1)
    capitalization_threshold = Money(allow_null=True, required=False)
    replacement_inflation = serializers.DecimalField(max_digits=5, decimal_places=2)
    tax_book = serializers.BooleanField()
    remind_days = serializers.IntegerField(min_value=1, max_value=180)
    tax_groups = TaxGroupSerializer(many=True, read_only=True)
    locked_rule = serializers.BooleanField(read_only=True)

    class Meta:
        ref_name = "AssetsSettings"


class CategorySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100)
    kind = serializers.ChoiceField(choices=AssetCategory.Kind.choices, required=False)
    life_months = serializers.IntegerField(allow_null=True, required=False, min_value=1)
    method = serializers.ChoiceField(choices=Method.choices, required=False)
    salvage_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    tax_group = serializers.CharField(allow_blank=True, required=False, max_length=8)
    tax_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, allow_null=True, required=False
    )
    service_months = serializers.IntegerField(allow_null=True, required=False)
    verify_months = serializers.IntegerField(allow_null=True, required=False)
    icon = serializers.CharField(allow_blank=True, required=False, max_length=40)
    order = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)
    system_code = serializers.CharField(read_only=True)
    assets = serializers.IntegerField(read_only=True)

    class Meta:
        ref_name = "AssetsCategory"


# The register --------------------------------------------------------------------------------


class DueSerializer(serializers.Serializer):
    what = serializers.ChoiceField(choices=UPKEEP_KINDS)
    day = serializers.DateField()


class AssetRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    name = serializers.CharField()
    model = serializers.CharField()
    category = Ref()
    category_kind = serializers.ChoiceField(choices=AssetCategory.Kind.choices)
    icon = serializers.CharField()
    branch = Ref(allow_null=True)
    status = serializers.ChoiceField(choices=Asset.Status.choices)
    condition = serializers.ChoiceField(choices=Asset.Condition.choices)
    cost = Money()
    accumulated = Money()
    book_value = Money()
    monthly = Money()
    in_service_on = serializers.DateField(allow_null=True)
    custodian = Ref(allow_null=True)
    next_due = DueSerializer(allow_null=True)
    photo_url = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "AssetsRow"


def photo_of(asset: Asset, user) -> str | None:
    photo = next((row for row in asset.files.all() if row.kind == AssetFile.Kind.PHOTO), None)
    if photo is None or not photo.file:
        return None
    return signed_url(
        photo.file, user=user, company_id=asset.company_id, check=f"assets.file:{photo.pk}"
    )


def row_of(asset: Asset, *, user, today, next_due) -> dict:
    due = next_due(asset, today)
    return {
        "id": asset.pk,
        "number": asset.number,
        "name": asset.name,
        "model": asset.model,
        "category": ref(asset.category),
        "category_kind": asset.category.kind,
        "icon": asset.category.icon,
        "branch": ref(asset.branch),
        "status": asset.status,
        "condition": asset.condition,
        "cost": asset.cost + asset.added,
        "accumulated": asset.accumulated + asset.written_down,
        "book_value": asset.book,
        "monthly": asset.last_amount,
        "in_service_on": asset.in_service_on,
        "custodian": ref(asset.custodian),
        "next_due": {"what": due[0], "day": due[1]} if due else None,
        "photo_url": photo_of(asset, user),
    }


class SummarySerializer(serializers.Serializer):
    count = serializers.IntegerField()
    cost = Money()
    accumulated = Money()
    book = Money()
    this_month = Money()
    this_year = Money()
    fully_depreciated = serializers.IntegerField()
    upkeep_due = serializers.IntegerField()
    low_value = serializers.IntegerField()

    class Meta:
        ref_name = "AssetsSummary"


class AssetWriteSerializer(serializers.Serializer):
    """Create and correct an asset. Ids for category, branch, supplier, purchase, people."""

    category = serializers.IntegerField(required=False)
    name = serializers.CharField(max_length=120, required=False)
    number = serializers.CharField(max_length=24, required=False, allow_blank=True)
    model = serializers.CharField(max_length=80, required=False, allow_blank=True)
    serial = serializers.CharField(max_length=64, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    condition = serializers.ChoiceField(choices=Asset.Condition.choices, required=False)
    status = serializers.ChoiceField(
        choices=WRITABLE_STATUSES,
        required=False,
    )
    branch = serializers.IntegerField(required=False, allow_null=True)
    purchased_on = serializers.DateField(required=False, allow_null=True)
    in_service_on = serializers.DateField(required=False, allow_null=True)
    cost = Money(required=False, allow_null=True)
    price = Money(required=False, allow_null=True)
    price_currency = serializers.ChoiceField(choices=Currency.choices, required=False)
    price_rate = serializers.DecimalField(
        max_digits=18, decimal_places=6, required=False, allow_null=True
    )
    salvage_value = Money(required=False, allow_null=True)
    life_months = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    method = serializers.ChoiceField(choices=Method.choices, required=False)
    declining_factor = serializers.DecimalField(max_digits=4, decimal_places=2, required=False)
    total_units = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True)
    opening_accumulated = Money(required=False, allow_null=True)
    books_depreciation = serializers.BooleanField(required=False)
    supplier = serializers.IntegerField(required=False, allow_null=True)
    supplier_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    purchase_transaction = serializers.IntegerField(required=False, allow_null=True)
    custodian = serializers.IntegerField(required=False, allow_null=True)
    responsible = serializers.IntegerField(required=False, allow_null=True)
    warranty_until = serializers.DateField(required=False, allow_null=True)
    insurance_until = serializers.DateField(required=False, allow_null=True)
    service_months = serializers.IntegerField(required=False, allow_null=True)
    next_service_on = serializers.DateField(required=False, allow_null=True)
    verify_months = serializers.IntegerField(required=False, allow_null=True)
    next_verification_on = serializers.DateField(required=False, allow_null=True)

    class Meta:
        ref_name = "AssetsWrite"


# One asset -----------------------------------------------------------------------------------


class ValuesSerializer(serializers.Serializer):
    cost = Money()
    added = Money()
    written_down = Money()
    accumulated = Money()
    book = Money()
    salvage_value = Money()
    monthly_now = Money()
    months_used = serializers.IntegerField()
    months_left = serializers.IntegerField(allow_null=True)
    end_month = serializers.DateField(allow_null=True)
    fully_depreciated = serializers.BooleanField()


class MonthSerializer(serializers.Serializer):
    month = serializers.DateField()
    opening = Money()
    amount = Money()
    closing = Money()
    accumulated = Money()
    state = serializers.ChoiceField(choices=MONTH_STATES)
    notes = serializers.ListField(child=serializers.CharField())
    transaction_id = serializers.IntegerField(allow_null=True)


class TaxBookSerializer(serializers.Serializer):
    rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    group = serializers.CharField()
    monthly = Money()
    accumulated = Money()
    book = Money()
    end_month = serializers.DateField(allow_null=True)
    difference = Money()


class EventSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=AssetEvent.Kind.choices)
    on = serializers.DateField()
    amount = Money(allow_null=True)
    units = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    from_branch = Ref(allow_null=True)
    to_branch = Ref(allow_null=True)
    person = Ref(allow_null=True)
    note = serializers.CharField()
    details = serializers.DictField()
    by = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


def event_of(event: AssetEvent) -> dict:
    return {
        "id": event.pk,
        "kind": event.kind,
        "on": event.on,
        "amount": event.amount,
        "units": event.units,
        "from_branch": ref(event.from_branch),
        "to_branch": ref(event.to_branch),
        "person": ref(event.membership),
        "note": event.note,
        "details": event.details,
        "by": event.created_by.get_full_name() or str(event.created_by)
        if event.created_by
        else None,
        "created_at": event.created_at,
    }


class AssignmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    person = Ref()
    issued_on = serializers.DateField()
    condition_out = serializers.CharField()
    note_out = serializers.CharField()
    acknowledged_at = serializers.DateTimeField(allow_null=True)
    returned_on = serializers.DateField(allow_null=True)
    condition_in = serializers.CharField()
    note_in = serializers.CharField()


def assignment_of(row) -> dict:
    return {
        "id": row.pk,
        "person": ref(row.membership),
        "issued_on": row.issued_on,
        "condition_out": row.condition_out,
        "note_out": row.note_out,
        "acknowledged_at": row.acknowledged_at,
        "returned_on": row.returned_on,
        "condition_in": row.condition_in,
        "note_in": row.note_in,
    }


class FileSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=AssetFile.Kind.choices)
    label = serializers.CharField()
    url = serializers.CharField()
    created_at = serializers.DateTimeField()

    class Meta:
        ref_name = "AssetsFile"


def file_of(row: AssetFile, user) -> dict:
    return {
        "id": row.pk,
        "kind": row.kind,
        "label": row.label,
        "url": signed_url(
            row.file, user=user, company_id=row.company_id, check=f"assets.file:{row.pk}"
        ),
        "created_at": row.created_at,
    }


class PurchaseRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    occurred_on = serializers.DateField()
    amount = Money()
    currency = serializers.CharField()
    description = serializers.CharField()
    account = serializers.CharField(allow_null=True)
    capitalized = serializers.BooleanField()


class AssetDetailSerializer(serializers.Serializer):
    asset = AssetRowSerializer()
    serial = serializers.CharField()
    notes = serializers.CharField()
    purchased_on = serializers.DateField(allow_null=True)
    price = Money(allow_null=True)
    price_currency = serializers.CharField()
    price_rate = serializers.DecimalField(max_digits=18, decimal_places=6)
    life_months = serializers.IntegerField(allow_null=True)
    method = serializers.ChoiceField(choices=Method.choices)
    declining_factor = serializers.DecimalField(max_digits=4, decimal_places=2)
    total_units = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    unit = serializers.CharField()
    opening_accumulated = Money(allow_null=True)
    books_depreciation = serializers.BooleanField()
    booked = serializers.BooleanField(help_text="Some of it is in Finance: facts are history.")
    supplier = Ref(allow_null=True)
    supplier_name = serializers.CharField()
    purchase = PurchaseRefSerializer(allow_null=True)
    responsible = Ref(allow_null=True)
    warranty_until = serializers.DateField(allow_null=True)
    insurance_until = serializers.DateField(allow_null=True)
    service_months = serializers.IntegerField(allow_null=True)
    next_service_on = serializers.DateField(allow_null=True)
    verify_months = serializers.IntegerField(allow_null=True)
    next_verification_on = serializers.DateField(allow_null=True)
    disposed_on = serializers.DateField(allow_null=True)
    disposal = serializers.CharField()
    disposal_amount = Money(allow_null=True)
    disposal_reason = serializers.CharField()
    qr_link = serializers.CharField()
    values = ValuesSerializer()
    schedule = MonthSerializer(many=True)
    tax = TaxBookSerializer(allow_null=True)
    events = EventSerializer(many=True)
    assignments = AssignmentSerializer(many=True)
    files = FileSerializer(many=True)

    class Meta:
        ref_name = "AssetsDetail"


# Actions -------------------------------------------------------------------------------------


class DaySerializer(serializers.Serializer):
    on = serializers.DateField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class StatusSerializer(DaySerializer):
    status = serializers.ChoiceField(choices=WRITABLE_STATUSES)


class MoveSerializer(DaySerializer):
    branch = serializers.IntegerField(allow_null=True)


class IssueSerializer(DaySerializer):
    person = serializers.IntegerField()
    condition = serializers.ChoiceField(choices=Asset.Condition.choices, required=False)


class ReturnSerializer(DaySerializer):
    condition = serializers.ChoiceField(choices=Asset.Condition.choices, required=False)


class AmountSerializer(DaySerializer):
    amount = Money()


class ServiceSerializer(DaySerializer):
    amount = Money(required=False, allow_null=True)


class VerificationSerializer(DaySerializer):
    valid_until = serializers.DateField(required=False, allow_null=True)


class RepairSerializer(DaySerializer):
    amount = Money(required=False, allow_null=True)
    improves = serializers.BooleanField(required=False, default=False)


class AdditionSerializer(AmountSerializer):
    purchase = serializers.IntegerField(required=False, allow_null=True)


class EstimateSerializer(DaySerializer):
    life_months = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    salvage_value = Money(required=False, allow_null=True)
    method = serializers.ChoiceField(choices=Method.choices, required=False, allow_null=True)


class UsageSerializer(serializers.Serializer):
    on = serializers.DateField()
    units = serializers.DecimalField(max_digits=14, decimal_places=2)


class DisposeSerializer(serializers.Serializer):
    on = serializers.DateField()
    kind = serializers.ChoiceField(choices=Asset.Disposal.choices)
    amount = Money(required=False, allow_null=True)
    account = serializers.IntegerField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300)


class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    kind = serializers.ChoiceField(choices=AssetFile.Kind.choices)
    label = serializers.CharField(required=False, allow_blank=True, max_length=120)


# Reports -------------------------------------------------------------------------------------


class ReportGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    amounts = serializers.ListField(child=Money())
    total = Money()
    assets = serializers.IntegerField()


class DepreciationReportSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    group = serializers.ChoiceField(choices=REPORT_GROUPS)
    months = serializers.ListField(child=serializers.DateField())
    posted_through = serializers.DateField()
    groups = ReportGroupSerializer(many=True)
    totals = serializers.ListField(child=Money())
    total = Money()
    tax = serializers.ListField(child=Money(), allow_null=True)
    tax_total = Money(allow_null=True)


class MovementLineSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    name = serializers.CharField(required=False)
    open_cost = Money()
    open_depreciation = Money()
    open_book = Money()
    in_cost = Money()
    out_cost = Money()
    out_depreciation = Money()
    depreciation = Money()
    written_down = Money()
    close_cost = Money()
    close_depreciation = Money()
    close_book = Money()


class MovementSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    lines = MovementLineSerializer(many=True)
    total = MovementLineSerializer()


class PlanAssetSerializer(serializers.Serializer):
    asset = AssetRowSerializer()
    end_month = serializers.DateField(required=False)
    estimate = Money(required=False)
    repairs = Money(required=False)
    replacement = Money(required=False)
    share = Money(required=False)


class QuarterSerializer(serializers.Serializer):
    quarter = serializers.CharField()
    count = serializers.IntegerField()
    amount = Money()


class UpkeepSerializer(serializers.Serializer):
    asset = AssetRowSerializer()
    what = serializers.ChoiceField(choices=UPKEEP_KINDS)
    day = serializers.DateField()
    overdue = serializers.BooleanField()


class UnconfirmedSerializer(serializers.Serializer):
    asset = Ref()
    person = Ref()
    issued_on = serializers.DateField()


class PlanningSerializer(serializers.Serializer):
    replacements = PlanAssetSerializer(many=True)
    quarters = QuarterSerializer(many=True)
    replacement_total = Money()
    repairs = PlanAssetSerializer(many=True)
    idle = AssetRowSerializer(many=True)
    idle_value = Money()
    free = AssetRowSerializer(many=True)
    upkeep = UpkeepSerializer(many=True)
    unconfirmed = UnconfirmedSerializer(many=True)
    inflation = serializers.DecimalField(max_digits=5, decimal_places=2)


class CustodySerializer(serializers.Serializer):
    person = Ref()
    value = Money()
    unconfirmed = serializers.IntegerField()
    assets = AssetRowSerializer(many=True)


class PurchaseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    occurred_on = serializers.DateField()
    amount = Money()
    currency = serializers.CharField()
    base_amount = Money()
    category = serializers.CharField(allow_null=True)
    counterparty = Ref(allow_null=True)
    branch = Ref(allow_null=True)
    account = serializers.CharField(allow_null=True)
    description = serializers.CharField()


# Counts --------------------------------------------------------------------------------------


class CountLineSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    asset = Ref()
    number = serializers.CharField()
    result = serializers.ChoiceField(choices=AssetCountLine.Result.choices)
    note = serializers.CharField()
    checked_by = Ref(allow_null=True)
    checked_at = serializers.DateTimeField(allow_null=True)


class CountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    branch = Ref(allow_null=True)
    status = serializers.ChoiceField(choices=AssetCount.Status.choices)
    started_on = serializers.DateField()
    closed_at = serializers.DateTimeField(allow_null=True)
    note = serializers.CharField()
    totals = serializers.DictField(child=serializers.IntegerField())
    lines = CountLineSerializer(many=True, required=False)

    class Meta:
        ref_name = "AssetsCount"


class CountStartSerializer(serializers.Serializer):
    branch = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class CountMarkSerializer(serializers.Serializer):
    result = serializers.ChoiceField(choices=AssetCountLine.Result.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


# Every shape here gets an "Assets…" component name of its own, so none collides with another
# app's ("Movement", "Move") and subclasses never inherit their parent's name.
for _name, _shape in list(globals().items()):
    if (
        isinstance(_shape, type)
        and issubclass(_shape, serializers.Serializer)
        and _shape.__module__ == __name__
        and "Meta" not in _shape.__dict__
    ):
        _shape.Meta = type("Meta", (), {"ref_name": "Assets" + _name.removesuffix("Serializer")})
