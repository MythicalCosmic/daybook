"""Django admin for the knowledge base (read-mostly: pages are written in the dashboard)."""

from django.contrib import admin

from apps.knowledge.models import Page, PageAck, PageVersion, Space


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "audience_all", "position", "archived_at")
    list_filter = ("audience_all",)
    search_fields = ("name", "company__name")
    filter_horizontal = ("positions",)


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "space", "company", "published", "require_ack", "version")
    list_filter = ("published", "require_ack")
    search_fields = ("title", "company__name")
    readonly_fields = ("body", "body_text", "version", "ack_version", "reminded_version")
    raw_id_fields = ("space", "parent", "updated_by", "created_by")


@admin.register(PageVersion)
class PageVersionAdmin(admin.ModelAdmin):
    list_display = ("page", "version", "created_by", "created_at")
    raw_id_fields = ("page", "created_by")


@admin.register(PageAck)
class PageAckAdmin(admin.ModelAdmin):
    list_display = ("page", "membership", "version", "at")
    raw_id_fields = ("page", "membership")
