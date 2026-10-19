from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.tasks.models import ChecklistItem, Task, TaskComment, TaskTemplate


@admin.register(TaskTemplate)
class TaskTemplateAdmin(ModelAdmin):
    list_display = ("title", "company", "due_time", "proof", "needs_confirmation", "is_active")
    list_filter = ("company", "is_active", "personal", "proof")
    search_fields = ("title", "company__name")
    list_select_related = ("company",)
    filter_horizontal = ("assignees", "positions")
    readonly_fields = ("created_by", "created_at", "updated_at")


class ChecklistInline(TabularInline):
    model = ChecklistItem
    extra = 0


class CommentInline(TabularInline):
    model = TaskComment
    extra = 0
    readonly_fields = ("author", "created_at")


@admin.register(Task)
class TaskAdmin(ModelAdmin):
    list_display = ("title", "company", "kind", "assignee", "status", "due_at")
    list_filter = ("company", "status", "kind")
    search_fields = ("title", "assignee__first_name", "assignee__last_name")
    list_select_related = ("company", "assignee__user")
    readonly_fields = (
        "kind",
        "template",
        "for_date",
        "created_by",
        "started_at",
        "completed_at",
        "confirmed_at",
        "confirmed_by",
        "created_at",
        "updated_at",
    )
    raw_id_fields = ("assignee",)
    inlines = (ChecklistInline, CommentInline)
