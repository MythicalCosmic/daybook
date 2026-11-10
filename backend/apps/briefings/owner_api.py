"""Owner dashboard endpoints of briefings; routed in `owner_urls.py` (docs/PLAN-OWNER.md §4.13).

    GET   briefings/?kind=weekly             reports.view: the caller's reviews, newest first
    GET   briefings/latest/?kind=weekly      reports.view: the newest one, when the next ones go
                                             out, who writes them and what the caller may do
    GET   briefings/{id}/                    reports.view: one review (marks it opened)
    POST  briefings/regenerate/ {kind}       company.settings: written again now, 3 a day
    GET   briefings/settings/                company.settings
    PATCH briefings/settings/                company.settings: days, time, recipients
    GET   briefings/advisor/conversations/   reports.view + ai.use: "Ask the advisor" chats
    POST  briefings/advisor/conversations/   a new one; the questions go through Ask AI's
                                             `ai/conversations/{id}/turns/` and `ai/turns/{id}/`

Every review answers only to readers of its own scope (apps.briefings.scope): another scope's
id is a 404 like another company's.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.briefings import conf, periods, queries, reviews, scope, services
from apps.briefings import serializers as s
from apps.briefings.models import Briefing
from apps.console.base import AllOf, OwnerAPIView
from apps.members.permissions import Perm

READ = Perm.REPORTS_VIEW
SETTINGS = Perm.COMPANY_SETTINGS
KIND = OpenApiParameter("kind", str, enum=Briefing.Kind.values, description="weekly (default).")


def _kind(request) -> str:
    value = request.query_params.get("kind") or Briefing.Kind.WEEKLY
    if value not in Briefing.Kind.values:
        raise ValidationError({"kind": ["weekly or monthly."]})
    return value


class BriefingListView(OwnerAPIView):
    perm = READ

    @extend_schema(
        operation_id="companies_briefings_list",
        parameters=[KIND],
        responses=s.BriefingsListSerializer,
    )
    def get(self, request, company_id):
        rows = queries.visible(self.membership, kind=_kind(request))
        return Response(
            s.BriefingsListSerializer({"results": [queries.summary(row) for row in rows]}).data
        )


class BriefingLatestView(OwnerAPIView):
    perm = READ

    @extend_schema(parameters=[KIND], responses=s.BriefingsLatestSerializer)
    def get(self, request, company_id):
        from apps.ai import chat

        kind = _kind(request)
        member = self.membership
        review = queries.latest(member, kind)
        if review is not None:
            services.mark_opened(review, member)
        now = timezone.now()
        moment = reviews.local(self.company, now)
        row = conf.get_settings(self.company)
        may_rewrite = member.has_perm(SETTINGS)
        shape = {
            "review": queries.shape(review) if review is not None else None,
            "next": {kind_: periods.next_send(row, kind_, moment) for kind_ in reviews.KINDS},
            "writer": "ai" if reviews.claude_writes(self.company) else "template",
            "advisor_on": reviews.advisor_writes(self.company),
            "chat": member.has_perm(READ) and chat.advisor_available(member),
            "has_data": scope.of(member).has_data,
            "can_regenerate": may_rewrite,
            "regenerations_left": max(
                services.REGENERATE_PER_DAY - services.regenerated_today(self.company, now), 0
            )
            if may_rewrite
            else 0,
            "can_configure": may_rewrite,
        }
        return Response(s.BriefingsLatestSerializer(shape).data)


class BriefingDetailView(OwnerAPIView):
    perm = READ

    @extend_schema(responses=s.BriefingsReviewSerializer)
    def get(self, request, company_id, briefing_id):
        review = queries.get(self.membership, briefing_id)
        if review is None:
            raise NotFound
        services.mark_opened(review, self.membership)
        return Response(s.BriefingsReviewSerializer(queries.shape(review)).data)


class BriefingRegenerateView(OwnerAPIView):
    perm = SETTINGS

    @extend_schema(
        request=s.BriefingsRegenerateSerializer,
        responses={200: s.BriefingsReviewSerializer, 202: s.BriefingsQueuedSerializer},
    )
    def post(self, request, company_id):
        form = s.BriefingsRegenerateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        review = services.request_regenerate(self.membership, kind=form.validated_data["kind"])
        if review is None:
            return Response({"queued": True}, status=status.HTTP_202_ACCEPTED)
        return Response(s.BriefingsReviewSerializer(queries.shape(review)).data)


class BriefingSettingsView(OwnerAPIView):
    perm = SETTINGS

    @extend_schema(responses=s.BriefingsSettingsSerializer)
    def get(self, request, company_id):
        return Response(s.BriefingsSettingsSerializer(conf.get_settings(self.company)).data)

    @extend_schema(
        request=s.BriefingsSettingsSerializer(partial=True),
        responses=s.BriefingsSettingsSerializer,
    )
    def patch(self, request, company_id):
        form = s.BriefingsSettingsSerializer(
            conf.get_settings(self.company), data=request.data, partial=True
        )
        form.is_valid(raise_exception=True)
        try:
            row = services.update_settings(
                self.company, by=self.membership, changes=dict(form.validated_data)
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        return Response(s.BriefingsSettingsSerializer(row).data)


def _conversation(row) -> dict:
    return {
        "id": row.pk,
        "title": row.title,
        "created_at": row.created_at,
        "last_activity_at": row.last_activity_at,
    }


class AdvisorConversationsView(OwnerAPIView):
    """The caller's "Ask the advisor" conversations (Ask AI conversations with `agent`
    "advisor", private to their author)."""

    perm = AllOf(READ, Perm.AI_USE)

    @extend_schema(responses=s.BriefingsConversationSerializer(many=True))
    def get(self, request, company_id):
        from apps.ai import chat
        from apps.ai.models import AIConversation

        rows = AIConversation.objects.filter(
            company_id=self.company.pk, membership=self.membership, agent=chat.ADVISOR
        ).order_by("-last_activity_at")[:50]
        return Response(
            s.BriefingsConversationSerializer([_conversation(row) for row in rows], many=True).data
        )

    @extend_schema(request=None, responses={201: s.BriefingsConversationSerializer})
    def post(self, request, company_id):
        from apps.ai import chat

        try:
            row = chat.start_conversation(self.membership, agent=chat.ADVISOR)
        except chat.TurnRefused as exc:
            return Response({"code": exc.code, "detail": str(exc)}, status=exc.status)
        return Response(
            s.BriefingsConversationSerializer(_conversation(row)).data,
            status=status.HTTP_201_CREATED,
        )
