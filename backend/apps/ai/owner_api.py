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

    GET/POST ai/custom-agents/             the agents an owner made (POST: ai.configure)
    PATCH/DELETE ai/custom-agents/<id>/    ai.configure; DELETE is a soft delete
    GET  ai/custom-agents/templates/       ai.configure: the ready jobs to start from
    GET  ai/custom-agents/options/         ai.configure: what the form offers
A custom agent's page, switch and "Run now" are the agents' own (ai/agents/custom_<id>/…).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.ai import agents, availability, chat, conf, queries, services, speech
from apps.ai import instructions as owner_instructions
from apps.ai.agents import custom, custom_templates, photo_checker
from apps.ai.api import CREATE_ERRORS, DRAFT_RELATIONS, DraftEndpoints
from apps.ai.models import AIDraft, AISettings, CustomAgent
from apps.ai.serializers import (
    AIApplyResultSerializer,
    AIDraftApplySerializer,
    AIDraftCreateSerializer,
    AIDraftSerializer,
)
from apps.console.base import OwnerAPIView, OwnerGenericAPIView
from apps.core.api import Pagination
from apps.core.throttles import throttle_person
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
            "chat": chat.available(membership),
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


class AICustomPersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class AICustomGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


class AICustomDomainSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="A tool domain (apps.ai.tools.registry).")
    label = serializers.CharField()


class AICustomAgentSerializer(serializers.Serializer):
    """An agent an owner made: what it does, when, for whom and what it may read."""

    id = serializers.IntegerField()
    job = serializers.CharField(help_text="What it should do, in the owner's words.")
    color = serializers.ChoiceField(CustomAgent.Color.choices)
    template = serializers.CharField(allow_blank=True, help_text="The template it started from.")
    frequency = serializers.ChoiceField(CustomAgent.Frequency.choices)
    at = serializers.CharField(help_text="HH:MM in the company's timezone.")
    weekday = serializers.IntegerField(allow_null=True, help_text="Weekly: 0 = Monday.")
    month_day = serializers.IntegerField(allow_null=True, help_text="Monthly: 1 to 28.")
    recipients = serializers.ChoiceField(CustomAgent.Recipients.choices)
    people = AICustomPersonSerializer(many=True)
    group = AICustomGroupSerializer(allow_null=True)
    domains = AICustomDomainSerializer(many=True)
    run_as = AICustomPersonSerializer(help_text="Whose rights it reads with ('me').")
    created_by = AICustomPersonSerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    paused_reason = serializers.CharField(
        allow_blank=True, help_text='Why it switched itself off: "", "left" or "no_access".'
    )
    paused_text = serializers.CharField(allow_blank=True)
    last_report = serializers.CharField(
        allow_null=True,
        help_text="What it last wrote: only for its owner and the people it goes to (else null).",
    )
    last_report_at = serializers.DateTimeField(allow_null=True)


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
    custom = AICustomAgentSerializer(
        allow_null=True, help_text="An agent an owner made (custom_<id>); null for a built-in one."
    )


MONEY = {"max_digits": 16, "decimal_places": 6, "allow_null": True}
ONLY_CONFIGURE = "Only for ai.configure (null otherwise)."


class AIAgentRunSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    duration_ms = serializers.IntegerField(allow_null=True)
    status = serializers.ChoiceField(
        ["running", "ok", "error"],
        help_text='A run still "running" an hour after it started reads as an error.',
    )
    forced = serializers.BooleanField(help_text='"Run now", not the schedule.')
    done = serializers.IntegerField(help_text="How many things the run did.")
    error = serializers.CharField(allow_null=True, help_text=ONLY_CONFIGURE)
    calls = serializers.IntegerField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    cost_usd = serializers.DecimalField(**MONEY, help_text=ONLY_CONFIGURE)


class AIAgentCallSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    model = serializers.CharField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    cache_read_tokens = serializers.IntegerField()
    latency_ms = serializers.IntegerField()
    stop_reason = serializers.CharField(allow_blank=True)
    cost_usd = serializers.DecimalField(**MONEY, help_text=ONLY_CONFIGURE)


class AIAgentUsageMonthSerializer(serializers.Serializer):
    calls = serializers.IntegerField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    cache_read_tokens = serializers.IntegerField()
    cost_usd = serializers.DecimalField(**MONEY, help_text=ONLY_CONFIGURE)


class AIAgentUsageDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    calls = serializers.IntegerField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    cost_usd = serializers.DecimalField(**MONEY, help_text=ONLY_CONFIGURE)


class AIAgentCompanyMonthSerializer(serializers.Serializer):
    month_cost_usd = serializers.DecimalField(max_digits=16, decimal_places=6)
    monthly_budget_usd = serializers.DecimalField(max_digits=10, decimal_places=2)


