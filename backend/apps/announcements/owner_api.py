"""Owner dashboard endpoints of announcements; routed in `owner_urls.py`.

    GET   announcements/?status=&q=&pinned=      the list with read rates (paginated)
    POST  announcements/                         publish now or schedule {text_html, …}
    GET   announcements/{id}/  ·  PATCH (scheduled only)
    GET   announcements/{id}/receipts/?state=read|unread&q=
    POST  announcements/{id}/remind/ · cancel/ · pin/ {pinned_until} · unpin/
    GET   announcements/audience/?position=&branch=   the composer's live count
    GET   announcements/stats/

Everything needs `announcements.send`.
"""

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
    inline_serializer,
)
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.announcements import queries, services, telegram_html
from apps.announcements.models import Announcement, Receipt
from apps.companies.models import Branch
from apps.console.base import OwnerViewSet
from apps.members.models import Position
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, person_ref

PULSE = "announcements.announcements"


class PersonRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class NamedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class OwnerAnnouncementSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    text = serializers.CharField(read_only=True, help_text="Telegram HTML.")
    author = serializers.SerializerMethodField()
    positions = serializers.SerializerMethodField()
    branches = serializers.SerializerMethodField()
    recipients_count = serializers.IntegerField(read_only=True)
    read_count = serializers.IntegerField(read_only=True)
    read_rate = serializers.SerializerMethodField()
    is_pinned = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = (
            "id",
            "title",
            "text",
            "status",
            "author",
            "positions",
            "branches",
            "created_at",
            "scheduled_for",
            "sent_at",
            "pinned_until",
            "expires_at",
            "is_pinned",
            "is_expired",
            "recipients_count",
            "read_count",
            "read_rate",
        )
        read_only_fields = fields

    def get_title(self, row: Announcement) -> str:
        return queries.title(row)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_author(self, row: Announcement) -> dict | None:
        return person_ref(row.author)

    @extend_schema_field(NamedSerializer(many=True))
    def get_positions(self, row: Announcement) -> list[dict]:
        return [{"id": p.pk, "name": p.name} for p in row.positions.all()]

    @extend_schema_field(NamedSerializer(many=True))
    def get_branches(self, row: Announcement) -> list[dict]:
        return [branch_ref(b) for b in row.branches.all()]

    def get_read_rate(self, row: Announcement) -> str | None:
        return queries.rate(row.read_count, row.recipients_count)

    def get_is_pinned(self, row: Announcement) -> bool:
        return bool(row.pinned_until and row.pinned_until > timezone.now())

    def get_is_expired(self, row: Announcement) -> bool:
        return bool(row.expires_at and row.expires_at <= timezone.now())


class PublishSerializer(serializers.Serializer):
    text_html = serializers.CharField(help_text="The composer's HTML; stored as Telegram HTML.")
    position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    scheduled_for = serializers.DateTimeField(required=False, allow_null=True)
    pinned_until = serializers.DateTimeField(required=False, allow_null=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class UpdateSerializer(PublishSerializer):
    text_html = serializers.CharField(required=False)


class PinSerializer(serializers.Serializer):
    pinned_until = serializers.DateTimeField()


class ReceiptSerializer(serializers.ModelSerializer):
    member = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    home_branch = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = ("id", "member", "position", "home_branch", "read_at", "reminded_at")
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer)
    def get_member(self, row: Receipt) -> dict:
        return person_ref(row.membership)

    def get_position(self, row: Receipt) -> str | None:
        return row.membership.position.name if row.membership.position_id else None

    @extend_schema_field(NamedSerializer(allow_null=True))
    def get_home_branch(self, row: Receipt) -> dict | None:
        return branch_ref(row.membership.home_branch)


class AnnouncementViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, OwnerViewSet
):
    """Announcements with their read rates, the composer and the follow-up actions."""

    perm = Perm.ANNOUNCE
    serializer_class = OwnerAnnouncementSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Announcement.objects.none()
        rows = queries.for_console(self.membership).prefetch_related("positions", "branches")
        if self.action != "list":
            return rows
        params = self.request.query_params
        statuses = [s for s in params.getlist("status") if s in Announcement.Status.values]
        if statuses:
            rows = rows.filter(status__in=statuses)
        now = timezone.now()
        if params.get("pinned") in ("1", "true"):
            rows = rows.filter(pinned_until__gt=now)
        if q := params.get("q", "").strip():
            rows = rows.filter(text__icontains=q)
        if author := params.get("author"):
            rows = rows.filter(author_id=author if author.isdigit() else 0)
        return rows.order_by("-created_at", "-pk")

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, many=True),
            OpenApiParameter("q", str),
            OpenApiParameter("pinned", bool),
            OpenApiParameter("author", int),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=PublishSerializer, responses={201: OwnerAnnouncementSerializer})
    def create(self, request, company_id):
        serializer = PublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _check_audience(self.company, data)
        announcement = services.publish(
            self.membership,
            telegram_html.from_editor(data["text_html"]),
            data.get("position_ids", []),
            branch_ids=data.get("branch_ids", []),
            scheduled_for=data.get("scheduled_for"),
            pinned_until=data.get("pinned_until"),
            expires_at=data.get("expires_at"),
        )
        self.bump(PULSE)
        fresh = self.get_queryset().get(pk=announcement.pk)
        return Response(self.get_serializer(fresh).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=UpdateSerializer, responses=OwnerAnnouncementSerializer)
    def partial_update(self, request, company_id, pk):
        announcement = self.get_object()
        serializer = UpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _check_audience(self.company, data)
        services.update_scheduled(
            announcement,
            by=self.membership,
            text=telegram_html.from_editor(data["text_html"]) if "text_html" in data else None,
            position_ids=data.get("position_ids"),
            branch_ids=data.get("branch_ids"),
            scheduled_for=data.get("scheduled_for"),
            pinned_until=data.get("pinned_until", services.UNSET),
            expires_at=data.get("expires_at", services.UNSET),
        )
        self.bump(PULSE)
        return Response(self.get_serializer(self.get_queryset().get(pk=announcement.pk)).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("state", str, description="read or unread"),
            OpenApiParameter("q", str),
        ],
        responses=ReceiptSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def receipts(self, request, company_id, pk):
        announcement = self.get_object()
        rows = services.visible_receipts(announcement, self.membership).select_related(
            "membership__user", "membership__position", "membership__home_branch"
        )
        state = request.query_params.get("state")
        if state == "read":
            rows = rows.filter(read_at__isnull=False)
        elif state == "unread":
            rows = rows.filter(read_at__isnull=True)
        if q := request.query_params.get("q", "").strip():
            rows = rows.filter(
                Q(membership__first_name__icontains=q) | Q(membership__last_name__icontains=q)
            )
        rows = rows.order_by("read_at", "membership__first_name", "membership__last_name")
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(ReceiptSerializer(page, many=True).data)

    @extend_schema(
        request=None,
        responses=inline_serializer(
            "AnnouncementsReminded", {"reminded": serializers.IntegerField()}
        ),
    )
    @action(detail=True, methods=["post"])
    def remind(self, request, company_id, pk):
        count = services.remind_unread(self.get_object(), by=self.membership)
        self.bump(PULSE)
        return Response({"reminded": count})

    @extend_schema(request=None, responses=OwnerAnnouncementSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk):
        announcement = services.cancel_scheduled(self.get_object(), by=self.membership)
        self.bump(PULSE)
        return Response(self.get_serializer(self.get_queryset().get(pk=announcement.pk)).data)

    @extend_schema(request=PinSerializer, responses=OwnerAnnouncementSerializer)
    @action(detail=True, methods=["post"])
    def pin(self, request, company_id, pk):
        serializer = PinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        announcement = services.pin(
            self.get_object(), by=self.membership, until=serializer.validated_data["pinned_until"]
        )
        self.bump(PULSE)
        return Response(self.get_serializer(self.get_queryset().get(pk=announcement.pk)).data)

    @extend_schema(request=None, responses=OwnerAnnouncementSerializer)
    @action(detail=True, methods=["post"])
    def unpin(self, request, company_id, pk):
        announcement = services.unpin(self.get_object(), by=self.membership)
        self.bump(PULSE)
        return Response(self.get_serializer(self.get_queryset().get(pk=announcement.pk)).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("position", int, many=True),
            OpenApiParameter("branch", int, many=True),
        ],
        responses=inline_serializer(
            "AnnouncementsAudience",
            {"count": serializers.IntegerField(), "sample": NamedSerializer(many=True)},
        ),
    )
    @action(detail=False, methods=["get"])
    def audience(self, request, company_id):
        return Response(
            queries.audience_count(
                self.company,
                self.membership,
                _ints(request.query_params.getlist("position")),
                _ints(request.query_params.getlist("branch")),
            )
        )

    @extend_schema(
        responses=inline_serializer(
            "AnnouncementsStats",
            {
                "sent_30d": serializers.IntegerField(),
                "read_rate_30d": serializers.CharField(allow_null=True),
                "scheduled": serializers.IntegerField(),
                "pinned": serializers.IntegerField(),
                "unread_people_30d": serializers.IntegerField(),
            },
        )
    )
    @action(detail=False, methods=["get"])
    def stats(self, request, company_id):
        return Response(queries.stats(self.membership, timezone.now()))


def _check_audience(company, data: dict) -> None:
    """Every position and branch id must be the company's: one dropped silently could widen
    the audience to everyone."""
    for key, model, message in (
        ("position_ids", Position, _("Pick positions of this company.")),
        ("branch_ids", Branch, _("Pick branches of this company.")),
    ):
        ids = set(data.get(key) or [])
        if ids and model.objects.for_company(company).filter(pk__in=ids).count() != len(ids):
            raise ValidationError({key: [message]})


def _ints(values) -> list[int]:
    found = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                raise ValidationError({"id": [_("Must be a whole number.")]})
            found.append(int(part))
    return found
