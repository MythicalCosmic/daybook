"""Serializers of the finance owner endpoints (`owner_api.py`).

Money is always a string ("1250000.00"), days are company-local `YYYY-MM-DD`. Output
serializers read the viewing `membership` from the context to hide per-person salary detail
(§5) and to say what the viewer may do with a row (`can_edit`, `can_void`).
"""

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.files import signed_url
from apps.core.money import CENT, MoneySerializerField
from apps.finance import access, sources
from apps.finance.models import (
    Category,
    CompanyRate,
    Counterparty,
    Debt,
    FinanceSettings,
    MoneyAccount,
    RateSource,
    Receipt,
    Transaction,
    Transfer,
)
from apps.members.permissions import Perm

RECEIPT_TTL = 3600
EDIT_WINDOW = timedelta(hours=24)


def money_out(**kwargs) -> MoneySerializerField:
    return MoneySerializerField(positive=False, read_only=True, **kwargs)


# References -----------------------------------------------------------------------------------


class FinanceRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class FinanceBranchRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()


class FinanceAccountRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()
    currency = serializers.CharField()


class FinanceCategoryRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()
    color = serializers.CharField()
    parent_name = serializers.CharField(allow_null=True)


def branch_ref(branch) -> dict | None:
    return {"id": branch.pk, "name": branch.name, "code": branch.code} if branch else None


def person_ref(member) -> dict | None:
    return {"id": member.pk, "name": str(member)} if member else None


def account_ref(account) -> dict | None:
    if account is None:
        return None
    return {
        "id": account.pk,
        "name": account.name,
        "kind": account.kind,
        "currency": account.currency,
    }


def category_ref(category) -> dict | None:
    if category is None:
        return None
    return {
        "id": category.pk,
        "name": category.name,
        "kind": category.kind,
        "color": category.color,
        "parent_name": category.parent.name if category.parent_id else None,
    }


def user_name(user) -> str | None:
    return str(user) if user else None


# Accounts -------------------------------------------------------------------------------------


class AccountSerializer(serializers.ModelSerializer):
    """A money account with its balance, the balance in the base currency at today's rate and
    a 30-day sparkline (from `context["figures"]`)."""

    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    branch = serializers.SerializerMethodField()
    holder = serializers.SerializerMethodField()
    operators = serializers.SerializerMethodField()
    balance = money_out()
    base_balance = serializers.SerializerMethodField()
    spark = serializers.SerializerMethodField()
    last_activity = serializers.SerializerMethodField()
    can_record = serializers.SerializerMethodField()

    class Meta:
        model = MoneyAccount
        fields = (
            "id",
            "name",
            "kind",
            "kind_label",
            "currency",
            "branch",
            "holder",
            "operators",
            "bank_name",
            "number_last4",
            "balance",
            "base_balance",
            "allow_negative",
            "is_active",
            "order",
            "color",
            "spark",
            "last_activity",
            "can_record",
        )

    def _figures(self, account) -> dict:
        return self.context.get("figures", {}).get(account.pk, {})

    @extend_schema_field(FinanceBranchRefSerializer(allow_null=True))
    def get_branch(self, account):
        return branch_ref(account.branch)

    @extend_schema_field(FinanceRefSerializer(allow_null=True))
    def get_holder(self, account):
        return person_ref(account.holder)

    @extend_schema_field(FinanceRefSerializer(many=True))
    def get_operators(self, account):
        return [person_ref(member) for member in account.operators.all()]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_base_balance(self, account):
        value = self._figures(account).get("base")
        return str(value) if value is not None else None

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_spark(self, account):
        return [str(value) for value in self._figures(account).get("spark", [])]

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_last_activity(self, account):
        day = self._figures(account).get("last_activity")
        return day.isoformat() if day else None

    def get_can_record(self, account) -> bool:
        return account.pk in self.context.get("recordable", set())


class AccountWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    kind = serializers.ChoiceField(MoneyAccount.Kind.choices)
    currency = serializers.ChoiceField(("UZS", "USD"), default="UZS")
    branch = serializers.IntegerField(required=False, allow_null=True)
    holder = serializers.IntegerField(required=False, allow_null=True)
    operators = serializers.ListField(child=serializers.IntegerField(), required=False)
    bank_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    number_last4 = serializers.CharField(max_length=4, required=False, allow_blank=True)
    allow_negative = serializers.BooleanField(required=False)
    color = serializers.CharField(max_length=7, required=False, allow_blank=True)
    order = serializers.IntegerField(required=False, min_value=0)
    opening_balance = MoneySerializerField(positive=False, required=False, allow_null=True)
    opening_on = serializers.DateField(required=False, allow_null=True)


class AccountUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    branch = serializers.IntegerField(required=False, allow_null=True)
    operators = serializers.ListField(child=serializers.IntegerField(), required=False)
    bank_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    number_last4 = serializers.CharField(max_length=4, required=False, allow_blank=True)
    allow_negative = serializers.BooleanField(required=False)
    color = serializers.CharField(max_length=7, required=False, allow_blank=True)
    order = serializers.IntegerField(required=False, min_value=0)


# Categories -----------------------------------------------------------------------------------


class CategoryNodeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()
    parent_id = serializers.IntegerField(allow_null=True)
    system_code = serializers.CharField()
    is_system = serializers.BooleanField()
    is_sensitive = serializers.BooleanField()
    is_capex = serializers.BooleanField()
    is_active = serializers.BooleanField()
    color = serializers.CharField()
    icon = serializers.CharField()
    order = serializers.IntegerField()
    entries = serializers.IntegerField(help_text="Ledger rows booked on it (0: it can be deleted).")
    children = serializers.ListField(child=serializers.DictField())


def category_node(category: Category, entries: dict[int, int], children: list[dict]) -> dict:
    return {
        "id": category.pk,
        "name": category.name,
        "kind": category.kind,
        "parent_id": category.parent_id,
        "system_code": category.system_code,
        "is_system": bool(category.system_code),
        "is_sensitive": category.is_sensitive,
        "is_capex": category.is_capex,
        "is_active": category.is_active,
        "color": category.color,
        "icon": category.icon,
        "order": category.order,
        "entries": entries.get(category.pk, 0),
        "children": children,
    }


class CategoryWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    kind = serializers.ChoiceField(Category.Kind.choices)
    parent = serializers.IntegerField(required=False, allow_null=True)
    color = serializers.CharField(max_length=7, required=False, allow_blank=True)
    icon = serializers.CharField(max_length=40, required=False, allow_blank=True)
    is_capex = serializers.BooleanField(required=False)
    is_sensitive = serializers.BooleanField(required=False)


class CategoryUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    color = serializers.CharField(max_length=7, required=False, allow_blank=True)
    icon = serializers.CharField(max_length=40, required=False, allow_blank=True)
    is_capex = serializers.BooleanField(required=False)
    is_sensitive = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)


class CategoryMergeSerializer(serializers.Serializer):
    into = serializers.IntegerField()


class CategoryMoveSerializer(serializers.Serializer):
    parent = serializers.IntegerField(allow_null=True)
    index = serializers.IntegerField(min_value=0)


# Counterparties -------------------------------------------------------------------------------


class CounterpartySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    default_category = serializers.SerializerMethodField()
    credit_limit = money_out(allow_null=True)
    owes_us = serializers.SerializerMethodField()
    we_owe = serializers.SerializerMethodField()
    overdue = serializers.SerializerMethodField()
    last_activity = serializers.SerializerMethodField()

    class Meta:
        model = Counterparty
        fields = (
            "id",
            "name",
            "kind",
            "kind_label",
            "phone",
            "tin",
            "contact_person",
            "telegram_username",
            "address",
            "bank_details",
            "notes",
            "default_category",
            "credit_limit",
            "credit_blocked",
            "birthday",
            "tags",
            "is_active",
            "owes_us",
            "we_owe",
            "overdue",
            "last_activity",
            "created_at",
        )

    def _balance(self, party) -> dict:
        return self.context.get("balances", {}).get(party.pk, {})

    @extend_schema_field(FinanceCategoryRefSerializer(allow_null=True))
    def get_default_category(self, party):
        return category_ref(party.default_category)

    @extend_schema_field(serializers.CharField())
    def get_owes_us(self, party):
        return str(self._balance(party).get("owes_us", "0.00"))

    @extend_schema_field(serializers.CharField())
    def get_we_owe(self, party):
        return str(self._balance(party).get("we_owe", "0.00"))

    @extend_schema_field(serializers.CharField())
    def get_overdue(self, party):
        return str(self._balance(party).get("overdue", "0.00"))

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_last_activity(self, party):
        day = self._balance(party).get("last_activity")
        return day.isoformat() if day else None


class CounterpartyWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    kind = serializers.ChoiceField(Counterparty.Kind.choices, required=False)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    tin = serializers.CharField(max_length=20, required=False, allow_blank=True)
    contact_person = serializers.CharField(max_length=100, required=False, allow_blank=True)
    telegram_username = serializers.CharField(max_length=65, required=False, allow_blank=True)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    bank_details = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    default_category = serializers.IntegerField(required=False, allow_null=True)
    credit_limit = MoneySerializerField(positive=False, required=False, allow_null=True)
    credit_blocked = serializers.BooleanField(required=False)
    birthday = serializers.DateField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=32), required=False)
    is_active = serializers.BooleanField(required=False)


# Receipts -------------------------------------------------------------------------------------


class ReceiptSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    thumb_url = serializers.SerializerMethodField()
    is_image = serializers.BooleanField(read_only=True)

    class Meta:
        model = Receipt
        fields = ("id", "url", "thumb_url", "content_type", "size", "is_image", "created_at")

    def _sign(self, receipt, file, suffix=""):
        member = self.context["membership"]
        extension = ".pdf" if receipt.content_type == "application/pdf" else ".jpg"
        if suffix:
            extension = ".webp"
        return signed_url(
            file,
            user=member.user,
            company_id=receipt.company_id,
            check=f"finance.receipt:{receipt.pk}",
            ttl=RECEIPT_TTL,
            filename=f"receipt-{receipt.pk}{suffix}{extension}",
        )

    @extend_schema_field(serializers.CharField())
    def get_url(self, receipt):
        return self._sign(receipt, receipt.file)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_thumb_url(self, receipt):
        return self._sign(receipt, receipt.thumb, "-thumb") if receipt.thumb else None


# Transactions ---------------------------------------------------------------------------------


class SourceRefSerializer(serializers.Serializer):
    type = serializers.CharField()
    label = serializers.CharField()
    id = serializers.IntegerField()
    url = serializers.CharField()


def source_label(row) -> str:
    return str(sources.label(row.source_type)) if row.source_type else ""


def foreign_source(row) -> str | None:
    """The label of the module that booked `row` (an entry, transfer or debt) when it isn't the
    finance ledger itself: such rows are corrected in their module (§2.3 rule 3)."""
    if row.source_type and not row.source_type.startswith("finance."):
        return source_label(row)
    return None


def source_ref(row, company_id: int) -> dict | None:
    if not row.source_type:
        return None
    return {
        "type": row.source_type,
        "label": sources.label(row.source_type),
        "id": row.source_id,
        "url": sources.url(row.source_type, row.source_id, company_id),
    }


