"""Owner dashboard endpoints of the owner console.

Outside a company (`owner_urls.py`, `/api/v1/owner/`): `me/`, `permissions/`.
Inside a company (`company_urls.py`, `/api/v1/owner/companies/<id>/`): `pulse/`, `search/`,
`queue/`, `queue/counts/`, `stream/`, `branches/today/`, `saved-views/`.
"""

from datetime import UTC, datetime

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
    inline_serializer,
)
from rest_framework import mixins, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts import company_switch
from apps.accounts.services import approved_memberships
from apps.console import pulse, queries, registry, services
from apps.console.base import OwnerAPIView, OwnerUserAPIView, OwnerViewSet
from apps.console.models import SavedView
from apps.core.models import Language
from apps.members.permissions import Perm

SEARCH_MIN_LENGTH = 2
SEARCH_PER_TYPE = 5
QUEUE_LIMIT = 50
STREAM_LIMIT = 50
MAX_LIMIT = 200


# me/ and permissions/ ----------------------------------------------------------------------


class BranchBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()


class HomeBranchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class RoleBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class OwnerMeCompanySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    logo = serializers.CharField(allow_null=True)
    timezone = serializers.CharField()
    base_currency = serializers.CharField()
    features = serializers.ListField(child=serializers.CharField())
    role = RoleBriefSerializer(allow_null=True)
    is_owner = serializers.BooleanField()
    permissions = serializers.ListField(child=serializers.ChoiceField(Perm.choices))
    branch_scope = serializers.ListField(
        child=serializers.IntegerField(),
        allow_null=True,
        help_text="null: every branch; otherwise the branch ids they see (may be empty).",
    )
    branches = BranchBriefSerializer(many=True)
    home_branch = HomeBranchSerializer(allow_null=True)
    pending = serializers.IntegerField(help_text="Items waiting in Needs you.")
    setup_completed = serializers.BooleanField()
    membership_id = serializers.IntegerField()


class OwnerMeUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    telegram_id = serializers.IntegerField(allow_null=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    username = serializers.CharField(help_text="Telegram username, without @; may be empty.")
    photo_url = serializers.CharField(allow_null=True)


BOT_COMPANY_HELP = (
    "The company the person works in, the same in the bot, the mini app and the dashboard (the "
    "employee `me` has the same field). Set it when the person switches company: the bot follows "
    "and says so in its chat."
)


class OwnerMeSerializer(serializers.Serializer):
    user = OwnerMeUserSerializer(read_only=True)
    language = serializers.ChoiceField(Language.choices)
    bot_company = serializers.IntegerField(allow_null=True, help_text=BOT_COMPANY_HELP)
    companies = OwnerMeCompanySerializer(many=True, read_only=True)


class OwnerMeUpdateSerializer(serializers.Serializer):
    language = serializers.ChoiceField(Language.choices, required=False)
    bot_company = serializers.IntegerField(
        allow_null=True, required=False, help_text=BOT_COMPANY_HELP
    )

    def validate_bot_company(self, value: int | None) -> int | None:
        user = self.context["user"]
        if value is not None and value not in {
            member.company_id for member in approved_memberships(user)
        }:
            raise ValidationError(_("You don't work in that company."))
        return value


class MeView(OwnerUserAPIView):
    """The signed-in person and every company where they may open the dashboard."""

    @extend_schema(responses=OwnerMeSerializer)
    def get(self, request):
        return Response(self._me(request.user))

    @extend_schema(request=OwnerMeUpdateSerializer, responses=OwnerMeSerializer)
    def patch(self, request):
        user = request.user
        serializer = OwnerMeUpdateSerializer(data=request.data, context={"user": user})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            if "language" in data:
                user.language = data["language"]
                user.save(update_fields=["language"])
            if "bot_company" in data:
                # A switch in the dashboard: the bot works in that company from now on.
                before = company_switch.bot_company_id(user)
                user.bot_company_id = data["bot_company"]
                user.save(update_fields=["bot_company"])
                company_switch.follow(user, before)
        return Response(self._me(user))

    def _me(self, user) -> dict:
        return {
            "user": {
                "id": user.pk,
                "telegram_id": user.telegram_id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "full_name": str(user),
                "username": user.telegram_username or "",
                "photo_url": user.photo.url if user.photo else None,
            },
            "language": user.language,
            "bot_company": company_switch.bot_company_id(user),
            "companies": queries.me_companies(user),
        }


class PermissionSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="A permission code (PermissionsEnum).")
    label = serializers.CharField()
    group = serializers.CharField(help_text="The code's prefix, e.g. sales.")


