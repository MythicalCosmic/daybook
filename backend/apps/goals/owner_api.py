"""Owner endpoints of business goals, mounted at `/api/v1/owner/companies/<id>/goals/`:

    GET    POST  goals/                 the goals (`?status=active|done|archived`); set one
    GET    PATCH DELETE goals/<id>/     one goal with its series; change it; delete it
    POST   goals/<id>/archive/  …/restore/
    GET    goals/metrics/               what goals can measure here, with branches and people
    GET    goals/preview/               a metric's value and pace for a period, before saving

Reading needs `reports.view` and the permission of the goal's numbers (a profit goal
`finance.view`); goals for one branch follow the caller's branch scope and company-wide goals
need every branch. Setting goals needs `company.settings` as well (the owners'). Every change is
audited by the services and bumps the `goals` pulse after commit.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, status
from rest_framework.response import Response

from apps.companies.models import Branch
from apps.console.base import AllOf, OwnerAPIView
from apps.goals import progress, queries, services
from apps.goals import serializers as s
from apps.goals.metrics import METRICS
from apps.goals.models import Goal
from apps.members.models import Membership
from apps.members.permissions import Perm

VIEW = Perm.REPORTS_VIEW
MANAGE = AllOf(Perm.REPORTS_VIEW, Perm.COMPANY_SETTINGS)
PULSE = "goals"
TABS = {
    "active": (Goal.Status.ACTIVE,),
    "done": (Goal.Status.ACHIEVED, Goal.Status.MISSED),
    "archived": (Goal.Status.ARCHIVED,),
}


def _jsonable(value):
    """Decimals as strings, days as ISO."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


class GoalsMixin:
    perm = VIEW

    @property
    def today(self) -> date:
        return services.local_today(self.company)

    def goal(self, pk) -> Goal:
        found = get_object_or_404(queries.visible(self.membership), pk=pk)
        return found

    def payload(self, goal: Goal) -> dict:
        data = queries.summary(goal, self.today)
        data["can_edit"] = queries.can_manage(self.membership)
        return data

    def branch(self, pk) -> Branch | None:
        member_scope = self.branch_scope
        if pk is None:
            if member_scope is not None:
                raise exceptions.ValidationError(
                    {"branch": [_("Pick one of your branches: company-wide goals need every one.")]}
                )
            return None
        found = Branch.objects.filter(company=self.company, pk=pk, is_active=True).first()
        if found is None or (member_scope is not None and found.pk not in member_scope):
            raise exceptions.ValidationError({"branch": [_("Pick one of your branches.")]})
        return found

    def person(self, pk) -> Membership | None:
        if pk is None:
            return None
        found = (
            Membership.objects.for_company(self.company)
            .filter(pk=pk, status=Membership.Status.APPROVED)
            .first()
        )
        if found is None:
            raise exceptions.ValidationError({"owner": [_("Pick someone from the team.")]})
        return found

    def changed(self) -> None:
        self.bump(PULSE)


class GoalsView(GoalsMixin, OwnerAPIView):
    """The goals of a tab with their progress now and their weekly series; POST sets one."""

    perms_by_action = {"post": MANAGE}

    @extend_schema(
        parameters=[OpenApiParameter("status", str, enum=list(TABS), description="active")],
        responses=s.GoalListSerializer,
        operation_id="companies_goals_list",
    )
    def get(self, request, company_id):
        tab = request.query_params.get("status") or "active"
        if tab not in TABS:
            raise exceptions.ValidationError({"status": [_("active, done or archived.")]})
        rows = queries.visible(self.membership)
        counts = {key: rows.filter(status__in=statuses).count() for key, statuses in TABS.items()}
        chosen = rows.filter(status__in=TABS[tab]).order_by(
            "ends_on" if tab == "active" else "-ends_on", "pk"
        )
        return Response(
            _jsonable(
                {
                    "today": self.today,
                    "currency": self.company.base_currency,
                    "can_manage": queries.can_manage(self.membership),
                    "goals": [self.payload(goal) for goal in chosen],
                    "counts": counts,
                }
            )
        )

    @extend_schema(request=s.GoalInputSerializer, responses={201: s.GoalSerializer})
    def post(self, request, company_id):
        serializer = s.GoalInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not METRICS[data["metric"]].visible_to(self.membership):
            raise exceptions.PermissionDenied(_("You don't see the numbers this goal measures."))
        goal = services.create_goal(
            self.company,
            by=self.membership,
            title=data["title"],
            metric=data["metric"],
            target=data["target"],
            starts_on=data["starts_on"],
            ends_on=data["ends_on"],
            branch=self.branch(data.get("branch")),
            owner=self.person(data.get("owner")),
            note=data.get("note", ""),
        )
        self.changed()
        return Response(_jsonable(self.payload(goal)), status=status.HTTP_201_CREATED)


