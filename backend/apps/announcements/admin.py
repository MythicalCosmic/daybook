from django.contrib import admin
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from apps.announcements.models import Announcement, Receipt


class ReceiptInline(TabularInline):
    model = Receipt
    extra = 0
    fields = ("membership", "read_at", "reminded_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Announcement)
class AnnouncementAdmin(ModelAdmin):
    """Announcements are sent from the bot (/announce); here they can be looked back on."""

    list_display = ("__str__", "company", "author", "created_at", "read_count")
    list_filter = ("company",)
    search_fields = ("text",)
    list_select_related = ("company", "author")
    fields = ("company", "author", "text", "positions", "created_at", "summary_sent_at")
    readonly_fields = fields
    inlines = (ReceiptInline,)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                receipt_count=Count("receipts"),
                read_receipts=Count("receipts", filter=Q(receipts__read_at__isnull=False)),
            )
        )

    @admin.display(description=_("Read"))
    def read_count(self, obj):
        return f"{obj.read_receipts} / {obj.receipt_count}"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
