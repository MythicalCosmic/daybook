"""Notification serializers shared by the owner and the employee endpoints."""

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.console.registry import QUEUE_STYLES
from apps.inbox.models import Notification


class InboxPersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class NotificationActionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    style = serializers.ChoiceField(QUEUE_STYLES)
    needs_reason = serializers.BooleanField()


class NotificationSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    acted_by = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            "id",
            "kind",
            "severity",
            "title",
            "body",
            "url",
            "app_screen",
            "target_type",
            "target_id",
            "actor",
            "actions",
            "data",
            "created_at",
            "read_at",
            "acted_at",
            "acted_by",
        )
        read_only_fields = fields

    @extend_schema_field(InboxPersonSerializer(allow_null=True))
    def get_actor(self, item: Notification) -> dict | None:
        if item.actor is None:
            return None
        return {"id": item.actor_id, "name": str(item.actor)}

    @extend_schema_field(NotificationActionSerializer(many=True))
    def get_actions(self, item: Notification) -> list[dict]:
        """No buttons once someone acted."""
        if item.acted_at is not None:
            return []
        return [
            {
                "key": action["key"],
                "label": action.get("label", action["key"]),
                "style": action.get("style", "default"),
                "needs_reason": bool(action.get("needs_reason")),
            }
            for action in item.actions
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_acted_by(self, item: Notification) -> str | None:
        return str(item.acted_by) if item.acted_by else None


class MarkReadSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), required=False, max_length=500)
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("all") and not attrs.get("ids"):
            raise serializers.ValidationError(_("Give ids or all=true."))
        return attrs


class UpdatedSerializer(serializers.Serializer):
    updated = serializers.IntegerField()


class CountSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    critical = serializers.IntegerField(help_text="How many of the unread ones are critical.")

    class Meta:
        ref_name = "InboxCount"
