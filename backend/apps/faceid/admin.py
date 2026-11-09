"""Django admin for Face ID: platform support adds a terminal here and reads off what to type
into it; owners work in the dashboard's Face ID page, where every change is audited."""

from django import forms
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.faceid import services
from apps.faceid.models import FaceDevice, FaceEvent, FaceIdSettings, FaceLink, new_device_token


class FaceDeviceForm(forms.ModelForm):
    class Meta:
        model = FaceDevice
        fields = ("company", "branch", "name", "direction", "enabled")

    def clean(self):
        data = super().clean()
        company, branch = data.get("company"), data.get("branch")
        if company and branch and branch.company_id != company.pk:
            raise forms.ValidationError({"branch": _("Pick a branch of that company.")})
        return data


@admin.register(FaceDevice)
class FaceDeviceAdmin(admin.ModelAdmin):
    form = FaceDeviceForm
    list_display = (
        "name",
        "company",
        "branch",
        "direction",
        "enabled",
        "last_seen_at",
        "last_event_at",
        "model",
        "ip",
    )
    list_filter = ("enabled", "direction")
    list_select_related = ("company", "branch")
    search_fields = ("name", "company__name", "mac", "serial", "ip")
    readonly_fields = (
        "token",
        "setup_values",
        "setup_https",
        "setup_http",
        "mac",
        "serial",
        "ip",
        "model",
        "last_seen_at",
        "last_heartbeat_at",
        "last_event_at",
        "clock_offset_s",
        "clock_checked_at",
        "created_by",
        "created_at",
    )
    fieldsets = (
        (None, {"fields": ("company", "branch", "name", "direction", "enabled")}),
        (
            _("What to type into the terminal"),
            {"fields": ("setup_values", "setup_https", "setup_http", "token")},
        ),
        (
            _("Learned from the terminal"),
            {
                "fields": (
                    "model",
                    "serial",
                    "mac",
                    "ip",
                    "last_seen_at",
                    "last_heartbeat_at",
                    "last_event_at",
                    "clock_offset_s",
                    "clock_checked_at",
                    "created_by",
                    "created_at",
                )
            },
        ),
    )
    actions = ("new_codes",)

    @admin.display(description=_("HTTPS (port 443)"))
    def setup_https(self, device):
        return services.setup(device)["https"]["url"] if device.pk else "—"

    @admin.display(description=_("Plain HTTP (port 80)"))
    def setup_http(self, device):
        return services.setup(device)["http"]["url"] if device.pk else "—"

    @admin.display(description=_("HTTP Listening fields"))
    def setup_values(self, device):
        if not device.pk:
            return _("Save the terminal first.")
        values = services.setup(device)
        return format_html(
            "{}: <code>{}</code><br>{}: <code>{}</code><br>{}: <code>HTTPS</code> · "
            "<code>443</code> ({}: <code>HTTP</code> · <code>80</code>)<br>{}: <code>{}</code>",
            _("Destination IP or host name"),
            values["host"] or "—",
            _("URL"),
            values["path"],
            _("Protocol and port"),
            _("fallback"),
            _("Heartbeat, minutes"),
            values["heartbeat_minutes"],
        )

    @admin.action(description=_("Give the selected terminals new codes"))
    def new_codes(self, request, queryset):
        for device in queryset:
            device.token = new_device_token()
            device.save(update_fields=["token", "updated_at"])

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(FaceEvent)
class FaceEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_at",
        "device",
        "kind",
        "action",
        "method",
        "employee_no",
        "name_on_device",
        "membership",
        "minor",
    )
    list_filter = ("action", "kind", "method", "device")
    list_select_related = ("device", "membership")
    search_fields = ("employee_no", "name_on_device", "device__name")
    date_hierarchy = "event_at"
    raw_id_fields = ("device", "membership")
    readonly_fields = [field.name for field in FaceEvent._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(FaceLink)
class FaceLinkAdmin(admin.ModelAdmin):
    list_display = ("employee_no", "membership", "company", "auto", "ignored", "created_at")
    list_filter = ("auto", "ignored")
    list_select_related = ("membership", "company")
    search_fields = ("employee_no", "membership__first_name", "membership__last_name")
    raw_id_fields = ("membership", "linked_by")
    readonly_fields = ("number_key",)


@admin.register(FaceIdSettings)
class FaceIdSettingsAdmin(admin.ModelAdmin):
    list_display = ("company", "attendance", "telegram", "notify_employee", "photo_days")
    list_select_related = ("company",)