class AIAgentUsageSerializer(serializers.Serializer):
    month = AIAgentUsageMonthSerializer(help_text="This month in the company's calendar.")
    days = AIAgentUsageDaySerializer(
        many=True, help_text="The last 30 days in the company's calendar, oldest first."
    )
    company = AIAgentCompanyMonthSerializer(
        allow_null=True, help_text="The whole company's month. " + ONLY_CONFIGURE
    )


class AIAgentUpcomingSerializer(serializers.Serializer):
    at = serializers.DateTimeField(allow_null=True)
    kind = serializers.ChoiceField(["run", "item"])
    label = serializers.CharField()


class AIAgentPromptSerializer(serializers.Serializer):
    label = serializers.CharField(
        help_text="The job it asks Claude to do, in the reader's language."
    )
    text = serializers.CharField(help_text="The system prompt as Claude reads it (English).")


class AIAgentDetailSerializer(AIAgentSerializer):
    runs = AIAgentRunSerializer(many=True, help_text="The newest 30 runs, newest first.")
    calls = AIAgentCallSerializer(
        many=True, help_text="Its newest 30 Claude calls, newest first: never a prompt or answer."
    )
    usage = AIAgentUsageSerializer()
    upcoming = AIAgentUpcomingSerializer(
        many=True, help_text="At most 6, soonest first; the ones without a time last."
    )
    scene = serializers.ChoiceField(
        ["working", "idle", "asleep"],
        help_text="working while it runs, idle when on and able to work, else asleep.",
    )
    prompts = AIAgentPromptSerializer(
        many=True, help_text="What it asks Claude; none when it works by fixed rules."
    )
    instructions = serializers.CharField(
        allow_blank=True, help_text="The owner's own instructions, added after each prompt."
    )


class AIAgentUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    config = serializers.DictField(required=False)
    instructions = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=owner_instructions.MAX_LENGTH,
        trim_whitespace=True,
    )


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


class AgentListView(OwnerAPIView):
    perm = None

    @extend_schema(responses=AIAgentSerializer(many=True))
    def get(self, request, company_id):
        return Response(AIAgentSerializer(queries.agent_rows(self.company), many=True).data)


