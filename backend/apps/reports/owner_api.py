"""Owner endpoints of team reports (docs/PLAN-OWNER.md §4.5): team KPIs over any range with a
comparison, grouped by person, position, routine, branch or day, and routine compliance. Both
answer the analytics shape of §4 (`range`, `compare`, `totals`, `previous`, `series`,
`breakdown`), so KpiCard and ChartCard render them. Personal tasks never count."""

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import exceptions, serializers
from rest_framework.response import Response

from apps.console.base import OwnerAPIView, RangeMixin
from apps.members.permissions import Perm
from apps.reports import kpis
from apps.tasks.owner_serializers import person

RANGE_PARAMS = [
    OpenApiParameter("from", description="First day, YYYY-MM-DD."),
    OpenApiParameter("to", description="Last day, YYYY-MM-DD (inclusive)."),
    OpenApiParameter(
        "preset",
        enum=[
            "today",
            "yesterday",
            "week",
            "last_week",
            "month",
            "last_month",
            "last_30",
            "quarter",
            "year",
        ],
    ),
    OpenApiParameter("compare", enum=["none", "prev", "year"]),
    OpenApiParameter(
        "branch", int, many=True, description="Narrow to these branches (within yours)."
    ),
]

ScoreShape = inline_serializer(
    "ReportsScore",
    {
        "total": serializers.IntegerField(),
        "done": serializers.IntegerField(),
        "on_time": serializers.IntegerField(),
        "late": serializers.IntegerField(),
        "missed": serializers.IntegerField(),
        "on_time_percent": serializers.FloatField(allow_null=True),
        "late_now": serializers.IntegerField(),
        "reminders": serializers.IntegerField(),
        "avg_delay_minutes": serializers.IntegerField(allow_null=True),
    },
)


class ReportsView(RangeMixin, OwnerAPIView):
    perm = Perm.REPORTS_VIEW

    def scope(self) -> list[int] | None:
        """The caller's branch scope, narrowed by `?branch=` (never widened)."""
        mine = self.branch_scope
        chosen = []
        for value in self.request.query_params.getlist("branch"):
            chosen += [int(part) for part in value.split(",") if part.isdigit()]
        if not chosen:
            return mine
        return [pk for pk in chosen if mine is None or pk in mine]

    def series_group(self) -> str:
        days = self.range.days
        return "day" if days <= 62 else "week" if days <= 366 else "month"


class TeamReportView(ReportsView):
    """Team KPIs for a range, optionally against a comparison range."""

    @extend_schema(
        parameters=[
            *RANGE_PARAMS,
            OpenApiParameter("group_by", enum=list(kpis.GROUPS), default="member"),
        ],
        responses=inline_serializer(
            "ReportsTeam",
            {
                "range": serializers.DictField(),
                "compare": serializers.DictField(allow_null=True),
                "group_by": serializers.CharField(),
                "totals": ScoreShape,
                "previous": ScoreShape,
                "series": serializers.ListField(child=serializers.DictField()),
                "breakdown": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    def get(self, request, company_id):
        group_by = request.query_params.get("group_by", "member")
        if group_by not in kpis.GROUPS:
            raise exceptions.ValidationError(
                {"group_by": [_("Pick one of: %(groups)s.") % {"groups": ", ".join(kpis.GROUPS)}]}
            )
        company, now, scope, period = self.company, timezone.now(), self.scope(), self.range
        rows = kpis.team_grouped(company, period.start, period.end, now, group_by, branch_ids=scope)
        totals = (
            kpis.sum_rows(rows)
            if group_by != "member"
            else kpis.team(
                company, period.start, period.end + timedelta(days=1), now, branch_ids=scope
            ).totals
        )
        previous = None
        compare_rows = {}
        if period.has_compare:
            before = kpis.team_grouped(
                company, period.compare_start, period.compare_end, now, group_by, branch_ids=scope
            )
            previous = kpis.sum_rows(before).as_dict()
            compare_rows = {row.key: row.score for row in before}
        series = kpis.trend(
            company,
            "on_time_percent",
            period.start,
            period.end,
            self.series_group(),
            branch_ids=scope,
        )
        return Response(
            period.as_dict()
            | {
                "group_by": group_by,
                "totals": totals.as_dict(),
                "previous": previous,
                "series": series,
                "breakdown": [_breakdown(row, compare_rows.get(row.key)) for row in rows],
            }
        )


class RoutineReportView(ReportsView):
    """Every routine's compliance over a range (routines nobody does included)."""

    @extend_schema(
        parameters=RANGE_PARAMS,
        responses=inline_serializer(
            "ReportsRoutines",
            {
                "range": serializers.DictField(),
                "compare": serializers.DictField(allow_null=True),
                "totals": serializers.DictField(),
                "previous": serializers.DictField(allow_null=True),
                "series": serializers.ListField(child=serializers.DictField()),
                "breakdown": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    def get(self, request, company_id):
        company, scope, period = self.company, self.scope(), self.range
        rows = kpis.routine_compliance(company, period.start, period.end, branch_ids=scope)
        previous = None
        before = {}
        if period.has_compare:
            compare = kpis.routine_compliance(
                company, period.compare_start, period.compare_end, branch_ids=scope
            )
            before = {row["id"]: row for row in compare}
            previous = _routine_totals(compare)
        series = kpis.trend(
            company,
            "on_time_percent",
            period.start,
            period.end,
            self.series_group(),
            branch_ids=scope,
        )
        breakdown = [
            {
                "key": str(row["id"]),
                "label": row["title"],
                **row,
                "previous_on_time_percent": before.get(row["id"], {}).get("on_time_percent"),
            }
            for row in rows
        ]
        return Response(
            period.as_dict()
            | {
                "totals": _routine_totals(rows),
                "previous": previous,
                "series": series,
                "breakdown": breakdown,
            }
        )


def _breakdown(row: kpis.Row, previous: kpis.Score | None) -> dict:
    data = {"key": row.key, "label": row.label, **row.score.as_dict(), **row.extra}
    if row.member is not None:
        data["member"] = person(row.member)
    data["previous_on_time_percent"] = previous.on_time_exact if previous is not None else None
    return data


def _routine_totals(rows: list[dict]) -> dict:
    made = sum(row["made"] for row in rows)
    on_time = sum(row["on_time"] for row in rows)
    done = on_time + sum(row["late"] for row in rows)
    return {
        "routines": len(rows),
        "made": made,
        "on_time": on_time,
        "late": sum(row["late"] for row in rows),
        "missed": sum(row["missed"] for row in rows),
        "on_time_percent": round(100 * on_time / made, 1) if made else None,
        "completion_percent": round(100 * done / made, 1) if made else None,
        "idle": sum(1 for row in rows if row["made"] == 0),
    }
