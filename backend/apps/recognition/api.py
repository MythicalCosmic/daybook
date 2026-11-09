"""Employee (mini app) endpoints of recognition, mounted at `/api/v1/companies/<id>/`
(docs/PLAN-LEARNING.md §13 R):

    GET   recognition/me/                        my points, level, streak, badges, what's new
    POST  recognition/seen/                      the app celebrated it {kudos?: bool} → 204
    GET   recognition/leaderboard/?period=week|month|all&scope=company|branch
    GET   recognition/kudos/?box=received|given  my thanks
    POST  recognition/kudos/                     {to, badge, message, task?} → the kudos (201)
    GET   recognition/kudos/colleagues/?q=       who I can thank, and how many more today

A person only ever sees their own points and thanks (and the leaderboard the company allows).
Everything answers 404 while the recognition module is off.
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.members.api import IsCompanyMember
from apps.members.models import Membership
from apps.recognition import conf, queries, services
from apps.recognition import serializers as s
from apps.recognition.models import Kudos


class RecognitionOn(BasePermission):
    """The company doesn't run recognition: as if the endpoints weren't there."""

    def has_permission(self, request, view):
        if not conf.is_on(view.membership.company):
            raise NotFound
        return True


class MemberView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, RecognitionOn)
    membership: Membership


def _choice(request, name: str, allowed, default: str) -> str:
    value = request.query_params.get(name) or default
    if value not in allowed:
        raise ValidationError(
            {name: [_("Pick one of: %(values)s.") % {"values": ", ".join(allowed)}]}
        )
    return value


class MeView(MemberView):
    @extend_schema(responses=s.MeSerializer, operation_id="recognition_me")
    def get(self, request, company_id):
        return Response(s.MeSerializer(queries.me(self.membership)).data)


class SeenView(MemberView):
    @extend_schema(request=s.SeenSerializer, responses={204: None}, operation_id="recognition_seen")
    def post(self, request, company_id):
        serializer = s.SeenSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        services.mark_seen(self.membership, kudos=serializer.validated_data["kudos"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeaderboardView(MemberView):
    @extend_schema(
        parameters=[
            OpenApiParameter("period", str, enum=list(queries.PERIODS)),
            OpenApiParameter("scope", str, enum=["company", "branch"]),
        ],
        responses=s.StaffBoardSerializer,
        operation_id="recognition_leaderboard",
    )
    def get(self, request, company_id):
        period = _choice(request, "period", queries.PERIODS, "week")
        scope = _choice(request, "scope", ("company", "branch"), "company")
        board = queries.staff_board(self.membership, period=period, scope=scope)
        return Response(s.StaffBoardSerializer(board).data)


class KudosView(MemberView):
    @extend_schema(
        parameters=[OpenApiParameter("box", str, enum=["received", "given"])],
        responses=s.KudosSerializer(many=True),
        operation_id="recognition_kudos_list",
    )
    def get(self, request, company_id):
        box = _choice(request, "box", ("received", "given"), "received")
        rows = queries.kudos_box(self.membership, box)
        return Response(
            s.KudosSerializer(
                [queries.kudos_payload(item, self.membership) for item in rows], many=True
            ).data
        )

    @extend_schema(
        request=s.SendKudosSerializer,
        responses={201: s.KudosSerializer},
        operation_id="recognition_kudos_send",
    )
    def post(self, request, company_id):
        serializer = s.SendKudosSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        company = self.membership.company
        receiver = (
            Membership.objects.select_related("user", "position", "company")
            .filter(company=company, pk=data["to"])
            .first()
        )
        if receiver is None:
            raise ValidationError({"to": [_("Pick a colleague of this company.")]})
        task = None
        if data.get("task"):
            from apps.tasks.queries import visible_tasks

            task = visible_tasks(self.membership).filter(pk=data["task"]).first()
            if task is None:
                raise ValidationError({"task": [_("Pick one of your tasks.")]})
        kudos = services.send_kudos(
            self.membership,
            to=receiver,
            badge=data["badge"],
            message=data.get("message", ""),
            task=task,
        )
        kudos = Kudos.objects.select_related(
            "from_member__user", "from_member__position", "to_member__user", "to_member__position"
        ).get(pk=kudos.pk)
        return Response(
            s.KudosSerializer(queries.kudos_payload(kudos, self.membership)).data,
            status=status.HTTP_201_CREATED,
        )


class ColleaguesView(MemberView):
    @extend_schema(
        parameters=[
            OpenApiParameter("q", str),
            OpenApiParameter(
                "include", int, description="A colleague to list first (to thank them back)."
            ),
        ],
        responses=s.ColleaguesSerializer,
        operation_id="recognition_kudos_colleagues",
    )
    def get(self, request, company_id):
        member = self.membership
        settings = conf.get_settings(member.company)
        include = request.query_params.get("include") or ""
        people = queries.colleagues(
            member,
            (request.query_params.get("q") or "").strip()[:60],
            include=int(include) if include.isdigit() else None,
        )
        results = [
            {
                **queries.person(person),
                "branch": person.home_branch.name if person.home_branch_id else None,
            }
            for person in people
        ]
        return Response(
            s.ColleaguesSerializer(
                {
                    "per_day": settings.kudos_per_day,
                    "left": services.kudos_left(member) if settings.kudos_enabled else 0,
                    "results": results,
                }
            ).data
        )
