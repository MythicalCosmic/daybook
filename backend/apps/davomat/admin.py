"""Django admin for Davomat, for platform support: the settings row (the bot's token is never
shown, only whether one is set), employees and link codes, read-only where the owner's own
pages make every change (audited)."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.davomat.models import DavomatSettings, Employee, TelegramLink


@admin.register(DavomatSettings)
class DavomatSettingsAdmin(admin.ModelAdmin):
    list_display = ("company", "product_name", "bot_username", "bot_status", "token_version")
    fields = (
        "company",
        "product_name",
        "auto_create_employees",
        "token_set",
        "bot_username",
        "bot_name",
        "bot_status",
        "bot_checked_at",
        "token_version",
    )
    readonly_fields = (
        "company",
        "token_set",
        "bot_username",
        "bot_name",
        "bot_status",
        "bot_checked_at",
        "token_version",
    )

    @admin.display(boolean=True, description=_("Token set"))
    def token_set(self, row: DavomatSettings) -> bool:
        return bool(row.bot_token)

    def has_add_permission(self, request):
        return False


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("membership", "company", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("membership__first_name", "membership__last_name")
    readonly_fields = ("company", "membership", "source", "created_by", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(TelegramLink)
class TelegramLinkAdmin(admin.ModelAdmin):
    list_display = ("membership", "company", "expires_at", "used_at")
    readonly_fields = (
        "company",
        "membership",
        "expires_at",
        "used_at",
        "telegram_id",
        "created_by",
        "created_at",
    )
    exclude = ("code_hash",)

    def has_add_permission(self, request):
        return False
