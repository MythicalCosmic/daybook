"""Django admin for the finance ledger: read-only, so balances never drift from their rows.

Every change goes through `apps.finance.services` (the owner dashboard and the bots). The one
exception is global exchange rates, which platform admins may enter by hand.
"""

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.finance.models import (
    Category,
    CompanyRate,
    Counterparty,
    Debt,
    ExchangeRate,
    FinanceSettings,
    MoneyAccount,
    Transaction,
    Transfer,
)


class ReadOnlyAdmin(ModelAdmin):
    """Shows rows; never adds, changes or deletes them."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyInline(TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class RowInline(ReadOnlyInline):
    model = Transaction
    fields = ("occurred_on", "kind", "status", "account", "amount", "currency", "base_amount")
    ordering = ("pk",)


@admin.register(FinanceSettings)
class FinanceSettingsAdmin(ReadOnlyAdmin):
    list_display = ("company", "locked_until", "rate_source", "reimburse_via")
    list_select_related = ("company",)


@admin.register(ExchangeRate)
class ExchangeRateAdmin(ModelAdmin):
    list_display = ("date", "currency", "rate", "source", "fetched_at")
    list_filter = ("currency", "source")
    date_hierarchy = "date"


@admin.register(CompanyRate)
class CompanyRateAdmin(ReadOnlyAdmin):
    list_display = ("date", "company", "currency", "rate", "set_by")
    list_filter = ("company", "currency")
    list_select_related = ("company", "set_by")
    date_hierarchy = "date"


@admin.register(MoneyAccount)
class MoneyAccountAdmin(ReadOnlyAdmin):
    list_display = (
        "name",
        "company",
        "kind",
        "currency",
        "balance",
        "branch",
        "holder",
        "is_active",
    )
    list_filter = ("company", "kind", "currency", "is_active")
    search_fields = ("name", "bank_name")
    list_select_related = ("company", "branch", "holder")


@admin.register(Category)
class CategoryAdmin(ReadOnlyAdmin):
    list_display = ("name", "company", "kind", "parent", "system_code", "is_sensitive", "is_active")
    list_filter = ("company", "kind", "is_active")
    search_fields = ("name", "system_code")
    list_select_related = ("company", "parent")


@admin.register(Counterparty)
class CounterpartyAdmin(ReadOnlyAdmin):
    list_display = ("name", "company", "kind", "phone", "tin", "is_active")
    list_filter = ("company", "kind", "is_active")
    search_fields = ("name", "phone", "tin")
    list_select_related = ("company",)


@admin.register(Transaction)
class TransactionAdmin(ReadOnlyAdmin):
    list_display = (
        "occurred_on",
        "company",
        "kind",
        "status",
        "account",
        "amount",
        "currency",
        "base_amount",
        "category",
        "source_type",
        "source_id",
    )
    list_filter = ("company", "kind", "status", "currency")
    search_fields = ("description", "source_type")
    list_select_related = ("company", "account", "category")
    date_hierarchy = "occurred_on"


@admin.register(Transfer)
class TransferAdmin(ReadOnlyAdmin):
    list_display = (
        "occurred_on",
        "company",
        "from_account",
        "to_account",
        "amount_out",
        "amount_in",
        "fee",
        "status",
    )
    list_filter = ("company", "status")
    list_select_related = ("company", "from_account", "to_account")
    date_hierarchy = "occurred_on"
    inlines = (RowInline,)


@admin.register(Debt)
class DebtAdmin(ReadOnlyAdmin):
    list_display = (
        "issued_on",
        "company",
        "direction",
        "kind",
        "status",
        "counterparty",
        "membership",
        "amount",
        "paid",
        "currency",
        "due_on",
    )
    list_filter = ("company", "direction", "kind", "status")
    search_fields = ("description", "counterparty__name")
    list_select_related = ("company", "counterparty", "membership")
    date_hierarchy = "issued_on"
    inlines = (RowInline,)
