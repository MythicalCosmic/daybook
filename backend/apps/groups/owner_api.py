"""Owner endpoints of Telegram groups (docs/PLAN-OWNER.md §4.4), all needing `groups.manage`.

GET   groups/                    connected groups, what each gets, and how to add one
PATCH groups/{id}/               {events, position_ids, branch_ids} (each optional)
POST  groups/{id}/disconnect/    the bot stops posting there
"""

from django.conf import settings
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.companies.models import Branch
from apps.console.base import OwnerViewSet
from apps.groups import services
from apps.groups.models import EVENT_FEATURES, GroupEvent, TelegramGroup, available_events
from apps.members.models import Position
from apps.members.permissions import Perm

# Events that tell about one person, so a positions filter means something for them.
PERSON_EVENTS = (GroupEvent.DAILY_DONE, GroupEvent.TASKS_DONE, GroupEvent.LATE, GroupEvent.MEMBERS)


class EventSerializer(serializers.Serializer):
    key = serializers.ChoiceField(GroupEvent.choices)
    label = serializers.CharField()
    feature = serializers.CharField(allow_null=True, help_text="The module it belongs to.")
    on = serializers.BooleanField()
    available = serializers.BooleanField(help_text="False when its module is switched off.")


class RefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class GroupSerializer(serializers.ModelSerializer):
    events = serializers.SerializerMethodField()
    positions = serializers.SerializerMethodField()
    branches = serializers.SerializerMethodField()
    linked_by = serializers.SerializerMethodField()
    connected_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = TelegramGroup
        fields = (
            "id",
            "title",
            "chat_id",
            "is_active",
            "events",
            "positions",
            "branches",
            "linked_by",
            "connected_at",
            "updated_at",
        )

    def get_events(self, group: TelegramGroup) -> list[dict]:
        company = group.company
        offered = {str(event) for event in available_events(company, group.events)}
        return [
            {
                "key": event.value,
                "label": str(event.label),
                "feature": EVENT_FEATURES.get(event),
                "on": event.value in group.events,
                # Listed but unavailable: chosen earlier, its module switched off since.
                "available": event not in EVENT_FEATURES
                or company.has_feature(EVENT_FEATURES[event]),
            }
            for event in GroupEvent
            if event.value in offered
        ]

    def get_positions(self, group: TelegramGroup) -> list[dict]:
        return [{"id": p.pk, "name": p.name} for p in group.positions.all()]

    def get_branches(self, group: TelegramGroup) -> list[dict]:
        return [{"id": b.pk, "name": b.name} for b in group.branches.all()]

    def get_linked_by(self, group: TelegramGroup) -> dict | None:
        member = group.linked_by
        return {"id": member.pk, "name": str(member)} if member else None


class GroupUpdateSerializer(serializers.Serializer):
    events = serializers.ListField(
        child=serializers.ChoiceField(GroupEvent.choices), required=False
    )
    position_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    branch_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


def connect_link() -> str:
    """Telegram's "add this bot to a group" link; adding it as a manager connects the group."""
    username = settings.EMPLOYEE_BOT_USERNAME
    return f"https://t.me/{username}?startgroup=connect" if username else ""


class GroupViewSet(mixins.ListModelMixin, OwnerViewSet):
    """The company's Telegram groups and what the bot posts in each."""

    serializer_class = GroupSerializer
    pagination_class = None
    perm = Perm.GROUPS_MANAGE

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TelegramGroup.objects.none()
        return (
            TelegramGroup.objects.for_company(self.company)
            .select_related("company", "linked_by", "linked_by__user")
            .prefetch_related(
                Prefetch("positions", queryset=Position.objects.order_by("order", "name")),
                Prefetch("branches", queryset=Branch.objects.order_by("order", "name")),
            )
            .order_by("-is_active", "title")
        )

    @extend_schema(
        responses=inline_serializer(
            "GroupsList",
            {
                "results": GroupSerializer(many=True),
                "connect_link": serializers.CharField(
                    help_text="Opens Telegram's group picker; empty without a bot username."
                ),
                "bot_username": serializers.CharField(),
                "person_events": serializers.ListField(child=serializers.CharField()),
                "options": inline_serializer(
                    "GroupsFilterOptions",
                    {"positions": RefSerializer(many=True), "branches": RefSerializer(many=True)},
                ),
            },
        )
    )
    def list(self, request, company_id):
        rows = GroupSerializer(self.get_queryset(), many=True).data
        positions = Position.objects.for_company(self.company).filter(is_active=True)
        branches = Branch.objects.for_company(self.company).filter(is_active=True)
        return Response(
            {
                "results": rows,
                "connect_link": connect_link(),
                "bot_username": settings.EMPLOYEE_BOT_USERNAME,
                "person_events": [str(event) for event in PERSON_EVENTS],
                "options": {
                    "positions": [
                        {"id": p.pk, "name": p.name} for p in positions.order_by("order", "name")
                    ],
                    "branches": [
                        {"id": b.pk, "name": b.name} for b in branches.order_by("order", "name")
                    ],
                },
            }
        )

    @extend_schema(request=GroupUpdateSerializer, responses=GroupSerializer)
    def partial_update(self, request, company_id, pk):
        group = self.get_object()
        serializer = GroupUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.update_settings(group, by=self.membership, **serializer.validated_data)
        self.bump("groups.groups")
        return Response(GroupSerializer(self.get_queryset().get(pk=group.pk)).data)

    @extend_schema(request=None, responses=GroupSerializer)
    @action(detail=True, methods=["post"])
    def disconnect(self, request, company_id, pk):
        group = self.get_object()
        services.disconnect(group, by=self.membership.user)
        self.bump("groups.groups")
        return Response(GroupSerializer(self.get_queryset().get(pk=group.pk)).data)
