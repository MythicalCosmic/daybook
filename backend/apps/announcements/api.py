"""Employee (mini app) endpoints of announcements, mounted at `/api/v1/companies/<id>/`.

GET   announcements/?pinned=true|false   what I received: pinned first, expired hidden
POST  announcements/{id}/read/            I've read it
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.announcements import queries, services
from apps.announcements.models import Announcement
from apps.members.api import IsCompanyMember


class FeedAuthorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class FeedAnnouncementSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    text = serializers.CharField(help_text="Telegram HTML: b, i, u, s, a, code, tg-spoiler.")
    author = serializers.SerializerMethodField()
    is_pinned = serializers.BooleanField(read_only=True)
    read_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = Announcement
        fields = ("id", "title", "text", "author", "sent_at", "is_pinned", "expires_at", "read_at")
        read_only_fields = fields

    def get_title(self, row: Announcement) -> str:
        return queries.title(row)

    @extend_schema_field(FeedAuthorSerializer(allow_null=True))
    def get_author(self, row: Announcement) -> dict | None:
        return {"id": row.author.pk, "name": str(row.author)} if row.author else None


class AnnouncementFeedViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The announcements I received, newest first with pinned ones on top."""

    permission_classes = (IsAuthenticated, IsCompanyMember)
    serializer_class = FeedAnnouncementSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Announcement.objects.none()
        pinned = self.request.query_params.get("pinned")
        flag = True if pinned in ("1", "true") else False if pinned in ("0", "false") else None
        return queries.feed(self.membership, pinned=flag)

    @extend_schema(parameters=[OpenApiParameter("pinned", bool)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=FeedAnnouncementSerializer)
    @action(detail=True, methods=["post"])
    def read(self, request, company_id, pk):
        announcement = get_object_or_404(queries.feed(self.membership), pk=pk)
        services.read(announcement, by=self.membership)
        return Response(self.get_serializer(queries.feed(self.membership).get(pk=pk)).data)