class PermissionsView(OwnerUserAPIView):
    """Every permission a role can grant, for the roles matrix."""

    @extend_schema(responses=PermissionSerializer(many=True))
    def get(self, request):
        return Response(
            [
                {"code": perm.value, "label": str(perm.label), "group": perm.value.split(".")[0]}
                for perm in Perm
            ]
        )


# pulse/ ---------------------------------------------------------------------------------


class PulseSerializer(serializers.Serializer):
    counters = serializers.DictField(child=serializers.IntegerField())
    versions = serializers.DictField(child=serializers.CharField())


class PulseView(OwnerAPIView):
    """Badge counters and version keys; poll every 15 s and refetch what moved."""

    @extend_schema(responses=PulseSerializer)
    def get(self, request, company_id):
        return Response(pulse.snapshot(self.membership))


# search/ --------------------------------------------------------------------------------


class SearchHitSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()
    title = serializers.CharField()
    subtitle = serializers.CharField()
    url = serializers.CharField()


class SearchView(OwnerAPIView):
    """Command palette results: up to 5 per type from every provider you may use."""

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, required=True),
            OpenApiParameter("types", str, description="Comma-separated hit types."),
        ],
        responses=inline_serializer(
            "ConsoleSearchResults", {"results": SearchHitSerializer(many=True)}
        ),
    )
    def get(self, request, company_id):
        q = request.query_params.get("q", "").strip()
        types = [t for t in request.query_params.get("types", "").split(",") if t]
        if len(q) < SEARCH_MIN_LENGTH:
            return Response({"results": []})
        hits = registry.run_search(
            self.membership, q[:100], types=types or None, limit=SEARCH_PER_TYPE
        )
        return Response({"results": registry.to_json(hits)})


# queue/ ---------------------------------------------------------------------------------


class QueueActionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    style = serializers.ChoiceField(registry.QUEUE_STYLES)
    method = serializers.ChoiceField(registry.QUEUE_METHODS)
    endpoint = serializers.CharField(help_text="Relative to /api/v1/owner/companies/{cid}/.")
    body = serializers.DictField()
    needs_reason = serializers.BooleanField()


class QueueItemSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.CharField()
    title = serializers.CharField()
    subtitle = serializers.CharField()
    created_at = serializers.DateTimeField(allow_null=True)
    url = serializers.CharField()
    actions = QueueActionSerializer(many=True)


class QueueKindSerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()


class QueueView(OwnerAPIView):
    """Needs you: approvals from every module, with the buttons that settle them."""

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str),
            OpenApiParameter("limit", int, description=f"Per kind, at most {MAX_LIMIT}."),
        ],
        responses=inline_serializer("ConsoleQueue", {"items": QueueItemSerializer(many=True)}),
    )
    def get(self, request, company_id):
        limit = _limit(request, QUEUE_LIMIT)
        items = registry.queue_items(
            self.membership, kind=request.query_params.get("kind") or None, limit=limit
        )
        return Response({"items": registry.to_json(items)})


class QueueCountsView(OwnerAPIView):
    """How many items wait, per kind."""

    @extend_schema(
        responses=inline_serializer(
            "ConsoleQueueCounts",
            {"total": serializers.IntegerField(), "kinds": QueueKindSerializer(many=True)},
        )
    )
    def get(self, request, company_id):
        counts = registry.queue_counts(self.membership)
        return Response(
            {
                "total": sum(count for _source, count in counts),
                "kinds": [
                    {"kind": source.key, "label": str(source.label), "count": count}
                    for source, count in counts
                ],
            }
        )


