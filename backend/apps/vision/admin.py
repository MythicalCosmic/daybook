"""Django admin for Ko‘z: platform support looks boxes, cameras, alerts and clips up here. Owners
work in the dashboard's Ko‘z page, where every change is audited; a box is paired with the
dashboard or `manage.py vision_agent`, never here, and its token is never shown."""

from django.contrib import admin

from apps.vision.models import Agent, Alert, Camera, Clip, VisionSettings


@admin.register(VisionSettings)
class VisionSettingsAdmin(admin.ModelAdmin):
    list_display = ("company", "queue_people", "queue_wait_s", "unattended_s", "cooldown_s")
    list_select_related = ("company",)
    search_fields = ("company__name",)


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "company",
        "branch",
        "paired_at",
        "last_seen_at",
        "version",
        "hostname",
        "removed_at",
        "demo",
    )
    list_filter = ("demo",)
    list_select_related = ("company", "branch")
    search_fields = ("name", "company__name", "hostname")
    readonly_fields = (
        "paired_at",
        "pairing_expires_at",
        "hostname",
        "os",
        "version",
        "last_seen_at",
        "removed_at",
        "created_by",
    )
    exclude = ("token_hash", "pairing_hash")

    def has_add_permission(self, request):
        return False


@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "company", "branch", "role", "enabled", "online", "last_seen_at")
    list_filter = ("role", "enabled", "online")
    list_select_related = ("company", "branch")
    search_fields = ("name", "key", "company__name")
    readonly_fields = ("agent", "key", "source", "channel", "width", "height", "last_seen_at")

    def has_add_permission(self, request):
        return False


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("pk", "kind", "state", "company", "branch", "camera", "started_at")
    list_filter = ("kind", "state")
    list_select_related = ("company", "branch", "camera")
    date_hierarchy = "started_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Clip)
class ClipAdmin(admin.ModelAdmin):
    list_display = ("pk", "camera", "state", "reason", "start", "end", "failure")
    list_filter = ("state", "reason")
    list_select_related = ("camera",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
