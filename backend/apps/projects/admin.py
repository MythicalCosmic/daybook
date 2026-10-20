"""Django admin for projects: read-mostly views for support."""

from django.contrib import admin

from apps.projects.models import (
    Label,
    Milestone,
    Project,
    ProjectList,
    ProjectMember,
    ProjectSettings,
    ProjectUpdate,
    TimeEntry,
)


class ListInline(admin.TabularInline):
    model = ProjectList
    extra = 0
    fields = ("name", "position", "is_done", "wip_limit")


class MemberInline(admin.TabularInline):
    model = ProjectMember
    extra = 0
    fields = ("membership", "role")
    raw_id_fields = ("membership",)


class MilestoneInline(admin.TabularInline):
    model = Milestone
    extra = 0
    fields = ("name", "due_on", "status")


class LabelInline(admin.TabularInline):
    model = Label
    extra = 0
    fields = ("name", "color")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "company", "status", "lead", "due_on", "archived_at")
    list_filter = ("status", "company")
    search_fields = ("key", "name")
    raw_id_fields = ("lead", "branch", "client", "created_by")
    readonly_fields = ("created_at", "updated_at", "health", "update_nudged_on")
    inlines = (ListInline, MemberInline, MilestoneInline, LabelInline)


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ("membership", "project", "day", "minutes", "source")
    list_filter = ("source",)
    raw_id_fields = ("membership", "project", "task", "created_by")
    date_hierarchy = "day"


@admin.register(ProjectUpdate)
class ProjectUpdateAdmin(admin.ModelAdmin):
    list_display = ("project", "health", "author", "created_at")
    raw_id_fields = ("project", "author")


@admin.register(ProjectSettings)
class ProjectSettingsAdmin(admin.ModelAdmin):
    list_display = ("company", "weekly_nudge", "nudge_weekday", "at_risk_days", "at_risk_percent")
