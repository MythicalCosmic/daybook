"""Django admin for learning: read-mostly views for support."""

from django.contrib import admin

from apps.learning import models


@admin.register(models.Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "status", "mandatory", "due_days", "renew_months")
    list_filter = ("status", "mandatory")
    search_fields = ("title",)


@admin.register(models.Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "status", "source", "duration_seconds")
    list_filter = ("status", "source")
    search_fields = ("title",)


@admin.register(models.Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("pk", "company", "state", "original_name", "size_bytes", "duration_seconds")
    list_filter = ("state",)


@admin.register(models.Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "status", "mode", "question_count", "pass_percent")
    list_filter = ("status", "mode")
    search_fields = ("title",)


@admin.register(models.Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("pk", "company", "kind", "state", "source", "topic")
    list_filter = ("kind", "state", "source")
    search_fields = ("text",)


@admin.register(models.Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("course", "membership", "cycle", "state", "due_at", "completed_at")
    list_filter = ("state", "source")


@admin.register(models.Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("quiz", "membership", "number", "state", "percent", "passed", "started_at")
    list_filter = ("state", "passed")


@admin.register(models.RegularCheck)
class RegularCheckAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "state", "every", "next_run_at")
    list_filter = ("state", "every")
