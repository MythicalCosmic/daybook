"""Owner dashboard endpoints of recognition (`recognition/…`, PLAN-LEARNING §11, §13):

    GET    recognition/leaderboard/?period=week|month|all&date=YYYY-MM-DD&branch&kind=all|learning
    GET    recognition/people/{id}/                 a person's points, level, badges, history
    POST   recognition/people/{id}/adjust/          {points, note}: a correction (owners)
    GET    recognition/kudos/?branch&member&before   the thanks, newest first
    POST   recognition/kudos/                       {to, badge, message}: "Say thanks"
    POST   recognition/kudos/{id}/hide/             hide one (owners)
    GET    recognition/badges/?branch                the catalogue with who has each badge
    GET/PATCH recognition/settings/                 the recognition settings (owners change)

Reading needs members.view, learning.view or recognition.manage; changing recognition.manage
("Say thanks" only dashboard access: it comes from a colleague). Company and branch scope
everywhere (a person outside the caller's branches answers 404, like another company's id);
everything answers 404 while the recognition module is off.
"""

from dataclasses import asdict
from datetime import date, datetime

from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.console.base import OwnerAPIView
from apps.members.models import Membership
from apps.members.queries import in_scope
from apps.recognition import badges as catalogue
from apps.recognition import conf, queries, rules, services
from apps.recognition import serializers as s
from apps.recognition.models import BadgeAward, Kudos, Streak
from apps.recognition.providers import MANAGE, READ

BRANCH_PARAM = OpenApiParameter("branch", int, description="One branch (in scope).")


class OwnerView(OwnerAPIView):
    perm = READ

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not conf.is_on(self.company):
            raise NotFound

    def branches(self) -> list[int] | None:
        """The caller's branches, narrowed to `?branch=` when given (and allowed)."""
        asked = self.request.query_params.get("branch")
        allowed = self.branch_scope
        if not asked:
            return allowed
        try:
            branch = int(asked)
        except ValueError as exc:
            raise ValidationError({"branch": [_("Give a number.")]}) from exc
        if allowed is not None and branch not in allowed:
            raise NotFound
        if not self.company.branches.filter(pk=branch).exists():
            raise NotFound
        return [branch]

    def person(self, member_id) -> Membership:
        found = (
            Membership.objects.select_related("user", "position", "company", "home_branch")
            .filter(company=self.company, pk=member_id)
            .first()
        )
        if found is None or not in_scope(self.membership, found):
            raise NotFound
        return found


def _day(value: str | None) -> date | None:
    if not value:
        return None
    day = parse_date(value)
    if day is None:
        raise ValidationError({"date": [_("Give a date as YYYY-MM-DD.")]})
    return day


class LeaderboardView(OwnerView):
    @extend_schema(
        parameters=[
            OpenApiParameter("period", str, enum=list(queries.PERIODS)),
            OpenApiParameter("date", str, description="Any day of the week or month wanted."),
            OpenApiParameter("kind", str, enum=["all", "learning"]),
            BRANCH_PARAM,
        ],
        responses=s.OwnerBoardSerializer,
        operation_id="recognition_owner_leaderboard",
    )
    def get(self, request, company_id):
        period = request.query_params.get("period") or "week"
        if period not in queries.PERIODS:
            raise ValidationError({"period": [_("Pick week, month or all.")]})
        kind = request.query_params.get("kind") or "all"
        if kind not in ("all", "learning"):
            raise ValidationError({"kind": [_("Pick all or learning.")]})
        board = queries.leaderboard(
            self.company,
            period=period,
            branch_ids=self.branches(),
            day=_day(request.query_params.get("date")),
            reasons=queries.LEARNING_REASONS if kind == "learning" else None,
        )
        ids = [row.member.pk for row in board.rows]
        badges = {}
        for member_id in BadgeAward.objects.filter(membership_id__in=ids).values_list(
            "membership_id", flat=True
        ):
            badges[member_id] = badges.get(member_id, 0) + 1
        streaks = {
            streak.membership_id: streak
            for streak in Streak.objects.filter(membership_id__in=ids, kind="learning")
        }
        rows = [
            {
                **queries.board_row(row),
                "badges": badges.get(row.member.pk, 0),
                "streak": queries.current_streak(streaks.get(row.member.pk), row.member),
            }
            for row in board.rows
        ]
        return Response(
            s.OwnerBoardSerializer(
                {
                    "period": period,
                    "kind": kind,
                    "start": board.start,
                    "end": board.end,
                    "rows": rows,
                }
            ).data
        )


class PersonView(OwnerView):
    @extend_schema(responses=s.ProfileSerializer, operation_id="recognition_owner_person")
    def get(self, request, company_id, member_id):
        return Response(s.ProfileSerializer(queries.profile(self.person(member_id))).data)


