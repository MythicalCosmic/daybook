from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from apps.audit.admin import AuditedAdmin
from apps.core.exceptions import DomainError
from apps.timeoff import services
from apps.timeoff.models import Holiday, TimeOff


class HolidayInline(TabularInline):
    model = Holiday
    extra = 0
    fields = ("date", "name")


@admin.register(Holiday)
class HolidayAdmin(AuditedAdmin, ModelAdmin):
    list_display = ("date", "name", "company")
    list_filter = ("company",)
    date_hierarchy = "date"


@admin.register(TimeOff)
class TimeOffAdmin(ModelAdmin):
    list_display = ("membership", "company", "first_day", "last_day", "status", "decided_by")
    list_filter = ("company", "status")
    search_fields = ("membership__first_name", "membership__last_name", "reason")
    list_select_related = ("membership", "company", "decided_by")
    readonly_fields = ("status", "decided_by", "decided_at", "created_at", "updated_at")
    actions = ("approve_selected", "reject_selected")

    # Decisions go through the service, so people hear about them and the audit log keeps them.
    def has_add_permission(self, request):
        return False

    @admin.action(description=_("Approve selected time off"))
    def approve_selected(self, request, queryset):
        self._decide(request, queryset, approve=True)

    @admin.action(description=_("Reject selected time off"))
    def reject_selected(self, request, queryset):
        self._decide(request, queryset, approve=False)

    def _decide(self, request, queryset, *, approve: bool) -> None:
        done = 0
        for time_off in queryset.filter(status=TimeOff.Status.PENDING):
            try:
                services.decide(time_off.pk, approve, by=request.user)
            except (DomainError, PermissionDenied) as exc:
                self.message_user(request, f"{time_off}: {exc}", level="warning")
            else:
                done += 1
        self.message_user(request, _("Decided: %(count)d") % {"count": done})