class AgentView(OwnerAPIView):
    """GET: the agent's page, for anyone who sees the agents (money and error texts only with
    ai.configure). PATCH: ai.configure."""

    perm = None
    perms_by_action = {"patch": CONFIGURE}

    @extend_schema(responses=AIAgentDetailSerializer)
    def get(self, request, company_id, key):
        page = queries.agent_detail(
            self.company,
            key,
            can_configure=self.membership.has_perm(CONFIGURE),
            viewer=self.membership,
        )
        if page is None:
            raise NotFound
        return Response(AIAgentDetailSerializer(page).data)

    @extend_schema(request=AIAgentUpdateSerializer, responses=AIAgentSerializer)
    def patch(self, request, company_id, key):
        agent = agents.resolve(self.company, key)
        if agent is None or not agent.works_in(self.company):
            raise NotFound
        form = AIAgentUpdateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            services.update_agent(self.company, key, by=self.membership, **form.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError({"config": exc.message_dict}) from exc
        self.bump(PULSE_SETTINGS)
        return Response(AIAgentSerializer(queries.agent_row(self.company, key)).data)


class AgentRunView(OwnerAPIView):
    perm = CONFIGURE

    @extend_schema(request=None, responses={202: AIQueuedSerializer})
    def post(self, request, company_id, key):
        if agents.resolve(self.company, key) is None:
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


# The agents an owner makes in their own words (apps.ai.agents.custom) --------------------------


class AICustomAgentWriteSerializer(serializers.Serializer):
    """The New agent form (or the fields that change). The rules and their translated messages
    are apps.ai.agents.custom.clean's."""

    name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    job = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    color = serializers.CharField(required=False, allow_blank=True, max_length=16)
    template = serializers.CharField(required=False, allow_blank=True, max_length=32)
    frequency = serializers.CharField(required=False, help_text="daily, weekdays, weekly, monthly")
    at = serializers.CharField(required=False, help_text="HH:MM in the company's timezone.")
    weekday = serializers.IntegerField(required=False, allow_null=True)
    month_day = serializers.IntegerField(required=False, allow_null=True)
    recipients = serializers.CharField(required=False, help_text="me, people or group")
    people = serializers.ListField(child=serializers.IntegerField(), required=False)
    group = serializers.IntegerField(required=False, allow_null=True)
    domains = serializers.ListField(child=serializers.CharField(max_length=32), required=False)


class AICustomTemplateSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    job = serializers.CharField()
    frequency = serializers.ChoiceField(CustomAgent.Frequency.choices)
    at = serializers.CharField()
    weekday = serializers.IntegerField(allow_null=True)
    month_day = serializers.IntegerField(allow_null=True)
    domains = serializers.ListField(child=serializers.CharField())
    color = serializers.ChoiceField(CustomAgent.Color.choices)
    icon = serializers.CharField(help_text="A lucide icon name.")
    needs = serializers.CharField(allow_null=True, help_text="The module it is about.")


class AICustomDomainOptionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    available = serializers.BooleanField(help_text="Whether the asker may read it.")
    reason = serializers.CharField(
        allow_blank=True, help_text='"", "switch_off" (Settings › AI) or "no_access".'
    )
    feature = serializers.CharField(allow_null=True, help_text="Its module, when it has one.")


class AICustomRecipientSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    position = serializers.CharField(allow_blank=True)
    photo = serializers.CharField(allow_null=True)


class AICustomOptionsSerializer(serializers.Serializer):
    domains = AICustomDomainOptionSerializer(many=True)
    groups = AICustomGroupSerializer(many=True, help_text="Linked Telegram groups.")
    people = AICustomRecipientSerializer(
        many=True, help_text="Who can get it: approved, with the bot started."
    )
    max_agents = serializers.IntegerField()
    live = serializers.IntegerField(help_text="How many the company has now.")
    run_now_left = serializers.IntegerField(help_text='"Run now"s left today, for all of them.')
    me = AICustomPersonSerializer()


def custom_options(member) -> dict:
    from apps.groups.models import TelegramGroup
    from apps.members.models import Membership
    from apps.members.queries import photo_url

    company = member.company
    groups = TelegramGroup.objects.filter(company=company, is_active=True).order_by("title", "pk")
    people = (
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.APPROVED, user__telegram_id__isnull=False)
        .select_related("user", "position")
        .order_by("first_name", "last_name", "pk")[:500]
    )
    return {
        "domains": custom.domain_options(company, member),
        "groups": [{"id": group.pk, "title": str(group)} for group in groups],
        "people": [
            {
                "id": person.pk,
                "name": str(person),
                "position": person.position.name if person.position_id else "",
                "photo": photo_url(person),
            }
            for person in people
        ],
        "max_agents": CustomAgent.MAX_LIVE,
        "live": custom.live(company).count(),
        "run_now_left": custom.run_now_left(company),
        "me": {"id": member.pk, "name": str(member)},
    }


