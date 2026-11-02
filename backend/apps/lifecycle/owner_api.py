"""Owner dashboard endpoints of the people lifecycle (`lifecycle/…`, docs/PLAN-OWNER.md §13.4).

    CRUD  lifecycle/discipline/?member&kind&category&status&active&from&to&branch&q
          (read: hr.discipline or hr.view; write: hr.discipline)
    POST  lifecycle/discipline/{id}/withdraw/ {reason} · …/fine/ {amount}
    GET   lifecycle/suspensions/                     who is suspended (hr.suspend or hr.view)
    POST  lifecycle/suspensions/ {member_id, until, reason}
    POST  lifecycle/suspensions/{member_id}/reinstate/          (hr.suspend)

Company- and branch-scoped (someone outside the caller's branches answers 404), 403 while the
HR module is off. Suspending is `members.services.suspend/reinstate`, rules and all.
"""

from datetime import date

from django.db.models import Q
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.console.base import OwnerViewSet
from apps.console.perms import AnyOf
from apps.hr import queries as hr_queries
from apps.lifecycle import queries, services
from apps.lifecycle import serializers as s
from apps.lifecycle.models import DisciplinaryRecord
from apps.members import services as members
from apps.members.models import Membership
from apps.members.permissions import Perm

READ_RECORDS = AnyOf(Perm.HR_DISCIPLINE, Perm.HR_VIEW)
READ_SUSPENSIONS = AnyOf(Perm.HR_SUSPEND, Perm.HR_VIEW)
BRANCH_PARAM = OpenApiParameter("branch", int, many=True, description="Branch ids (in scope).")


