"""Django admin for owner sign-in: device sessions, read-only; the action ends them."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from apps.signin import services
from apps.signin.models import DeviceSession


@admin.register(DeviceSession)
class DeviceSessionAdmin(ModelAdmin):
    list_display = ("user", "user_agent", "ip", "created_at", "last_seen_at", "revoked_at")
    list_filter = ("revoked_at",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "ip")
    readonly_fields = (
        "user",
        "refresh_jti",
        "previous_jti",
        "rotated_at",
        "user_agent",
        "ip",
        "created_at",
        "last_seen_at",
        "revoked_at",
    )
    actions = ("revoke",)

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("End the selected sessions"))
    def revoke(self, request, queryset):
        for session in queryset.filter(revoked_at__isnull=True):
            services.revoke_session(session)