class CustomAgentListView(OwnerAPIView):
    """GET: the company's own agents as the agents list shows them. POST: a new one
    (ai.configure), switched on; it reads with the creator's rights."""

    perm = None
    perms_by_action = {"post": CONFIGURE}

    @extend_schema(responses=AIAgentSerializer(many=True))
    def get(self, request, company_id):
        rows = [row for row in queries.agent_rows(self.company) if row["custom"] is not None]
        return Response(AIAgentSerializer(rows, many=True).data)

    @extend_schema(request=AICustomAgentWriteSerializer, responses={201: AIAgentSerializer})
    def post(self, request, company_id):
        form = AICustomAgentWriteSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            row = services.create_custom_agent(
                self.company, by=self.membership, data=form.validated_data
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        self.bump(PULSE_SETTINGS)
        return Response(
            AIAgentSerializer(queries.agent_row(self.company, row.key)).data, status=201
        )


class CustomAgentView(OwnerAPIView):
    perm = CONFIGURE

    def row(self, agent_id: int) -> CustomAgent:
        found = custom.live(self.company).filter(pk=agent_id).first()
        if found is None:
            raise NotFound
        return found

    @extend_schema(request=AICustomAgentWriteSerializer, responses=AIAgentSerializer)
    def patch(self, request, company_id, agent_id):
        row = self.row(agent_id)
        form = AICustomAgentWriteSerializer(data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        try:
            row = services.update_custom_agent(row, by=self.membership, data=form.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        self.bump(PULSE_SETTINGS)
        return Response(AIAgentSerializer(queries.agent_row(self.company, row.key)).data)

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, company_id, agent_id):
        services.delete_custom_agent(self.row(agent_id), by=self.membership)
        self.bump(PULSE_SETTINGS)
        return Response(status=204)


class CustomAgentTemplatesView(OwnerAPIView):
    perm = CONFIGURE

    @extend_schema(responses=AICustomTemplateSerializer(many=True))
    def get(self, request, company_id):
        return Response(
            AICustomTemplateSerializer(custom_templates.for_company(self.company), many=True).data
        )


class CustomAgentOptionsView(OwnerAPIView):
    perm = CONFIGURE

    @extend_schema(responses=AICustomOptionsSerializer)
    def get(self, request, company_id):
        return Response(AICustomOptionsSerializer(custom_options(self.membership)).data)


# Ask AI -----------------------------------------------------------------------------------------


class AIConversationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    last_activity_at = serializers.DateTimeField()


class AIStepSerializer(serializers.Serializer):
    label = serializers.CharField()
    status = serializers.ChoiceField(["done", "error"])
    ms = serializers.IntegerField()


class AIChatMessageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    role = serializers.ChoiceField(["user", "assistant"])
    text = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    steps = AIStepSerializer(many=True)


class AITurnCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=chat.TEXT_MAX)
    page = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")


class AITurnStartedSerializer(serializers.Serializer):
    turn_id = serializers.IntegerField()


class AITurnSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.ChoiceField(["queued", "running", "done", "failed", "cancelled"])
    steps = AIStepSerializer(many=True)
    text = serializers.CharField(allow_blank=True, help_text="Markdown: final once done.")
    error_code = serializers.CharField(allow_blank=True)
    message_id = serializers.IntegerField(allow_null=True)


def _conversation_row(conversation) -> dict:
    return {
        "id": conversation.pk,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "last_activity_at": conversation.last_activity_at,
    }


def _turn_row(turn) -> dict:
    return {
        "id": turn.pk,
        "status": turn.status,
        "steps": turn.steps or [],
        "text": turn.text,
        "error_code": turn.error_code,
        "message_id": turn.message_id,
    }


def _refused(exc: chat.TurnRefused) -> Response:
    return Response({"code": exc.code, "detail": str(exc)}, status=exc.status)


class ChatAccess(OwnerAPIView):
    perm = Perm.AI_USE

    def conversation(self, conversation_id: int):
        from apps.ai.models import AIConversation

        found = AIConversation.objects.filter(
            pk=conversation_id, company_id=self.company.pk, membership=self.membership
        ).first()
        if found is None:
            raise NotFound
        return found

    def turn(self, turn_id: int):
        from apps.ai.models import AITurn

        found = AITurn.objects.filter(
            pk=turn_id, company_id=self.company.pk, membership=self.membership
        ).first()
        if found is None:
            raise NotFound
        return found


class ConversationListView(ChatAccess):
    @extend_schema(responses=AIConversationSerializer(many=True))
    def get(self, request, company_id):
        from apps.ai.models import AIConversation

        rows = AIConversation.objects.filter(
            company_id=self.company.pk, membership=self.membership
        ).order_by("-last_activity_at")[:100]
        return Response(
            AIConversationSerializer([_conversation_row(c) for c in rows], many=True).data
        )

    @extend_schema(request=None, responses={201: AIConversationSerializer})
    def post(self, request, company_id):
        try:
            conversation = chat.start_conversation(self.membership)
        except chat.TurnRefused as exc:
            return _refused(exc)
        return Response(AIConversationSerializer(_conversation_row(conversation)).data, status=201)


class ConversationMessagesView(ChatAccess):
    @extend_schema(responses=AIChatMessageSerializer(many=True))
    def get(self, request, company_id, conversation_id):
        from apps.ai.models import AIMessage

        conversation = self.conversation(conversation_id)
        messages = AIMessage.objects.filter(conversation=conversation).select_related("turn")
        rows = [
            {
                "id": message.pk,
                "role": message.role,
                "text": message.display_text,
                "created_at": message.created_at,
                "steps": (message.turn.steps or [])
                if message.turn and message.role == "assistant"
                else [],
            }
            for message in messages
            if message.display_text
        ]
        return Response(AIChatMessageSerializer(rows, many=True).data)


class TurnCreateView(ChatAccess):
    @extend_schema(request=AITurnCreateSerializer, responses={202: AITurnStartedSerializer})
    def post(self, request, company_id, conversation_id):
        throttle_person(self, request, "ai_turn", self.membership.pk)
        form = AITurnCreateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            turn = chat.start_turn(
                self.conversation(conversation_id), by=self.membership, **form.validated_data
            )
        except chat.TurnRefused as exc:
            return _refused(exc)
        return Response({"turn_id": turn.pk}, status=202)


class TurnView(ChatAccess):
    @extend_schema(responses=AITurnSerializer)
    def get(self, request, company_id, turn_id):
        return Response(AITurnSerializer(_turn_row(self.turn(turn_id))).data)


class TurnCancelView(ChatAccess):
    @extend_schema(request=None, responses=AITurnSerializer)
    def post(self, request, company_id, turn_id):
        turn = chat.cancel_turn(self.turn(turn_id), by=self.membership)
        return Response(AITurnSerializer(_turn_row(turn)).data)
