"""Employee (mini app) endpoints of the AI features; routed in `urls.py` (contract §4).

    GET  ai/status/                         what the app may offer (voice, typed, limits)
    POST ai/task-drafts/                    multipart audio (+ seconds, language) or {"text"}
    GET  ai/task-drafts/<id>/               own drafts only (others 404); poll while working
    POST ai/task-drafts/<id>/apply/         {"drafts"?: [...]} -> {draft, created, failed}
    POST ai/task-drafts/<id>/discard/       204

Errors carry a code for the app: 400 {"code": "audio_too_long" | "audio_too_big" |
"audio_unreadable" | "text_too_long", "detail"}, 403 {"code": "ai_off"}, 429
{"code": "limit_reached"} (the daily limit; a burst over 20 a minute is throttled too).
The owner API (owner_api.py) uses the same handlers through `DraftEndpoints`.
"""

from dataclasses import asdict

from django.conf import settings
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai import services
from apps.ai.models import AIDraft
from apps.ai.serializers import (
    AIApplyResultSerializer,
    AIDraftApplySerializer,
    AIDraftCreateSerializer,
    AIDraftSerializer,
    AIErrorSerializer,
    AIVoiceStatusSerializer,
)
from apps.core.throttles import throttle_person
from apps.members.api import IsCompanyMember

DRAFT_RELATIONS = ("company", "created_by__user", "created_by__company", "created_by__role")
CREATE_ERRORS = {
    201: AIDraftSerializer,
    400: OpenApiResponse(AIErrorSerializer, description="audio_* or text_too_long"),
    403: OpenApiResponse(AIErrorSerializer, description="ai_off"),
    429: OpenApiResponse(AIErrorSerializer, description="limit_reached"),
}


class DraftEndpoints:
    """The task-draft handlers both APIs share; `self.membership` is set by their permission
    classes, `source` names where drafts come from, `visible_drafts()` what the caller sees."""

    source: str
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def visible_drafts(self) -> QuerySet[AIDraft]:
        return AIDraft.objects.filter(created_by=self.membership)

    def get_draft(self, draft_id: int) -> AIDraft:
        draft = (
            self.visible_drafts()
            .filter(company_id=self.membership.company_id, pk=draft_id)
            .select_related(*DRAFT_RELATIONS)
            .first()
        )
        if draft is None:
            raise NotFound
        return draft

    def create_draft(self, request) -> Response:
        throttle_person(self, request, "ai_draft", self.membership.pk)
        form = AIDraftCreateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        try:
            draft = services.start_draft(
                self.membership,
                audio=data.get("audio"),
                seconds=data.get("seconds"),
                text=data.get("text"),
                language=data.get("language"),
                source=self.source,
            )
        except services.DraftRefused as exc:
            return Response({"code": exc.code, "detail": str(exc)}, status=exc.status)
        draft = self.get_draft(draft.pk)
        return Response(
            AIDraftSerializer(draft, context={"request": request}).data,
            status=status.HTTP_202_ACCEPTED,
        )

    def apply(self, request, draft_id: int) -> Response:
        draft = self.get_draft(draft_id)
        form = AIDraftApplySerializer(data=request.data or {})
        form.is_valid(raise_exception=True)
        result = services.apply_draft(draft, self.membership, form.validated_data.get("drafts"))
        draft = self.get_draft(draft_id)
        return Response(
            {
                "draft": AIDraftSerializer(draft, context={"request": request}).data,
                "created": result.created,
                "failed": result.failed,
            }
        )

    def discard(self, request, draft_id: int) -> Response:
        services.discard_draft(self.get_draft(draft_id), self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StatusView(APIView):
    """What the mini app may offer this member: recording, typed instructions, the limits."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(responses=AIVoiceStatusSerializer)
    def get(self, request, company_id):
        found = services.voice_status(self.membership)
        return Response(asdict(found) | {"bot_username": settings.EMPLOYEE_BOT_USERNAME})


class TaskDraftCreateView(DraftEndpoints, APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember)
    source = AIDraft.Source.MINIAPP

    @extend_schema(
        request={
            "multipart/form-data": AIDraftCreateSerializer,
            "application/json": AIDraftCreateSerializer,
        },
        responses={**CREATE_ERRORS, 202: AIDraftSerializer},
    )
    def post(self, request, company_id):
        return self.create_draft(request)


class TaskDraftDetailView(DraftEndpoints, APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(responses=AIDraftSerializer)
    def get(self, request, company_id, draft_id):
        return Response(
            AIDraftSerializer(self.get_draft(draft_id), context={"request": request}).data
        )


class TaskDraftApplyView(DraftEndpoints, APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(request=AIDraftApplySerializer, responses=AIApplyResultSerializer)
    def post(self, request, company_id, draft_id):
        return self.apply(request, draft_id)


class TaskDraftDiscardView(DraftEndpoints, APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(request=None, responses={204: None})
    def post(self, request, company_id, draft_id):
        return self.discard(request, draft_id)
