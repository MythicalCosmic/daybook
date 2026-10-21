"""Owner dashboard endpoints of the company calendar; routed in `owner_urls.py`.

`calendar/` is the whole calendar (every source the caller may see); `calendar/events/` are
the company's own events. Reading needs only dashboard access; adding and changing events
needs `agenda.manage`; anyone invited answers for themselves.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.agenda import aggregate, queries, services
from apps.agenda.conf import get_settings
from apps.agenda.models import Event
from apps.agenda.serializers import (
    AgendaAttendeeSerializer,
    AgendaCalendarItemSerializer,
    AgendaCancelSerializer,
    AgendaEventSerializer,
    AgendaEventUpdateSerializer,
    AgendaEventWriteSerializer,
    AgendaPeopleSerializer,
    AgendaRespondSerializer,
    AgendaSettingsSerializer,
    AgendaSourceSerializer,
    person,
    window,
)
from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.members.permissions import Perm

MANAGE = Perm.AGENDA_MANAGE


class CalendarView(OwnerAPIView):
    """The company calendar between two days: items of every source the caller may see
    (`sources=a,b` narrows them), plus the list of those sources for the toggles."""

    perm = None

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, description="First day, YYYY-MM-DD (default today)."),
            OpenApiParameter("to", str, description="Last day, inclusive (62 days at most)."),
            OpenApiParameter("sources", str, description="Comma-separated source keys."),
        ],
        responses=inline_serializer(
            "AgendaCalendar",
            {
                "range": serializers.DictField(child=serializers.CharField()),
                "sources": AgendaSourceSerializer(many=True),
                "items": AgendaCalendarItemSerializer(many=True),
            },
        ),
    )
    def get(self, request, company_id):
        first, last = window(request.query_params, self.company)
        wanted = request.query_params.get("sources")
        only = [key for key in wanted.split(",") if key] if wanted else None
        return Response(
            {
                "range": {"from": first.isoformat(), "to": last.isoformat()},
                "sources": aggregate.sources(self.membership),
                "items": aggregate.items(self.membership, first, last, only=only),
            }
        )


class SourcesView(OwnerAPIView):
    perm = None

    @extend_schema(responses=AgendaSourceSerializer(many=True))
    def get(self, request, company_id):
        return Response(aggregate.sources(self.membership))


class EventViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet):
    """The company's own events. The list filters by `when` (upcoming|past|cancelled), `q` and
    `kind`; the detail has the attendees and their answers."""

    serializer_class = AgendaEventSerializer
    lookup_value_regex = r"\d+"
    perm = None
    perms_by_action = {
        "create": MANAGE,
        "partial_update": MANAGE,
        "cancel": MANAGE,
        "remind": MANAGE,
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Event.objects.none()
        events = queries.with_answers(
            queries.visible_events(self.membership).select_related(
                "branch", "created_by__user", "company"
            ),
            self.membership,
        )
        if self.action != "list":
            return events
        params = self.request.query_params
        now = timezone.now()
        when = params.get("when", "upcoming")
        if when == "cancelled":
            events = events.filter(cancelled_at__isnull=False).order_by("-start")
        elif when == "past":
            events = (
                events.filter(cancelled_at__isnull=True)
                .filter(
                    Q(end__lt=now) | Q(end__isnull=True, start__lt=now), repeat=Event.Repeat.NONE
                )
                .order_by("-start")
            )
        else:
            today = queries.local_day(now, self.company)
            events = (
                events.filter(cancelled_at__isnull=True)
                .filter(
                    Q(repeat=Event.Repeat.NONE)
                    & (Q(end__gte=now) | Q(end__isnull=True, start__gte=now - timedelta(hours=12)))
                    | ~Q(repeat=Event.Repeat.NONE)
                    & (Q(repeat_until__isnull=True) | Q(repeat_until__gte=today))
                )
                .order_by("start")
            )
        if kind := params.get("kind"):
            events = events.filter(kind=kind)
        if q := (params.get("q") or "").strip():
            events = events.filter(Q(title__icontains=q) | Q(place__icontains=q))
        return events

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "action", None) == "list":
            context["compact"] = True
        return context

    @extend_schema(
        parameters=[
            OpenApiParameter("when", str, enum=["upcoming", "past", "cancelled"]),
            OpenApiParameter("kind", str, enum=Event.Kind.values),
            OpenApiParameter("q", str),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _event(self, pk) -> Event:
        event = queries.get_event(self.membership, int(pk))
        if event is None:
            raise NotFound
        return event

    def _detail(self, event: Event, *, status_code=status.HTTP_200_OK) -> Response:
        event = queries.with_answers(
            Event.objects.select_related("branch", "created_by__user", "company"),
            self.membership,
        ).get(pk=event.pk)
        return Response(
            AgendaEventSerializer(event, context=self.get_serializer_context()).data,
            status=status_code,
        )

    @extend_schema(responses=AgendaEventSerializer)
    def retrieve(self, request, company_id, pk):
        return self._detail(self._event(pk))

    @extend_schema(request=AgendaEventWriteSerializer, responses={201: AgendaEventSerializer})
    def create(self, request, company_id):
        data = AgendaEventWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        if "remind_before" not in request.data:
            values["remind_before"] = "default"
        event = services.create_event(self.company, by=self.membership, **values)
        return self._detail(event, status_code=status.HTTP_201_CREATED)

    @extend_schema(request=AgendaEventUpdateSerializer, responses=AgendaEventSerializer)
    def partial_update(self, request, company_id, pk):
        data = AgendaEventUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        event = services.update_event(self._event(pk), by=self.membership, **data.validated_data)
        return self._detail(event)

    @extend_schema(request=AgendaCancelSerializer, responses=AgendaEventSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk):
        data = AgendaCancelSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        event = services.cancel_event(
            self._event(pk), by=self.membership, reason=data.validated_data["reason"]
        )
        return self._detail(event)

    @extend_schema(
        request=None,
        responses=inline_serializer("AgendaReminded", {"reminded": serializers.IntegerField()}),
    )
    @action(detail=True, methods=["post"])
    def remind(self, request, company_id, pk):
        """Remind the attendees of the next occurrence now."""
        return Response({"reminded": services.remind_now(self._event(pk), by=self.membership)})

    @extend_schema(request=AgendaRespondSerializer, responses=AgendaAttendeeSerializer)
    @action(detail=True, methods=["post"])
    def respond(self, request, company_id, pk):
        """The caller, when invited, says whether they're coming."""
        data = AgendaRespondSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invite = services.respond(
            self._event(pk), by=self.membership, response=data.validated_data["response"]
        )
        return Response(AgendaAttendeeSerializer(invite).data)


class PeopleView(OwnerAPIView):
    """People the caller may invite (approved members in their branch scope)."""

    perm = MANAGE

    @extend_schema(responses=AgendaPeopleSerializer(many=True))
    def get(self, request, company_id):
        rows = queries.people(self.membership).prefetch_related("branches")
        return Response(
            [
                person(member)
                | {
                    "subtitle": " · ".join(
                        part
                        for part in (
                            member.position.name if member.position else "",
                            member.home_branch.name if member.home_branch else "",
                        )
                        if part
                    ),
                    "position_id": member.position_id,
                    "branch_ids": [branch.pk for branch in member.branches.all()],
                }
                for member in rows
            ]
        )


class SettingsView(OwnerAPIView):
    perm = None
    perms_by_action = {"patch": MANAGE}

    @extend_schema(responses=AgendaSettingsSerializer)
    def get(self, request, company_id):
        return Response(AgendaSettingsSerializer(get_settings(self.company)).data)

    @extend_schema(request=AgendaSettingsSerializer, responses=AgendaSettingsSerializer)
    def patch(self, request, company_id):
        data = AgendaSettingsSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        row = services.update_settings(self.company, by=self.membership, **data.validated_data)
        return Response(AgendaSettingsSerializer(row).data)