class TransactionSerializer(serializers.ModelSerializer):
    """One ledger row. Without payroll access, a salary-type row keeps its amount and category
    but loses the person, the party, the description and the receipts (`masked`)."""

    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    account = serializers.SerializerMethodField()
    amount = money_out()
    rate = serializers.DecimalField(max_digits=18, decimal_places=6, coerce_to_string=True)
    base_amount = money_out()
    category = serializers.SerializerMethodField()
    counterparty = serializers.SerializerMethodField()
    membership = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    project = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    approved_by = serializers.SerializerMethodField()
    voided_by = serializers.SerializerMethodField()
    receipts = serializers.SerializerMethodField()
    masked = serializers.SerializerMethodField()
    is_manual = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_void = serializers.SerializerMethodField()
    can_approve = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = (
            "id",
            "kind",
            "kind_label",
            "status",
            "status_label",
            "occurred_on",
            "account",
            "amount",
            "currency",
            "rate",
            "rate_stale",
            "base_amount",
            "category",
            "counterparty",
            "membership",
            "branch",
            "project",
            "debt_id",
            "transfer_id",
            "is_contra",
            "description",
            "source",
            "created_by",
            "created_at",
            "approved_by",
            "approved_at",
            "voided_by",
            "voided_at",
            "void_reason",
            "receipts",
            "masked",
            "is_manual",
            "can_edit",
            "can_void",
            "can_approve",
        )

    @property
    def viewer(self):
        return self.context["membership"]

    def _masked(self, row) -> bool:
        return access.masks_row(self.viewer, row)

    def get_masked(self, row) -> bool:
        return self._masked(row)

    @extend_schema_field(FinanceAccountRefSerializer(allow_null=True))
    def get_account(self, row):
        return account_ref(row.account)

    @extend_schema_field(FinanceCategoryRefSerializer(allow_null=True))
    def get_category(self, row):
        return category_ref(row.category)

    @extend_schema_field(FinanceRefSerializer(allow_null=True))
    def get_counterparty(self, row):
        if self._masked(row) or row.counterparty_id is None:
            return None
        return {"id": row.counterparty_id, "name": row.counterparty.name}

    @extend_schema_field(FinanceRefSerializer(allow_null=True))
    def get_membership(self, row):
        return None if self._masked(row) else person_ref(row.membership)

    @extend_schema_field(FinanceBranchRefSerializer(allow_null=True))
    def get_branch(self, row):
        return branch_ref(row.branch)

    @extend_schema_field(FinanceRefSerializer(allow_null=True))
    def get_project(self, row):
        return {"id": row.project_id, "name": row.project.name} if row.project_id else None

    def get_description(self, row) -> str:
        return "" if self._masked(row) else row.description

    @extend_schema_field(SourceRefSerializer(allow_null=True))
    def get_source(self, row):
        # A payslip's number leads to the person: hidden with the rest of the detail.
        return None if self._masked(row) else source_ref(row, row.company_id)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_created_by(self, row):
        return user_name(row.created_by)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_approved_by(self, row):
        return user_name(row.approved_by)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_voided_by(self, row):
        return user_name(row.voided_by)

    @extend_schema_field(ReceiptSerializer(many=True))
    def get_receipts(self, row):
        if self._masked(row):
            return []
        return ReceiptSerializer(row.receipts.all(), many=True, context=self.context).data

    def get_is_manual(self, row) -> bool:
        return (
            row.kind in ("income", "expense", "owner", "opening")
            and not row.source_type
            and row.transfer_id is None
            and row.debt_id is None
        )

    def _open(self, row) -> bool:
        locked = self.context.get("locked_until")
        return row.status in ("posted", "pending") and (locked is None or row.occurred_on > locked)

    def get_can_edit(self, row) -> bool:
        if not self._open(row) or self._masked(row):
            return False
        if access.can_manage(self.viewer):
            return True
        return (
            access.can_record(self.viewer)
            and row.created_by_id == self.viewer.user_id
            and row.created_at >= timezone.now() - EDIT_WINDOW
        )

    def get_can_void(self, row) -> bool:
        if not self._open(row) or not access.can_manage(self.viewer):
            return False
        if row.transfer_id is not None or row.kind == "debt_open":
            return False
        if row.kind in ("income", "expense") and row.account_id is None and row.debt_id:
            return False
        if foreign_source(row) is not None:
            return False
        return not (row.kind == "fx" and row.source_type == "finance.transaction")

    def get_can_approve(self, row) -> bool:
        """A pending entry recorded here (a claim's entry is decided with its claim), by someone
        else than the viewer unless the viewer is an owner."""
        if row.status != "pending" or row.source_type or not self._open(row):
            return False
        if not self.viewer.has_perm(Perm.FINANCE_APPROVE):
            return False
        return row.created_by_id != self.viewer.user_id or access.is_owner(self.viewer)


class TransactionCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(("income", "expense", "owner", "opening"))
    direction = serializers.ChoiceField(("in", "out"), default="in")
    amount = MoneySerializerField()
    occurred_on = serializers.DateField()
    account = serializers.IntegerField()
    category = serializers.IntegerField(required=False, allow_null=True)
    counterparty = serializers.IntegerField(required=False, allow_null=True)
    member = serializers.IntegerField(required=False, allow_null=True)
    branch = serializers.IntegerField(required=False, allow_null=True)
    project = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    receipt_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    receipts = serializers.ListField(child=serializers.FileField(), required=False)


class TransactionUpdateSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    category = serializers.IntegerField(required=False, allow_null=True)
    counterparty = serializers.IntegerField(required=False, allow_null=True)
    member = serializers.IntegerField(required=False, allow_null=True)
    branch = serializers.IntegerField(required=False, allow_null=True)
    project = serializers.IntegerField(required=False, allow_null=True)
    occurred_on = serializers.DateField(required=False)
    amount = MoneySerializerField(required=False)
    account = serializers.IntegerField(required=False)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


class BulkSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=200)
    action = serializers.ChoiceField(("categorize", "void"))
    category = serializers.IntegerField(required=False)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)


class BulkResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    ok = serializers.BooleanField()
    error = serializers.CharField(required=False)


class ReceiptUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


# Transfers ------------------------------------------------------------------------------------


