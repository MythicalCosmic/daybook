"""Employee (mini app) endpoints of the company calendar; routed in `urls.py`.

The app's "Calendar" shows the person's own events and the team dates their permissions allow
(holidays, birthdays, shifts… whatever modules registered), and lets them answer invitations.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agenda import aggregate, queries, services
from apps.agenda.serializers import (
    AgendaAttendeeSerializer,
    AgendaCalendarItemSerializer,
    AgendaEventSerializer,
    AgendaRespondSerializer,
    AgendaSourceSerializer,
    window,
)
from apps.members.api import IsCompanyMember


class CalendarView(APIView):
    """My calendar between two days: my events, company events and team dates."""

    permission_classes = (IsAuthenticated, IsCompanyMember)

    @extend_schema(
        parameters=[OpenApiParameter("from", str), OpenApiParameter("to", str)],
        responses=inline_serializer(
            "AgendaEmployeeCalendar",
            {
                "range": serializers.DictField(child=serializers.CharField()),
                "sources": AgendaSourceSerializer(many=True),
                "items": AgendaCalendarItemSerializer(many=True),
                "mine": serializers.ListField(child=serializers.CharField()),
            },
        ),
    )
    def get(self, request, company_id):
        member = self.membership
        first, last = window(request.query_params, member.company)
        items = aggregate.items(member, first, last)
        invited = set(
            queries.visible_events(member)
            .filter(invites__membership=member)
            .values_list("pk", flat=True)
        )
        mine = [
            item["id"]
            for item in items
            if item["kind"] == "agenda.event"
            and int(item["id"].split(":", 1)[1].split("-", 1)[0]) in invited
        ]
        return Response(
            {
                "range": {"from": first.isoformat(), "to": last.isoformat()},
                "sources": aggregate.sources(member),
                "items": items,
                "mine": mine,
            }
        )


class EventView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember)

    def _event(self, pk):
        event = queries.get_event(self.membership, int(pk))
        if event is None:
            raise NotFound
        return event

    @extend_schema(responses=AgendaEventSerializer)
    def get(self, request, company_id, pk):
        context = {"request": request, "membership": self.membership, "reader": True}
        return Response(AgendaEventSerializer(self._event(pk), context=context).data)


class RespondView(EventView):
    http_method_names = ["post", "options"]

    @extend_schema(request=AgendaRespondSerializer, responses=AgendaAttendeeSerializer)
    def post(self, request, company_id, pk):
        data = AgendaRespondSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invite = services.respond(
            self._event(pk), by=self.membership, response=data.validated_data["response"]
        )
        return Response(AgendaAttendeeSerializer(invite).data)
