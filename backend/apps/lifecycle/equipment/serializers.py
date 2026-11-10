"""Shapes of `lifecycle/equipment/…` (owner dashboard). Values are money strings, null without
the right to see them (assets.manage or finance.view; a deduction's amount: payroll.view)."""

from rest_framework import serializers

from apps.assets.models import Asset, AssetCategory
from apps.core.money import MoneySerializerField
from apps.hr.serializers import BranchRefSerializer, PersonRefSerializer
from apps.lifecycle.equipment.services import LOST, RETURNED


class EquipmentCategoryRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    icon = serializers.CharField(help_text="A lucide icon name.")
    kind = serializers.CharField(help_text="fixed, intangible or low_value.")

    class Meta:
        ref_name = "LifecycleEquipmentCategoryRef"


class EquipmentDeductionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = serializers.CharField(allow_null=True, help_text="Only with payroll.view.")
    currency = serializers.CharField()
    status = serializers.CharField(help_text="The adjustment's status in payroll.")

    class Meta:
        ref_name = "LifecycleEquipmentDeduction"


class EquipmentItemSerializer(serializers.Serializer):
    """Something a person holds: the hand-out and its asset."""

    assignment_id = serializers.IntegerField()
    asset_id = serializers.IntegerField()
    number = serializers.CharField()
    name = serializers.CharField()
    model = serializers.CharField()
    serial = serializers.CharField()
    notes = serializers.CharField(help_text="A size, for a uniform.")
    category = EquipmentCategoryRefSerializer()
    branch = BranchRefSerializer(allow_null=True)
    issued_on = serializers.DateField()
    condition_out = serializers.CharField()
    note_out = serializers.CharField()
    acknowledged_at = serializers.DateTimeField(allow_null=True)
    photo_url = serializers.CharField(
        allow_null=True, help_text="The photo taken when given, else one of the asset."
    )
    value = MoneySerializerField(allow_null=True, help_text="What it cost (register readers).")
    deduction = EquipmentDeductionSerializer(allow_null=True)
    may_write_off = serializers.BooleanField(help_text="A device needs assets.manage.")

    class Meta:
        ref_name = "LifecycleEquipmentItem"


class EquipmentPersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)
    position = serializers.CharField(allow_null=True)
    home_branch = BranchRefSerializer(allow_null=True)
    status = serializers.CharField(help_text="approved, suspended, left or blocked.")

    class Meta:
        ref_name = "LifecycleEquipmentPerson"


class EquipmentLeavingSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField(help_text="requested or agreed.")
    day = serializers.DateField(allow_null=True)

    class Meta:
        ref_name = "LifecycleEquipmentLeaving"


class EquipmentHolderSerializer(serializers.Serializer):
    person = EquipmentPersonSerializer()
    leaving = EquipmentLeavingSerializer(allow_null=True)
    left_on = serializers.DateField(allow_null=True)
    items = EquipmentItemSerializer(many=True)
    value = MoneySerializerField(allow_null=True)
    unconfirmed = serializers.IntegerField()
    overdue = serializers.IntegerField(help_text="Items still held by someone who has left.")
    leaving_soon = serializers.BooleanField(help_text="Leaves within two weeks, holding items.")

    class Meta:
        ref_name = "LifecycleEquipmentHolder"


class EquipmentTotalsSerializer(serializers.Serializer):
    people = serializers.IntegerField(help_text="People holding something.")
    items = serializers.IntegerField()
    unconfirmed = serializers.IntegerField()
    to_return = serializers.IntegerField(help_text="Held by people who leave or have left.")
    value = MoneySerializerField(allow_null=True)
    in_stock = serializers.IntegerField()

    class Meta:
        ref_name = "LifecycleEquipmentTotals"


class EquipmentCanSerializer(serializers.Serializer):
    values = serializers.BooleanField(help_text="Sees what things cost.")
    devices = serializers.BooleanField(help_text="Adds and writes off devices (assets.manage).")
    deduct = serializers.BooleanField(help_text="Payroll is on: deductions can be proposed.")
    pay = serializers.BooleanField(help_text="Sees a deduction's amount (payroll.view).")
    register = serializers.BooleanField(help_text="Opens the asset register.")

    class Meta:
        ref_name = "LifecycleEquipmentCan"


class EquipmentPeopleSerializer(serializers.Serializer):
    today = serializers.DateField()
    people = EquipmentHolderSerializer(many=True)
    totals = EquipmentTotalsSerializer()
    can = EquipmentCanSerializer()

    class Meta:
        ref_name = "LifecycleEquipmentPeople"


class EquipmentStockSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    name = serializers.CharField()
    model = serializers.CharField()
    serial = serializers.CharField()
    notes = serializers.CharField()
    category = EquipmentCategoryRefSerializer()
    branch = BranchRefSerializer(allow_null=True)
    status = serializers.CharField(help_text="in_use, in_storage, repair or suspended.")
    condition = serializers.CharField()
    value = MoneySerializerField(allow_null=True)
    holder = PersonRefSerializer(allow_null=True)
    issued_on = serializers.DateField(allow_null=True)
    acknowledged_at = serializers.DateTimeField(allow_null=True)
    photo_url = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "LifecycleEquipmentStock"


class EquipmentCategorySerializer(EquipmentCategoryRefSerializer):
    stock = serializers.IntegerField()
    out = serializers.IntegerField()
    may_add = serializers.BooleanField()

    class Meta:
        ref_name = "LifecycleEquipmentCategory"


class EquipmentSuggestionSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.CharField()
    icon = serializers.CharField()

    class Meta:
        ref_name = "LifecycleEquipmentSuggestion"


class EquipmentCategoriesSerializer(serializers.Serializer):
    categories = EquipmentCategorySerializer(many=True)
    suggestions = EquipmentSuggestionSerializer(many=True)

    class Meta:
        ref_name = "LifecycleEquipmentCategories"


class EquipmentHistorySerializer(EquipmentItemSerializer):
    returned_on = serializers.DateField(allow_null=True)
    condition_in = serializers.CharField()
    note_in = serializers.CharField()
    photo_in_url = serializers.CharField(allow_null=True)
    outcome = serializers.CharField(help_text="held, returned, lost or written_off.")

    class Meta:
        ref_name = "LifecycleEquipmentHistory"


class EquipmentPersonPageSerializer(serializers.Serializer):
    today = serializers.DateField()
    holder = EquipmentHolderSerializer()
    history = EquipmentHistorySerializer(many=True)
    can = EquipmentCanSerializer()

    class Meta:
        ref_name = "LifecycleEquipmentPersonPage"


# Writes --------------------------------------------------------------------------------------

CONDITIONS = Asset.Condition.choices


class IssueInputSerializer(serializers.Serializer):
    person_id = serializers.IntegerField()
    asset_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=30)
    on = serializers.DateField(required=False, allow_null=True)
    condition = serializers.ChoiceField(CONDITIONS, required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)
    photo = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        ref_name = "LifecycleEquipmentIssueInput"


class ReturnInputSerializer(serializers.Serializer):
    outcome = serializers.CharField(
        required=False, default=RETURNED, help_text=f"{RETURNED} (came back) or {LOST}."
    )
    on = serializers.DateField(required=False, allow_null=True)
    condition = serializers.ChoiceField(CONDITIONS, required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)
    photo = serializers.ImageField(required=False, allow_null=True)
    write_off = serializers.BooleanField(required=False, default=False)
    deduction = MoneySerializerField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300)

    class Meta:
        ref_name = "LifecycleEquipmentReturnInput"


class DeductionInputSerializer(serializers.Serializer):
    amount = MoneySerializerField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300)

    class Meta:
        ref_name = "LifecycleEquipmentDeductionInput"


class AddItemsInputSerializer(serializers.Serializer):
    category_id = serializers.IntegerField()
    name = serializers.CharField(max_length=110)
    quantity = serializers.IntegerField(min_value=1, max_value=100, default=1)
    branch_id = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    cost = MoneySerializerField(required=False, allow_null=True)
    serial = serializers.CharField(required=False, allow_blank=True, max_length=64)
    model = serializers.CharField(required=False, allow_blank=True, max_length=80)

    class Meta:
        ref_name = "LifecycleEquipmentAddInput"


class AddedSerializer(serializers.Serializer):
    items = EquipmentStockSerializer(many=True)

    class Meta:
        ref_name = "LifecycleEquipmentAdded"


class CategoryInputSerializer(serializers.Serializer):
    suggestion = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    kind = serializers.CharField(
        required=False,
        default=AssetCategory.Kind.LOW_VALUE.value,
        help_text="low_value (uniforms, keys) or fixed (a device).",
    )
    icon = serializers.CharField(required=False, allow_blank=True, max_length=40)

    class Meta:
        ref_name = "LifecycleEquipmentCategoryInput"