class GoalView(GoalsMixin, OwnerAPIView):
    """One goal with its whole weekly series; PATCH changes it, DELETE removes it."""

    perms_by_action = {"patch": MANAGE, "delete": MANAGE}

    @extend_schema(responses=s.GoalSerializer)
    def get(self, request, company_id, pk):
        goal = self.goal(pk)
        data = self.payload(goal)
        data["series"] = queries.series(goal, queries.live(goal, self.today), limit=120)
        return Response(_jsonable(data))

    @extend_schema(request=s.GoalPatchSerializer, responses=s.GoalSerializer)
    def patch(self, request, company_id, pk):
        goal = self.goal(pk)
        serializer = s.GoalPatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        if "owner" in fields:
            fields["owner"] = self.person(fields["owner"])
        goal = services.update_goal(goal, by=self.membership, **fields)
        self.changed()
        return Response(_jsonable(self.payload(goal)))

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, company_id, pk):
        services.delete_goal(self.goal(pk), by=self.membership)
        self.changed()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GoalArchiveView(GoalsMixin, OwnerAPIView):
    """Put a goal away (it stops being measured and told about)."""

    perm = MANAGE

    @extend_schema(request=None, responses=s.GoalSerializer)
    def post(self, request, company_id, pk):
        goal = services.archive_goal(self.goal(pk), by=self.membership)
        self.changed()
        return Response(_jsonable(self.payload(goal)))


class GoalRestoreView(GoalArchiveView):
    """Bring an archived goal back."""

    @extend_schema(request=None, responses=s.GoalSerializer)
    def post(self, request, company_id, pk):
        goal = services.restore_goal(self.goal(pk), by=self.membership)
        self.changed()
        return Response(_jsonable(self.payload(goal)))


class MetricsView(GoalsMixin, OwnerAPIView):
    """What a goal can measure here (a module that is off says so), the branches and people to
    pick."""

    @extend_schema(responses=s.MetricsSerializer)
    def get(self, request, company_id):
        member = self.membership
        member_scope = self.branch_scope
        branches = Branch.objects.filter(company=self.company, is_active=True).order_by(
            "order", "pk"
        )
        if member_scope is not None:
            branches = branches.filter(pk__in=member_scope)
        people = (
            Membership.objects.for_company(self.company)
            .filter(status=Membership.Status.APPROVED)
            .order_by("first_name", "last_name", "pk")
        )
        return Response(
            {
                "metrics": [
                    {
                        "key": metric.key,
                        "label": str(metric.label),
                        "hint": str(metric.hint),
                        "unit": metric.unit,
                        "better": metric.better,
                        "kind": metric.kind,
                        "branchable": metric.branchable,
                        "available": metric.available(self.company),
                        "feature": metric.feature,
                    }
                    for metric in METRICS.values()
                    if metric.visible_to(member)
                ],
                "branches": [{"id": row.pk, "name": row.name} for row in branches],
                "people": [{"id": row.pk, "name": str(row)} for row in people],
                "company_wide": member_scope is None,
            }
        )


class PreviewView(GoalsMixin, OwnerAPIView):
    """A metric's value so far and its pace to the period's end, with the state a target would
    have: what the goal dialog shows while someone types."""

    @extend_schema(
        parameters=[
            OpenApiParameter("metric", str, required=True),
            OpenApiParameter("starts_on", str, required=True),
            OpenApiParameter("ends_on", str, required=True),
            OpenApiParameter("branch", int),
            OpenApiParameter("target", str),
        ],
        responses=s.PreviewSerializer,
    )
    def get(self, request, company_id):
        params = request.query_params
        metric = METRICS.get(params.get("metric") or "")
        if metric is None or not metric.visible_to(self.membership):
            raise exceptions.ValidationError({"metric": [_("Pick what the goal measures.")]})
        try:
            starts_on = date.fromisoformat(params.get("starts_on", ""))
            ends_on = date.fromisoformat(params.get("ends_on", ""))
        except ValueError:
            raise exceptions.ValidationError({"starts_on": [_("A day like 2026-10-01.")]}) from None
        if ends_on < starts_on:
            raise exceptions.ValidationError({"ends_on": [_("The goal ends before it starts.")]})
        raw_branch = params.get("branch")
        branch = self.branch(int(raw_branch) if raw_branch and raw_branch.isdigit() else None)
        try:
            target = Decimal(params.get("target") or "0")
        except InvalidOperation:
            target = Decimal(0)
        if not target.is_finite() or target < 0:
            target = Decimal(0)
        draft = Goal(
            company=self.company,
            title="",
            metric=metric.key,
            target=target or Decimal(1),
            starts_on=starts_on,
            ends_on=ends_on,
            branch=branch,
        )
        result = progress.evaluate(draft, self.today)
        has_target = bool(target)
        return Response(
            _jsonable(
                {
                    "metric": metric.key,
                    "state": result.state if has_target else None,
                    "value": result.value,
                    "forecast": result.forecast,
                    "baseline": result.baseline,
                    "progress": result.progress if has_target else None,
                    "days_left": result.days_left,
                }
            )
        )
