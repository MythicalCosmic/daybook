"""Owner dashboard endpoints of insights and the owner's cockpit; routed in `owner_urls.py`.

    GET   cockpit/                              Egasi paneli in one call (finance.view or
                                                reports.view; money only with finance.view)
    GET   insights/?status&kind&severity&domain&branch&limit
                                                live insights by default (reports.view and
                                                each domain's permission, branch-scoped)
    GET   insights/{id}/
    POST  insights/{id}/acknowledge/            seen
    POST  insights/{id}/dismiss/                {reason?}
    POST  insights/{id}/resolve/
    POST  insights/{id}/make-task/              {assignee_id?, due_on?, title?}
    GET/PATCH insights/settings/                ai.configure or company.settings
    POST  insights/check/                       run the rules now (same perms, once a minute)

An insight outside the caller's company, branch scope or domains answers 404.
"""

from django.core.cache import cache
from django.db import transaction
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions
from rest_framework.response import Response

from apps.console.base import AnyOf, OwnerAPIView
from apps.insights import access, cockpit, conf, detectors, queries, services
from apps.insights import serializers as s
from apps.insights.models import Insight
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import in_scope

READ = access.BASE
COCKPIT = AnyOf(Perm.FINANCE_VIEW, Perm.REPORTS_VIEW)
CONFIGURE = AnyOf(Perm.AI_CONFIGURE, Perm.COMPANY_SETTINGS)
PAGE = 50
MAX_PAGE = 200
CHECK_EVERY = 60  # seconds between two "Check now" runs of a company


class CockpitView(OwnerAPIView):
    """Egasi paneli: profit by branch, cash and runway, decisions waiting, insights."""

    perm = COCKPIT

    @extend_schema(responses=s.CockpitSerializer, operation_id="insights_owner_cockpit")
    def get(self, request, company_id):
        return Response(cockpit.build(self.membership))


def _choice(value: str | None, allowed, name: str):
    if value and value not in allowed:
        raise exceptions.ValidationError({name: [_("Pick one of the listed values.")]})
    return value or None


class InsightListView(OwnerAPIView):
    perm = READ

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status", str, description="live (default: open and seen), all, or one status."
            ),
            OpenApiParameter("kind", str, enum=Insight.Kind.values),
            OpenApiParameter("severity", str, enum=Insight.Severity.values),
            OpenApiParameter("domain", str, enum=Insight.Domain.values),
            OpenApiParameter("branch", int),
            OpenApiParameter("limit", int, description=f"At most {MAX_PAGE}."),
        ],
        responses=s.InsightListSerializer,
        operation_id="insights_owner_list",
    )
    def get(self, request, company_id):
        params = request.query_params
        status = params.get("status") or "live"
        if status not in ("live", "all", *Insight.Status.values):
            raise exceptions.ValidationError({"status": [_("Pick one of the listed values.")]})
        filters = {
            "status": status,
            "kind": _choice(params.get("kind"), Insight.Kind.values, "kind"),
            "severity": _choice(params.get("severity"), Insight.Severity.values, "severity"),
            "domain": _choice(params.get("domain"), Insight.Domain.values, "domain"),
            "branch": _int(params.get("branch"), "branch"),
        }
        limit = min(_int(params.get("limit"), "limit") or PAGE, MAX_PAGE)
        rows = queries.visible(self.membership, filters)
        return Response(
            {"count": rows.count(), "results": [queries.as_dict(row) for row in rows[:limit]]}
        )