# stream/ --------------------------------------------------------------------------------


class ConsolePersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class StreamItemSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    kind = serializers.CharField()
    actor = ConsolePersonSerializer(allow_null=True)
    title = serializers.CharField()
    url = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class StreamView(OwnerAPIView):
    """The live activity stream, newest first."""

    @extend_schema(
        parameters=[
            OpenApiParameter("since", OpenApiTypes.DATETIME, description="Only newer items."),
            OpenApiParameter("limit", int),
        ],
        responses=inline_serializer("ConsoleStream", {"items": StreamItemSerializer(many=True)}),
    )
    def get(self, request, company_id):
        since = _since(request)
        items = registry.run_stream(
            self.membership, since=since, limit=_limit(request, STREAM_LIMIT)
        )
        return Response({"items": registry.to_json(items)})


# branches/today/ ------------------------------------------------------------------------


class BranchTodaySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()
    opens_at = serializers.CharField(allow_null=True, help_text="HH:MM, company time.")
    closes_at = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(queries.BRANCH_STATUSES)
    sales = serializers.DictField(required=False, help_text="contracts.SalesFacts")
    attendance = serializers.DictField(required=False, help_text="contracts.AttendanceFacts")
    tasks = serializers.DictField(required=False, help_text="contracts.TasksFacts")
    finance = serializers.DictField(required=False, help_text="contracts.FinanceFacts")


class BranchesTodayView(OwnerAPIView):
    """Branch cards: status plus the facts of every module you may see."""

    @extend_schema(responses=BranchTodaySerializer(many=True))
    def get(self, request, company_id):
        return Response(queries.branches_today(self.membership, timezone.now()))


# saved-views/ ---------------------------------------------------------------------------


class SavedViewSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = SavedView
        fields = ("id", "module", "name", "state", "is_shared", "order", "owner", "is_mine")
        read_only_fields = ("id", "owner", "is_mine")

    @extend_schema_field(ConsolePersonSerializer)
    def get_owner(self, view: SavedView) -> dict:
        return {"id": view.membership_id, "name": str(view.membership)}

    def get_is_mine(self, view: SavedView) -> bool:
        return view.membership_id == self.context["membership"].pk

    def validate_state(self, value):
        if not isinstance(value, dict):
            raise ValidationError(_("A saved view's state must be an object."))
        return value


class SavedViewViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Your saved views and the ones colleagues shared (`?module=` narrows them). Only your
    own can be changed or deleted."""

    serializer_class = SavedViewSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation has no member
            return SavedView.objects.none()
        views = queries.saved_views(
            self.membership, module=self.request.query_params.get("module") or None
        )
        if self.action in ("update", "partial_update", "destroy"):
            views = views.filter(membership=self.membership)
        return views

    @extend_schema(parameters=[OpenApiParameter("module", str)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.instance = services.create_saved_view(
            by=self.membership, **serializer.validated_data
        )
        self.bump("console.saved_views")

    def perform_update(self, serializer):
        serializer.instance = services.update_saved_view(
            serializer.instance, by=self.membership, **serializer.validated_data
        )
        self.bump("console.saved_views")

    def perform_destroy(self, instance):
        services.delete_saved_view(instance, by=self.membership)
        self.bump("console.saved_views")


def _limit(request, default: int) -> int:
    try:
        value = int(request.query_params.get("limit", default))
    except ValueError:
        raise ValidationError({"limit": [_("Must be a whole number.")]}) from None
    return max(1, min(value, MAX_LIMIT))


def _since(request) -> datetime | None:
    text = request.query_params.get("since")
    if not text:
        return None
    try:
        since = parse_datetime(text)
    except ValueError:
        since = None
    if since is None:
        raise ValidationError({"since": [_("Must be a date and time like 2026-10-20T09:00:00Z.")]})
    return since if timezone.is_aware(since) else since.replace(tzinfo=UTC)
