"""Owner dashboard endpoints of the inbox: `inbox/…` and `notification-preferences/`."""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.inbox import queries, registry, services
from apps.inbox.models import Notification
from apps.inbox.serializers import (
    CountSerializer,
    MarkReadSerializer,
    NotificationSerializer,
    UpdatedSerializer,
)


class ActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


class InboxViewSet(mixins.ListModelMixin, OwnerViewSet):
    """Your in-app notifications in this company."""

    serializer_class = NotificationSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        tab = self.request.query_params.get("tab", "all")
        if tab not in queries.TABS:
            raise ValidationError({"tab": [_("Use unread or all.")]})
        return queries.inbox(self.membership, tab=tab)

    @extend_schema(parameters=[OpenApiParameter("tab", str, enum=list(queries.TABS))])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=CountSerializer)
    @action(detail=False, url_path="unread-count")
    def unread_count(self, request, company_id):
        return Response({"count": queries.unread_count(self.membership)})

    @extend_schema(request=MarkReadSerializer, responses=UpdatedSerializer)
    @action(detail=False, methods=["post"])
    def read(self, request, company_id):
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = services.mark_read(
            self.membership,
            ids=serializer.validated_data.get("ids", []),
            everything=serializer.validated_data["all"],
        )
        return Response({"updated": count})

    @extend_schema(request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, company_id, pk):
        try:
            item = services.archive(self.membership, int(pk))
        except Notification.DoesNotExist:
            raise NotFound from None
        return Response(NotificationSerializer(item).data)

    @extend_schema(
        request=ActionSerializer,
        responses=inline_serializer(
            "InboxActionResult",
            {"message": serializers.CharField(), "notification": NotificationSerializer()},
        ),
    )
    @action(detail=True, methods=["post"], url_path=r"actions/(?P<key>[a-z][a-z0-9_]*)")
    def act(self, request, company_id, pk, key):
        """Press a notification's button: the module's handler decides (and checks its own
        permission)."""
        serializer = ActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not queries.inbox(self.membership).filter(pk=pk).exists():
            raise NotFound
        try:
            message = services.run_action(
                int(pk), key, by=self.membership, reason=serializer.validated_data["reason"]
            )
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc) or None) from exc
        item = Notification.objects.select_related("actor", "acted_by").get(pk=pk)
        return Response(
            {"message": message or _("Done."), "notification": NotificationSerializer(item).data}
        )


class PreferenceSerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField(read_only=True)
    audience = serializers.CharField(read_only=True)
    severity = serializers.CharField(read_only=True)
    in_app_available = serializers.BooleanField(read_only=True)
    in_app = serializers.BooleanField()
    telegram = serializers.BooleanField()

    def validate_kind(self, value):
        if value not in registry.KINDS:
            raise ValidationError(_("Unknown notification kind."))
        return value


class NotificationPreferencesView(OwnerAPIView):
    """Per kind: show in the dashboard and/or send to Telegram."""

    @extend_schema(responses=PreferenceSerializer(many=True))
    def get(self, request, company_id):
        return Response(queries.preferences(self.membership))

    @extend_schema(
        request=PreferenceSerializer(many=True), responses=PreferenceSerializer(many=True)
    )
    def put(self, request, company_id):
        serializer = PreferenceSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        services.set_preferences(self.membership, serializer.validated_data)
        return Response(queries.preferences(self.membership))
