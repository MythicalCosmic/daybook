"""Django admin for recognition: read the ledger, badges, levels, streaks and kudos."""

from django.contrib import admin

from apps.recognition.models import (
    BadgeAward,
    Kudos,
    LevelUp,
    PointsEntry,
    RecognitionSettings,
    Streak,
)


@admin.register(RecognitionSettings)
class RecognitionSettingsAdmin(admin.ModelAdmin):
    list_display = ("company", "points_enabled", "kudos_enabled", "leaderboard_scope")


@admin.register(PointsEntry)
class PointsEntryAdmin(admin.ModelAdmin):
    list_display = ("membership", "points", "reason", "key", "at")
    list_filter = ("reason",)
    search_fields = ("key", "membership__first_name", "membership__last_name")
    raw_id_fields = ("membership", "by")


@admin.register(BadgeAward)
class BadgeAwardAdmin(admin.ModelAdmin):
    list_display = ("membership", "badge", "ref", "awarded_at", "seen_at", "notified_at")
    list_filter = ("badge",)
    raw_id_fields = ("membership",)


@admin.register(LevelUp)
class LevelUpAdmin(admin.ModelAdmin):
    list_display = ("membership", "number", "reached_at", "seen_at", "notified_at")
    raw_id_fields = ("membership",)


@admin.register(Streak)
class StreakAdmin(admin.ModelAdmin):
    list_display = ("membership", "kind", "current", "best", "last_day", "started_on")
    raw_id_fields = ("membership",)


@admin.register(Kudos)
class KudosAdmin(admin.ModelAdmin):
    list_display = ("from_member", "to_member", "badge", "created_at", "hidden_at")
    list_filter = ("badge",)
    raw_id_fields = ("from_member", "to_member", "task", "hidden_by")
