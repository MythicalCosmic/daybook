"""Django admin for sales and cash: read-only, so shifts never drift from their ledger rows.

Every change goes through `apps.sales.services` (the owner dashboard, the mini app and the bots).
"""

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.sales.models import (
    CashMovement,
    CashShift,
    DailySales,
    PaymentMethod,
    Register,
    Sale,
    SalePayment,
    SalesSettings,
    SalesTarget,
    ShiftPayment,
)


class ReadOnlyAdmin(ModelAdmin):
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyInline(TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SalesSettings)
class SalesSettingsAdmin(ReadOnlyAdmin):
    list_display = ("company", "mode", "blind_cash_count", "cash_tolerance", "next_shift_number")
    list_select_related = ("company",)


@admin.register(PaymentMethod)
class PaymentMethodAdmin(ReadOnlyAdmin):
    list_display = ("name", "company", "kind", "account", "fee_percent", "is_active", "order")
    list_filter = ("kind", "is_active")
    list_select_related = ("company", "account")
    search_fields = ("name",)


@admin.register(Register)
class RegisterAdmin(ReadOnlyAdmin):
    list_display = ("name", "branch", "company", "cash_account", "is_active")
    list_select_related = ("branch", "company", "cash_account")


class ShiftPaymentInline(ReadOnlyInline):
    model = ShiftPayment
    fields = ("method", "sales", "refunds", "receipts")


class MovementInline(ReadOnlyInline):
    model = CashMovement
    fk_name = "shift"
    fields = ("kind", "amount", "receiver", "reason", "confirmed_at", "voided_at")


@admin.register(CashShift)
class CashShiftAdmin(ReadOnlyAdmin):
    list_display = (
        "__str__",
        "company",
        "branch",
        "cashier",
        "business_day",
        "status",
        "counted_cash",
        "difference",
    )
    list_filter = ("status", "forced", "ai_mismatch")
    list_select_related = ("company", "branch", "cashier")
    date_hierarchy = "business_day"
    inlines = (ShiftPaymentInline, MovementInline)
    exclude = ("z_photo", "terminal_photo")


@admin.register(CashMovement)
class CashMovementAdmin(ReadOnlyAdmin):
    list_display = ("kind", "amount", "company", "branch", "register", "receiver", "created_at")
    list_filter = ("kind",)
    list_select_related = ("company", "branch", "register", "receiver")
    exclude = ("photo",)


class SalePaymentInline(ReadOnlyInline):
    model = SalePayment
    fields = ("method", "amount")


@admin.register(Sale)
class SaleAdmin(ReadOnlyAdmin):
    list_display = ("__str__", "company", "branch", "kind", "total", "sold_at", "source")
    list_filter = ("kind", "source")
    list_select_related = ("company", "branch")
    inlines = (SalePaymentInline,)


@admin.register(DailySales)
class DailySalesAdmin(ReadOnlyAdmin):
    list_display = ("day", "branch", "company", "net", "receipts", "avg_check", "shifts")
    list_select_related = ("branch", "company")
    date_hierarchy = "day"


@admin.register(SalesTarget)
class SalesTargetAdmin(ReadOnlyAdmin):
    list_display = ("month", "company", "branch", "membership", "amount")
    list_select_related = ("company", "branch", "membership")