class ModuleOn:
    """403 while HR (and with it the lifecycle) is switched off for the company."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.company.has_feature("hr"):
            raise PermissionDenied(_("HR isn't switched on for this company."))


class LifecycleContext:
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["today"] = hr_queries.today(self.company)
        # Every row these views show comes from a query limited to the viewer's branches.
        context["in_scope"] = True
        return context

    def person(self, member_id) -> Membership:
        found = hr_queries.person(self.company, member_id, branch_ids=self.branch_scope)
        if found is None:
            raise NotFound
        return found


def _int(value, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: [_("Give a number.")]}) from exc


def _day(value, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: [_("Give a day as YYYY-MM-DD.")]}) from exc


class DisciplineViewSet(
    ModuleOn,
    LifecycleContext,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    OwnerViewSet,
):
    """Warnings and reprimands, with the person's explanation and the fine proposed."""

    perm = READ_RECORDS
    perms_by_action = {
        "create": Perm.HR_DISCIPLINE,
        "partial_update": Perm.HR_DISCIPLINE,
        "destroy": Perm.HR_DISCIPLINE,
        "withdraw": Perm.HR_DISCIPLINE,
        "fine": Perm.HR_DISCIPLINE,
    }
    serializer_class = s.RecordSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DisciplinaryRecord.objects.none()
        rows = queries.records(self.company, branch_ids=self.branch_scope).select_related(
            "membership__user",
            "membership__position",
            "membership__home_branch",
            "membership__role",
            "membership__company",
            "issued_by__user",
            "company",
        )
        if self.action != "list":
            return rows
        params = self.request.query_params
        if member := _int(params.get("member"), "member"):
            rows = rows.filter(membership_id=member)
        kinds = [value for value in params.getlist("kind") if value in DisciplinaryRecord.Kind]
        if kinds:
            rows = rows.filter(kind__in=kinds)
        categories = [
            value for value in params.getlist("category") if value in DisciplinaryRecord.Category
        ]
        if categories:
            rows = rows.filter(category__in=categories)
        statuses = [
            value for value in params.getlist("status") if value in DisciplinaryRecord.Status
        ]
        if statuses:
            rows = rows.filter(status__in=statuses)
        if params.get("active") == "true":
            rows = queries.active(rows, hr_queries.today(self.company))
        if start := _day(params.get("from"), "from"):
            rows = rows.filter(issued_on__gte=start)
        if end := _day(params.get("to"), "to"):
            rows = rows.filter(issued_on__lte=end)
        branches = [int(b) for b in params.getlist("branch") if str(b).isdigit()]
        if branches:
            rows = rows.filter(membership__branches__in=branches).distinct()
        if q := (params.get("q") or "").strip():
            for word in q.split()[:4]:
                rows = rows.filter(
                    Q(membership__first_name__icontains=word)
                    | Q(membership__last_name__icontains=word)
                )
        return rows.order_by("-issued_on", "-pk")

    @extend_schema(
        parameters=[
            OpenApiParameter("member", int),
            OpenApiParameter("kind", str, many=True, enum=list(DisciplinaryRecord.Kind.values)),
            OpenApiParameter(
                "category", str, many=True, enum=list(DisciplinaryRecord.Category.values)
            ),
            OpenApiParameter("status", str, many=True, enum=list(DisciplinaryRecord.Status.values)),
            OpenApiParameter("active", bool, description="Only records that still count."),
            OpenApiParameter("from", str, description="Given on or after (YYYY-MM-DD)."),
            OpenApiParameter("to", str, description="Given on or before (YYYY-MM-DD)."),
            OpenApiParameter("q", str),
            BRANCH_PARAM,
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.RecordWriteSerializer, responses={201: s.RecordSerializer})
    def create(self, request, company_id):
        data = self.write_data()
        member = self.person(data.pop("member_id", None))
        for name in ("kind", "category", "description"):
            if not data.get(name):
                raise ValidationError({name: [_("This field is required.")]})
        if "expires_on" not in data:
            data["expires_on"] = services.UNSET
        record = services.issue(member, by=self.membership, **data)
        return Response(
            self.get_serializer(self.reload(record)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=s.RecordWriteSerializer, responses=s.RecordSerializer)
    def partial_update(self, request, company_id, pk):
        record = self.get_object()
        data = self.write_data()
        data.pop("member_id", None)
        if data.pop("fine_amount", None) is not None:
            raise ValidationError({"fine_amount": [_("Propose a fine with its own button.")]})
        record = services.update(record, by=self.membership, **data)
        return Response(self.get_serializer(self.reload(record)).data)

    def perform_destroy(self, instance):
        services.delete(instance, by=self.membership)

    @extend_schema(request=s.WithdrawSerializer, responses=s.RecordSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, company_id, pk):
        record = self.get_object()
        serializer = s.WithdrawSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.withdraw(
            record, by=self.membership, reason=serializer.validated_data["reason"]
        )
        return Response(self.get_serializer(self.reload(record)).data)

    @extend_schema(request=s.FineRequestSerializer, responses=s.RecordSerializer)
    @action(detail=True, methods=["post"])
    def fine(self, request, company_id, pk):
        record = self.get_object()
        serializer = s.FineRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.propose_fine(
            record, by=self.membership, amount=serializer.validated_data["amount"]
        )
        return Response(self.get_serializer(self.reload(record)).data)

    def write_data(self) -> dict:
        serializer = s.RecordWriteSerializer(data=self.request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if data.get("evidence") is None:
            data.pop("evidence", None)
        if data.get("fine_amount") is None:
            data.pop("fine_amount", None)
        return data

    def reload(self, record: DisciplinaryRecord) -> DisciplinaryRecord:
        return self.get_queryset().get(pk=record.pk)


class SuspensionViewSet(ModuleOn, LifecycleContext, mixins.ListModelMixin, OwnerViewSet):
    """Who is suspended until when and why; suspend and reinstate (members' own rules)."""

    perm = READ_SUSPENSIONS
    perms_by_action = {"create": Perm.HR_SUSPEND, "reinstate": Perm.HR_SUSPEND}
    serializer_class = s.SuspensionSerializer
    pagination_class = None
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        return Membership.objects.none()

    @extend_schema(parameters=[BRANCH_PARAM], responses=s.SuspensionSerializer(many=True))
    def list(self, request, company_id):
        rows = queries.suspended(self.company, branch_ids=self.branch_scope)
        branches = {int(b) for b in request.query_params.getlist("branch") if str(b).isdigit()}
        if branches:
            rows = [
                row
                for row in rows
                if branches & set(row["member"].branches.values_list("pk", flat=True))
            ]
        return Response(self.get_serializer(rows, many=True).data)

    @extend_schema(request=s.SuspendSerializer, responses={201: s.SuspensionSerializer})
    def create(self, request, company_id):
        serializer = s.SuspendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        person = self.person(data["member_id"])
        members.suspend(person, by=self.membership, until=data.get("until"), reason=data["reason"])
        return Response(self.row(person.pk), status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def reinstate(self, request, company_id, pk):
        person = self.person(pk)
        members.reinstate(person, by=self.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def row(self, member_id: int) -> dict:
        rows = queries.suspended(self.company, branch_ids=self.branch_scope)
        found = next(row for row in rows if row["member"].pk == member_id)
        return self.get_serializer(found).data