def _int(value, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise exceptions.ValidationError({name: [_("Give a number.")]}) from exc


class InsightMixin:
    perm = READ

    def insight(self, pk) -> Insight:
        found = access.visible(self.membership).select_related("branch", "task").filter(pk=pk)
        insight = found.first()
        if insight is None:
            raise exceptions.NotFound
        return insight


class InsightDetailView(InsightMixin, OwnerAPIView):
    @extend_schema(responses=s.InsightSerializer, operation_id="insights_owner_detail")
    def get(self, request, company_id, pk):
        return Response(queries.as_dict(self.insight(pk)))


def _fresh(insight: Insight) -> dict:
    return queries.as_dict(Insight.objects.select_related("branch", "task").get(pk=insight.pk))


class AcknowledgeView(InsightMixin, OwnerAPIView):
    @extend_schema(request=None, responses=s.InsightSerializer, operation_id="insights_owner_ack")
    def post(self, request, company_id, pk):
        insight = services.acknowledge(self.insight(pk), by=self.membership)
        return Response(_fresh(insight))


class DismissView(InsightMixin, OwnerAPIView):
    @extend_schema(
        request=s.DismissSerializer,
        responses=s.InsightSerializer,
        operation_id="insights_owner_dismiss",
    )
    def post(self, request, company_id, pk):
        body = s.DismissSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        insight = services.dismiss(
            self.insight(pk), by=self.membership, reason=body.validated_data.get("reason", "")
        )
        return Response(_fresh(insight))


class ResolveView(InsightMixin, OwnerAPIView):
    @extend_schema(
        request=None, responses=s.InsightSerializer, operation_id="insights_owner_resolve"
    )
    def post(self, request, company_id, pk):
        insight = services.resolve(self.insight(pk), by=self.membership)
        return Response(_fresh(insight))


class MakeTaskView(InsightMixin, OwnerAPIView):
    @extend_schema(
        request=s.MakeTaskSerializer,
        responses=s.MadeTaskSerializer,
        operation_id="insights_owner_make_task",
    )
    def post(self, request, company_id, pk):
        body = s.MakeTaskSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        insight = self.insight(pk)
        assignee = None
        if body.validated_data.get("assignee_id"):
            assignee = (
                Membership.objects.select_related("user", "company", "home_branch")
                .filter(
                    company=self.company,
                    pk=body.validated_data["assignee_id"],
                    status=Membership.Status.APPROVED,
                )
                .first()
            )
            if assignee is None or not in_scope(self.membership, assignee):
                raise exceptions.ValidationError({"assignee_id": [_("Pick someone you see.")]})
        task = services.make_task(
            insight,
            by=self.membership,
            assignee=assignee,
            due_on=body.validated_data.get("due_on"),
            title=body.validated_data.get("title") or "",
        )
        return Response(
            {
                "insight": _fresh(insight),
                "task": {"id": task.pk, "title": task.title, "status": task.status},
            }
        )


class SettingsView(OwnerAPIView):
    perm = CONFIGURE

    def _data(self) -> dict:
        row = conf.get_settings(self.company)
        data = s.InsightSettingsSerializer(row).data
        return {
            **data,
            "kinds": [
                {
                    "kind": kind.value,
                    "label": str(kind.label),
                    "domain": detectors.domain_of(kind.value),
                    "available": kind.value in access.kinds_on(self.company),
                }
                for kind in Insight.Kind
            ],
            "last_run_at": row.last_run_at,
        }

    @extend_schema(
        responses=s.InsightSettingsResponseSerializer, operation_id="insights_owner_settings"
    )
    def get(self, request, company_id):
        return Response(self._data())

    @extend_schema(
        request=s.InsightSettingsSerializer,
        responses=s.InsightSettingsResponseSerializer,
        operation_id="insights_owner_settings_update",
    )
    def patch(self, request, company_id):
        body = s.InsightSettingsSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        services.update_settings(self.company, by=self.membership, **body.validated_data)
        return Response(self._data())


class CheckView(OwnerAPIView):
    """Run the rules now (the cockpit's "Check now"), at most once a minute per company."""

    perm = CONFIGURE

    @extend_schema(
        request=None, responses=s.CheckResultSerializer, operation_id="insights_owner_check"
    )
    def post(self, request, company_id):
        if not cache.add(f"insights:check:{self.company.pk}", 1, CHECK_EVERY):
            raise exceptions.Throttled(wait=CHECK_EVERY)
        with transaction.atomic():
            result = services.check_now(self.company, by=self.membership)
        return Response(result)