class AdjustView(OwnerView):
    perm = MANAGE

    @extend_schema(
        request=s.AdjustSerializer,
        responses=s.ProfileSerializer,
        operation_id="recognition_owner_adjust",
    )
    def post(self, request, company_id, member_id):
        person = self.person(member_id)
        serializer = s.AdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.adjust(person, by=self.membership, **serializer.validated_data)
        return Response(s.ProfileSerializer(queries.profile(person)).data)


class KudosView(OwnerView):
    perms_by_action = {"post": None}

    @extend_schema(
        parameters=[
            BRANCH_PARAM,
            OpenApiParameter("member", int, description="Thanks sent or received by one person."),
            OpenApiParameter("before", str, description="Older than this moment (paging)."),
        ],
        responses=s.KudosSerializer(many=True),
        operation_id="recognition_owner_kudos",
    )
    def get(self, request, company_id):
        member_id = request.query_params.get("member")
        if member_id:
            if not member_id.isdigit():
                raise ValidationError({"member": [_("Give a number.")]})
            member_id = self.person(int(member_id)).pk
        before = request.query_params.get("before")
        moment: datetime | None = parse_datetime(before) if before else None
        if before and moment is None:
            raise ValidationError({"before": [_("Give a moment as ISO 8601.")]})
        rows = queries.kudos_feed(
            self.company, branch_ids=self.branches(), member_id=member_id or None, before=moment
        )
        return Response(
            s.KudosSerializer(
                [queries.kudos_payload(item, self.membership) for item in rows], many=True
            ).data
        )

    @extend_schema(
        request=s.SendKudosSerializer,
        responses={201: s.KudosSerializer},
        operation_id="recognition_owner_kudos_send",
    )
    def post(self, request, company_id):
        serializer = s.SendKudosSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        receiver = self.person(data["to"])
        kudos = services.send_kudos(
            self.membership, to=receiver, badge=data["badge"], message=data.get("message", "")
        )
        kudos = queries._kudos().get(pk=kudos.pk)
        return Response(
            s.KudosSerializer(queries.kudos_payload(kudos, self.membership)).data,
            status=status.HTTP_201_CREATED,
        )


class HideKudosView(OwnerView):
    perm = MANAGE

    @extend_schema(request=None, responses={204: None}, operation_id="recognition_owner_hide")
    def post(self, request, company_id, kudos_id):
        kudos = (
            Kudos.objects.select_related("from_member", "to_member", "company")
            .filter(company=self.company, pk=kudos_id, hidden_at__isnull=True)
            .first()
        )
        if kudos is None or not (
            in_scope(self.membership, kudos.to_member)
            or in_scope(self.membership, kudos.from_member)
        ):
            raise NotFound
        services.hide_kudos(kudos, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BadgesView(OwnerView):
    @extend_schema(
        parameters=[BRANCH_PARAM],
        responses=s.CatalogueEntrySerializer(many=True),
        operation_id="recognition_owner_badges",
    )
    def get(self, request, company_id):
        holders = queries.badge_holders(self.company, branch_ids=self.branches())
        refs = [award.ref for award in holders.get("topic_expert", [])]
        topics = queries.topic_names(refs)
        entries = []
        for badge in catalogue.BADGES:
            awards = holders.get(badge.key, [])
            entries.append(
                {
                    **queries.catalogue_payload(badge),
                    "count": len(awards),
                    "holders": [
                        {
                            "member": queries.person(award.membership),
                            "ref": award.ref,
                            "name": catalogue.title(
                                award.badge, award.ref, topic=topics.get(award.ref)
                            ),
                            "awarded_at": award.awarded_at,
                        }
                        for award in awards
                    ],
                }
            )
        return Response(s.CatalogueEntrySerializer(entries, many=True).data)


class SettingsView(OwnerView):
    perms_by_action = {"patch": MANAGE}

    def _data(self):
        row = conf.get_settings(self.company)
        merged = rules.table(row.points_table)
        return {
            **{field: getattr(row, field) for field in services.SETTING_FIELDS},
            "points": [
                {
                    "key": key,
                    "label": str(rules.POINT_LABELS[key]),
                    "default": default,
                    "points": merged[key],
                }
                for key, default in rules.POINTS.items()
            ],
            "levels": [asdict(level) for level in queries.levels()],
        }

    @extend_schema(responses=s.SettingsSerializer, operation_id="recognition_owner_settings")
    def get(self, request, company_id):
        return Response(s.SettingsSerializer(self._data()).data)

    @extend_schema(
        request=s.SettingsSerializer,
        responses=s.SettingsSerializer,
        operation_id="recognition_owner_settings_update",
    )
    def patch(self, request, company_id):
        serializer = s.SettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_settings(self.company, by=self.membership, **serializer.validated_data)
        return Response(s.SettingsSerializer(self._data()).data)