class TransferSerializer(serializers.ModelSerializer):
    from_account = serializers.SerializerMethodField()
    to_account = serializers.SerializerMethodField()
    amount_out = money_out()
    amount_in = money_out()
    fee = money_out()
    exchange_rate = serializers.DecimalField(
        max_digits=18, decimal_places=6, coerce_to_string=True, allow_null=True
    )
    created_by = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()

    class Meta:
        model = Transfer
        fields = (
            "id",
            "occurred_on",
            "from_account",
            "to_account",
            "amount_out",
            "amount_in",
            "exchange_rate",
            "fee",
            "description",
            "status",
            "source",
            "created_by",
            "created_at",
            "voided_at",
            "void_reason",
        )

    @extend_schema_field(FinanceAccountRefSerializer)
    def get_from_account(self, transfer):
        return account_ref(transfer.from_account)

    @extend_schema_field(FinanceAccountRefSerializer)
    def get_to_account(self, transfer):
        return account_ref(transfer.to_account)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_created_by(self, transfer):
        return user_name(transfer.created_by)

    @extend_schema_field(SourceRefSerializer(allow_null=True))
    def get_source(self, transfer):
        return source_ref(transfer, transfer.company_id)


class TransferCreateSerializer(serializers.Serializer):
    from_account = serializers.IntegerField()
    to_account = serializers.IntegerField()
    amount_out = MoneySerializerField()
    amount_in = MoneySerializerField(required=False, allow_null=True)
    rate = serializers.DecimalField(
        max_digits=18, decimal_places=6, required=False, allow_null=True, min_value=CENT
    )
    fee = MoneySerializerField(positive=False, required=False, min_value=0)
    occurred_on = serializers.DateField()
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)


# Debts ----------------------------------------------------------------------------------------


class DebtPartySerializer(serializers.Serializer):
    type = serializers.ChoiceField(("counterparty", "member"))
    id = serializers.IntegerField()
    name = serializers.CharField()


class InstallmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    due_on = serializers.DateField()
    amount = serializers.CharField()
    paid = serializers.CharField()
    status = serializers.ChoiceField(("paid", "partial", "due", "overdue"))


class DebtSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    direction_label = serializers.CharField(source="get_direction_display", read_only=True)
    party = serializers.SerializerMethodField()
    amount = money_out()
    paid = money_out()
    outstanding = serializers.SerializerMethodField()
    base_outstanding = serializers.SerializerMethodField()
    days_overdue = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    responsible = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    masked = serializers.SerializerMethodField()

    class Meta:
        model = Debt
        fields = (
            "id",
            "direction",
            "direction_label",
            "kind",
            "kind_label",
            "status",
            "party",
            "currency",
            "amount",
            "paid",
            "outstanding",
            "base_outstanding",
            "issued_on",
            "due_on",
            "days_overdue",
            "description",
            "branch",
            "responsible",
            "is_opening",
            "is_locked",
            "source",
            "masked",
            "created_at",
        )

    def _masked(self, debt) -> bool:
        return access.masks_debt(self.context["membership"], debt)

    def get_masked(self, debt) -> bool:
        return self._masked(debt)

    @extend_schema_field(DebtPartySerializer(allow_null=True))
    def get_party(self, debt):
        if self._masked(debt):
            return None
        if debt.counterparty_id:
            return {
                "type": "counterparty",
                "id": debt.counterparty_id,
                "name": debt.counterparty.name,
            }
        return {"type": "member", "id": debt.membership_id, "name": str(debt.membership)}

    @extend_schema_field(serializers.CharField())
    def get_outstanding(self, debt):
        return str(debt.amount - debt.paid)

    @extend_schema_field(serializers.CharField())
    def get_base_outstanding(self, debt):
        from apps.finance.queries import book_value

        return str(book_value(debt, debt.amount - debt.paid))

    def get_days_overdue(self, debt) -> int:
        from apps.finance.queries import days_overdue

        return days_overdue(debt, self.context["today"])

    def get_description(self, debt) -> str:
        return "" if self._masked(debt) else debt.description

    @extend_schema_field(FinanceBranchRefSerializer(allow_null=True))
    def get_branch(self, debt):
        return branch_ref(debt.branch)

    @extend_schema_field(FinanceRefSerializer(allow_null=True))
    def get_responsible(self, debt):
        return person_ref(debt.responsible)

    @extend_schema_field(SourceRefSerializer(allow_null=True))
    def get_source(self, debt):
        return source_ref(debt, debt.company_id)


class DebtCreateSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(Debt.Direction.choices)
    kind = serializers.ChoiceField(
        [
            (kind, label)
            for kind, label in Debt.Kind.choices
            if kind not in ("salary", "reimbursement")
        ]
    )
    mode = serializers.ChoiceField(
        ("account", "category", "opening"),
        help_text="account: money moved now; category: earned or spent on credit; opening: owed "
        "from before the books started.",
    )
    amount = MoneySerializerField()
    currency = serializers.ChoiceField(("UZS", "USD"))
    issued_on = serializers.DateField()
    due_on = serializers.DateField(required=False, allow_null=True)
    counterparty = serializers.IntegerField(required=False, allow_null=True)
    member = serializers.IntegerField(required=False, allow_null=True)
    account = serializers.IntegerField(required=False, allow_null=True)
    category = serializers.IntegerField(required=False, allow_null=True)
    branch = serializers.IntegerField(required=False, allow_null=True)
    responsible = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)

    def validate(self, attrs):
        if bool(attrs.get("counterparty")) == bool(attrs.get("member")):
            raise serializers.ValidationError(
                {"counterparty": [_("Pick who owes or is owed: a counterparty or an employee.")]}
            )
        if attrs["mode"] == "account" and not attrs.get("account"):
            raise serializers.ValidationError({"account": [_("Pick the account.")]})
        if attrs["mode"] == "category" and not attrs.get("category"):
            raise serializers.ValidationError({"category": [_("Pick a category.")]})
        return attrs


class DebtUpdateSerializer(serializers.Serializer):
    due_on = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    responsible = serializers.IntegerField(required=False, allow_null=True)
    branch = serializers.IntegerField(required=False, allow_null=True)


class PaymentSerializer(serializers.Serializer):
    account = serializers.IntegerField()
    amount = MoneySerializerField()
    debt_amount = MoneySerializerField(required=False, allow_null=True)
    paid_on = serializers.DateField()


class WriteOffSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)
    amount = MoneySerializerField(required=False, allow_null=True)


class InstallmentRowSerializer(serializers.Serializer):
    due_on = serializers.DateField()
    amount = MoneySerializerField()


class InstallmentsWriteSerializer(serializers.Serializer):
    installments = InstallmentRowSerializer(many=True)


# Rates and settings ---------------------------------------------------------------------------


class RateRowSerializer(serializers.Serializer):
    id = serializers.CharField(help_text='"cbu-12", "manual-3" or "company-7".')
    date = serializers.DateField()
    currency = serializers.CharField()
    rate = serializers.CharField()
    source = serializers.ChoiceField(("cbu", "manual", "company"))
    set_by = serializers.CharField(allow_null=True)
    editable = serializers.BooleanField()


def rate_row(row) -> dict:
    if isinstance(row, CompanyRate):
        return {
            "id": f"company-{row.pk}",
            "date": row.date.isoformat(),
            "currency": row.currency,
            "rate": str(row.rate),
            "source": "company",
            "set_by": user_name(row.set_by),
            "editable": True,
        }
    return {
        "id": f"{row.source}-{row.pk}",
        "date": row.date.isoformat(),
        "currency": row.currency,
        "rate": str(row.rate),
        "source": row.source if row.source in (RateSource.CBU, RateSource.MANUAL) else "cbu",
        "set_by": None,
        "editable": False,
    }


class RateCreateSerializer(serializers.Serializer):
    currency = serializers.ChoiceField(("USD",), default="USD")
    date = serializers.DateField()
    rate = serializers.DecimalField(max_digits=18, decimal_places=6, min_value=CENT)


class SettingsSerializer(serializers.ModelSerializer):
    approval_threshold = money_out(allow_null=True)
    receipt_required_over = money_out(allow_null=True)
    large_expense_alert = money_out(allow_null=True)
    base_currency = serializers.CharField(source="company.base_currency", read_only=True)
    can_reopen = serializers.SerializerMethodField()

    class Meta:
        model = FinanceSettings
        fields = (
            "locked_until",
            "rate_source",
            "approval_threshold",
            "receipt_required_over",
            "large_expense_alert",
            "reimburse_via",
            "base_currency",
            "can_reopen",
        )

    def get_can_reopen(self, row) -> bool:
        return access.is_owner(self.context["membership"])


class SettingsUpdateSerializer(serializers.Serializer):
    rate_source = serializers.ChoiceField(RateSource.choices, required=False)
    approval_threshold = MoneySerializerField(positive=False, required=False, allow_null=True)
    receipt_required_over = MoneySerializerField(positive=False, required=False, allow_null=True)
    large_expense_alert = MoneySerializerField(positive=False, required=False, allow_null=True)
    reimburse_via = serializers.ChoiceField(FinanceSettings.ReimburseVia.choices, required=False)


class LockSerializer(serializers.Serializer):
    until = serializers.DateField(allow_null=True)
