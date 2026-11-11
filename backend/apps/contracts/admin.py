"""Django admin for business contracts: for support; owners use the dashboard."""

from django.contrib import admin

from apps.contracts.models import BusinessContract, ContractFile, ContractSettings


class FileInline(admin.TabularInline):
    model = ContractFile
    extra = 0
    fields = ("kind", "label", "size", "created_at")
    readonly_fields = ("kind", "label", "size", "created_at")
    can_delete = False


@admin.register(BusinessContract)
class BusinessContractAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "kind", "branch", "ends_on", "status")
    list_filter = ("kind", "status")
    search_fields = ("title", "number")
    raw_id_fields = ("company", "branch", "counterparty", "responsible", "rule", "created_by")
    readonly_fields = ("reminders_sent",)
    inlines = (FileInline,)


@admin.register(ContractSettings)
class ContractSettingsAdmin(admin.ModelAdmin):
    list_display = ("company", "remind_days", "notice_remind_days")
    raw_id_fields = ("company",)
