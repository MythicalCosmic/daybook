from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.members.api import IsCompanyMember, MemberBriefSerializer, requires
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.reports import kpis
from apps.reports.periods import Period, bounds


class ScoreSerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Shared tasks whose deadline passed in the period.")
    on_time = serializers.IntegerField()
    late = serializers.IntegerField(help_text="Finished after the deadline.")
    missed = serializers.IntegerField(help_text="Still not finished.")
    on_time_percent = serializers.IntegerField(allow_null=True)
    avg_delay_minutes = serializers.IntegerField(
        allow_null=True, help_text="How late the late ones were, on average."
    )
    late_now = serializers.IntegerField(help_text="Open and overdue right now.")
    reminders = serializers.IntegerField(help_text="Reminders the bot had to send.")


class TeamRowSerializer(ScoreSerializer):
    member = MemberBriefSerializer()


class TeamStatsSerializer(serializers.Serializer):
    period = serializers.ChoiceField(Period.choices)
    start = serializers.DateField()
    end = serializers.DateField(help_text="The period's last day.")
    totals = ScoreSerializer()
    members = TeamRowSerializer(many=True, help_text="Everyone registered, best first.")


class TeamStatsView(APIView):
    """How everyone's shared work went: on time, late, missed. Needs reports.view."""

    permission_classes = (IsAuthenticated, IsCompanyMember, requires(Perm.REPORTS_VIEW))

    @extend_schema(
        parameters=[OpenApiParameter("period", enum=Period.values, default=Period.WEEK)],
        responses=TeamStatsSerializer,
    )
    def get(self, request, company_id):
        period = request.query_params.get("period", Period.WEEK)
        if period not in Period.values:
            raise serializers.ValidationError({"period": [f"Pick one of: {', '.join(Period)}."]})
        company = self.membership.company
        now = timezone.now()
        today = timezone.localtime(now, ZoneInfo(company.timezone)).date()
        start, end = bounds(Period(period), today)
        report = kpis.team(company, start, end, now)
        data = {
            "period": period,
            "start": start,
            "end": end - timedelta(days=1),
            "totals": report.totals,
            "members": [_row(person, score) for person, score in report.rows],
        }
        return Response(TeamStatsSerializer(data).data)


def _row(person: Membership, score: kpis.Score) -> dict:
    return {"member": person} | {name: getattr(score, name) for name in ScoreSerializer().fields}
