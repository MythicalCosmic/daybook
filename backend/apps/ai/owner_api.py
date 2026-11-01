"""Owner dashboard endpoints of the AI features; routed in `owner_urls.py` (contract §5).

    GET  ai/status/                      dashboard.access: AI on?, Claude and speech, features,
                                         the month's budget (ai.configure only)
    GET/PATCH ai/settings/               ai.configure
    POST ai/settings/enable/             ai.configure, {"accept_terms": true}: the owner's consent
    POST ai/settings/disable/            ai.configure
    GET/POST ai/task-drafts/             the voice notes; POST as in the mini app (source dashboard)
    GET  ai/task-drafts/<id>/ · POST …/apply/ · POST …/discard/

Drafts: people with ai.configure or tasks.view_all see the company's (in their branches),
everyone else their own; only the author creates a draft's tasks or throws it away.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.ai import agents, availability, conf, queries, services, speech
from apps.ai.agents import photo_checker
from apps.ai.api import CREATE_ERRORS, DRAFT_RELATIONS, DraftEndpoints
from apps.ai.models import AIDraft, AISettings
from apps.ai.serializers import (
    AIApplyResultSerializer,
    AIDraftApplySerializer,
    AIDraftCreateSerializer,
    AIDraftSerializer,
)
from apps.console.base import OwnerAPIView, OwnerGenericAPIView
from apps.core.api import Pagination
from apps.members import scope
from apps.members.permissions import Perm

CONFIGURE = Perm.AI_CONFIGURE
# Open dashboards refetch the AI status and settings when this moves (apps.console.pulse).
PULSE_SETTINGS = "ai.settings"


class AIBudgetSerializer(serializers.Serializer):
    monthly_usd = serializers.DecimalField(max_digits=10, decimal_places=2)
    spent_usd = serializers.DecimalField(max_digits=10, decimal_places=2)
    resets_on = serializers.DateField()


class AIFeaturesSerializer(serializers.Serializer):
    voice = serializers.BooleanField()
    smart_text = serializers.BooleanField()
    chat = serializers.BooleanField()
    photo_checker = serializers.BooleanField()


class AIOwnerStatusSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    can_configure = serializers.BooleanField()
    claude = serializers.ChoiceField(
        ["connected", "not_configured", "fake", "blocked", "budget_reached", "unavailable"]
    )
    speech = serializers.ChoiceField(["ready", "not_configured", "fake"])
    features = AIFeaturesSerializer()
    budget = AIBudgetSerializer(allow_null=True, help_text="Only for ai.configure.")


class AISettingsSerializer(serializers.ModelSerializer):
    enabled_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AISettings
        fields = (
            "enabled",
            "enabled_by_name",
            "enabled_at",
            "platform_blocked",
            "monthly_budget_usd",
            "share_task_text",
            "share_finance",
            "share_salaries",
            "voice_retention_days",
            "member_daily_drafts",
        )
        read_only_fields = ("enabled", "enabled_by_name", "enabled_at", "platform_blocked")

    def get_enabled_by_name(self, row: AISettings) -> str:
        if row.enabled_by is None:
            return ""
        return row.enabled_by.get_full_name() or str(row.enabled_by)


class AIEnableSerializer(serializers.Serializer):
    accept_terms = serializers.BooleanField()


def owner_status(membership) -> dict:
    company = membership.company
    can_configure = membership.has_perm(CONFIGURE)
    voice = services.voice_status(membership)
    claude = availability.claude_state(company)
    budget = None
    if can_configure:
        row = conf.get_settings(company)
        budget = {
            "monthly_usd": f"{row.monthly_budget_usd:.2f}",
            "spent_usd": f"{availability.to_usd(availability.month_spend_micro(company)):.2f}",
            "resets_on": availability.resets_on(company).isoformat(),
        }
    return {
        "enabled": conf.ai_on(company),
        "can_configure": can_configure,
        "claude": claude,
        "speech": speech.status(),
        "features": {
            "voice": voice.voice,
            "smart_text": voice.smart_text,
            "chat": False,  # Ask AI arrives with the chat backend
            "photo_checker": conf.ai_on(company)
            and agents.state_of(company, photo_checker.KEY).enabled
            and (availability.fake() or availability.status(company).available),
        },
        "budget": budget,
    }


class StatusView(OwnerAPIView):
    perm = None

    @extend_schema(responses=AIOwnerStatusSerializer)
    def get(self, request, company_id):
        return Response(owner_status(self.membership))


class SettingsView(OwnerAPIView):
    perm = CONFIGURE

    @extend_schema(responses=AISettingsSerializer)
    def get(self, request, company_id):
        return Response(AISettingsSerializer(conf.get_settings(self.company)).data)

    @extend_schema(request=AISettingsSerializer, responses=AISettingsSerializer)
    def patch(self, request, company_id):
        form = AISettingsSerializer(
            conf.get_settings(self.company), data=request.data, partial=True
        )
        form.is_valid(raise_exception=True)
        try:
            row = services.update_settings(self.company, by=self.membership, **form.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        self.bump(PULSE_SETTINGS)
        return Response(AISettingsSerializer(row).data)


class EnableView(OwnerAPIView):
    perm = CONFIGURE

    @extend_schema(request=AIEnableSerializer, responses=AIOwnerStatusSerializer)
    def post(self, request, company_id):
        form = AIEnableSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        if not form.validated_data["accept_terms"]:
            raise ValidationError({"accept_terms": ["Accept the terms to turn AI on."]})
        services.enable_ai(self.company, by=self.membership)
        self.company.refresh_from_db()
        self.membership.company = self.company
        self.bump(PULSE_SETTINGS)
        return Response(owner_status(self.membership))


class DisableView(OwnerAPIView):
    perm = CONFIGURE

    @extend_schema(request=None, responses=AIOwnerStatusSerializer)
    def post(self, request, company_id):
        services.disable_ai(self.company, by=self.membership)
        self.bump(PULSE_SETTINGS)
        return Response(owner_status(self.membership))


class OwnerDraftEndpoints(DraftEndpoints):
    source = AIDraft.Source.DASHBOARD

    def visible_drafts(self) -> QuerySet[AIDraft]:
        member = self.membership
        drafts = AIDraft.objects.filter(company_id=member.company_id)
        if member.has_perm(CONFIGURE) or member.has_perm(Perm.TASKS_VIEW_ALL):
            mine = drafts.filter(created_by=member)
            scoped = scope.restrict(drafts, scope.branch_ids(member), field="created_by__branches")
            return drafts.filter(pk__in=scoped.values("pk")) | mine
        return drafts.filter(created_by=member)


class TaskDraftListView(OwnerDraftEndpoints, OwnerGenericAPIView):
    perm = None
    pagination_class = Pagination
    serializer_class = AIDraftSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, description="Comma-separated statuses."),
            OpenApiParameter("source", str, description="bot, owner_bot, miniapp or dashboard."),
            OpenApiParameter("author", int, description="The author's membership id."),
        ],
        responses=AIDraftSerializer(many=True),
    )
    def get(self, request, company_id):
        drafts = self.visible_drafts().select_related(*DRAFT_RELATIONS).order_by("-created_at")
        if statuses := request.query_params.get("status"):
            drafts = drafts.filter(status__in=statuses.split(","))
        if source := request.query_params.get("source"):
            drafts = drafts.filter(source=source)
        if (author := request.query_params.get("author", "")).isdigit():
            drafts = drafts.filter(created_by_id=int(author))
        page = self.paginate_queryset(drafts)
        return self.get_paginated_response(
            AIDraftSerializer(page, many=True, context={"request": request}).data
        )

    @extend_schema(
        request={
            "multipart/form-data": AIDraftCreateSerializer,
            "application/json": AIDraftCreateSerializer,
        },
        responses={**CREATE_ERRORS, 202: AIDraftSerializer},
    )
    def post(self, request, company_id):
        return self.create_draft(request)


class TaskDraftDetailView(OwnerDraftEndpoints, OwnerAPIView):
    perm = None

    @extend_schema(responses=AIDraftSerializer)
    def get(self, request, company_id, draft_id):
        draft = self.get_draft(draft_id)
        return Response(AIDraftSerializer(draft, context={"request": request}).data)


class TaskDraftApplyView(OwnerDraftEndpoints, OwnerAPIView):
    perm = None

    @extend_schema(request=AIDraftApplySerializer, responses=AIApplyResultSerializer)
    def post(self, request, company_id, draft_id):
        return self.apply(request, draft_id)


class TaskDraftDiscardView(OwnerDraftEndpoints, OwnerAPIView):
    perm = None

    @extend_schema(request=None, responses={204: None})
    def post(self, request, company_id, draft_id):
        return self.discard(request, draft_id)


# Agents and their activity ----------------------------------------------------------------------


class AIAgentOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class AIAgentFieldSerializer(serializers.Serializer):
    key = serializers.CharField()
    type = serializers.ChoiceField(["bool", "int", "time", "choice"])
    label = serializers.CharField()
    help = serializers.CharField(allow_blank=True)
    min = serializers.IntegerField(required=False)
    max = serializers.IntegerField(required=False)
    unit = serializers.CharField(required=False)
    options = AIAgentOptionSerializer(many=True, required=False)


class AIAgentStatsSerializer(serializers.Serializer):
    today = serializers.IntegerField()
    week = serializers.IntegerField()


class AIAgentSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField(help_text="A lucide icon name.")
    enabled = serializers.BooleanField()
    needs_claude = serializers.BooleanField()
    available = serializers.BooleanField()
    unavailable_reason = serializers.ChoiceField(["", "needs_claude", "needs_speech", "ai_off"])
    schedule = serializers.CharField()
    running = serializers.BooleanField()
    last_run_at = serializers.DateTimeField(allow_null=True)
    next_run_at = serializers.DateTimeField(allow_null=True)
    stats = AIAgentStatsSerializer()
    config = serializers.DictField()
    fields = AIAgentFieldSerializer(many=True)


class AIAgentUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    config = serializers.DictField(required=False)


class AIQueuedSerializer(serializers.Serializer):
    queued = serializers.BooleanField()


class AIActivityActorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo = serializers.CharField(allow_null=True)


class AIActivitySubjectSerializer(serializers.Serializer):
    type = serializers.ChoiceField(["task", "member", "draft"])
    id = serializers.IntegerField()
    label = serializers.CharField(allow_blank=True)


class AIActivityItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    agent = serializers.CharField()
    agent_name = serializers.CharField()
    icon = serializers.CharField()
    kind = serializers.CharField()
    level = serializers.ChoiceField(["info", "success", "warning"])
    text = serializers.CharField()
    created_at = serializers.DateTimeField()
    actor = AIActivityActorSerializer(allow_null=True)
    subject = AIActivitySubjectSerializer(allow_null=True)


class AIActivityPageSerializer(serializers.Serializer):
    results = AIActivityItemSerializer(many=True)
    next_before = serializers.IntegerField(allow_null=True)


def _agent_row(company, key: str) -> dict:
    return next(row for row in queries.agent_rows(company) if row["key"] == key)


class AgentListView(OwnerAPIView):
    perm = None

    @extend_schema(responses=AIAgentSerializer(many=True))
    def get(self, request, company_id):
        return Response(AIAgentSerializer(queries.agent_rows(self.company), many=True).data)


class AgentView(OwnerAPIView):
    perm = CONFIGURE

    @extend_schema(request=AIAgentUpdateSerializer, responses=AIAgentSerializer)
    def patch(self, request, company_id, key):
        if agents.get(key) is None:
            raise NotFound
        form = AIAgentUpdateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            services.update_agent(self.company, key, by=self.membership, **form.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError({"config": exc.message_dict}) from exc
        self.bump(PULSE_SETTINGS)
        return Response(AIAgentSerializer(_agent_row(self.company, key)).data)


class AgentRunView(OwnerAPIView):
    perm = CONFIGURE

    @extend_schema(request=None, responses={202: AIQueuedSerializer})
    def post(self, request, company_id, key):
        if agents.get(key) is None:
            raise NotFound
        services.run_agent_now(self.company, key, by=self.membership)
        return Response({"queued": True}, status=202)


class ActivityView(OwnerAPIView):
    perm = None

    @extend_schema(
        parameters=[
            OpenApiParameter("agent", str, description="One agent's key."),
            OpenApiParameter("limit", int, description="How many (30; at most 100)."),
            OpenApiParameter("before", int, description="The page after: next_before."),
        ],
        responses=AIActivityPageSerializer,
    )
    def get(self, request, company_id):
        params = request.query_params
        limit = int(params["limit"]) if params.get("limit", "").isdigit() else 30
        before = int(params["before"]) if params.get("before", "").isdigit() else None
        page = queries.activity(
            self.company,
            branch_ids=self.branch_scope,
            agent=params.get("agent") or None,
            limit=limit,
            before=before,
        )
        return Response(AIActivityPageSerializer(page).data)
