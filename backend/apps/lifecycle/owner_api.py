"""Owner dashboard endpoints of the people lifecycle (`lifecycle/…`, docs/PLAN-OWNER.md §13.4).

    CRUD  lifecycle/discipline/?member&kind&category&status&active&from&to&branch&q
          (read: hr.discipline or hr.view; write: hr.discipline)
    POST  lifecycle/discipline/{id}/withdraw/ {reason} · …/fine/ {amount}
    GET   lifecycle/suspensions/                     who is suspended (hr.suspend or hr.view)
    POST  lifecycle/suspensions/ {member_id, until, reason}
    POST  lifecycle/suspensions/{member_id}/reinstate/          (hr.suspend)

    GET   lifecycle/terminations/?status&kind&member&branch&q · …/counts/ · …/{id}/
          (read: hr.terminate or hr.view; the rest hr.terminate)
    POST  lifecycle/terminations/ {member_id, kind, last_day, reason, leave_days, final_payslip}
    PATCH lifecycle/terminations/{id}/ {kind, reason, notes, rehire, leave_days, final_payslip}
    POST  lifecycle/terminations/{id}/agree/ {last_day?, leave_days?, final_payslip?}
    POST  lifecycle/terminations/{id}/decline/ {reason} · …/withdraw/ {reason} · …/retry/
    POST  lifecycle/terminations/{id}/handover/ {title, kind}
    PATCH/DELETE lifecycle/terminations/{id}/handover/{item_id}/ {done, note}

    GET   lifecycle/job-changes/?status&member&branch&q · …/counts/ · …/{id}/
          · …/current/?member=  (read: hr.manage or hr.view; the rest hr.manage)
    POST  lifecycle/job-changes/ {member_id, effective_on, reason, position_id?, branch_id?,
          department_id?, pay_amount?, pay_type?, approve?}
    POST  lifecycle/job-changes/{id}/approve/ · …/reject/ {reason} · …/cancel/ {reason} · …/retry/
    GET   lifecycle/people/{member_id}/career/   hired, job changes, leaving (hr.view and the like)

Company- and branch-scoped (someone outside the caller's branches answers 404), 403 while the
HR module is off. Suspending is `members.services.suspend/reinstate`, rules and all; leaving is
`apps.lifecycle.terminations`, job changes `apps.lifecycle.job_changes`. Pay shows only with
payroll.view.
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

from apps.companies.models import Branch
from apps.console.base import OwnerAPIView, OwnerViewSet
from apps.console.perms import AnyOf
from apps.hr import queries as hr_queries
from apps.lifecycle import integrations, job_changes, queries, services, terminations
from apps.lifecycle import serializers as s
from apps.lifecycle.models import DisciplinaryRecord, HandoverItem, JobChange, Termination
from apps.members import services as members
from apps.members.models import Department, Membership, Position
from apps.members.permissions import Perm
from apps.members.queries import branch_ref, person_ref

READ_RECORDS = AnyOf(Perm.HR_DISCIPLINE, Perm.HR_VIEW)
READ_SUSPENSIONS = AnyOf(Perm.HR_SUSPEND, Perm.HR_VIEW)
READ_LEAVING = AnyOf(Perm.HR_TERMINATE, Perm.HR_VIEW)
READ_CHANGES = AnyOf(Perm.HR_MANAGE, Perm.HR_VIEW)
READ_CAREER = AnyOf(Perm.HR_VIEW, Perm.HR_MANAGE, Perm.HR_TERMINATE)
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


def _search(rows, q: str):
    for word in (q or "").split()[:4]:
        rows = rows.filter(
            Q(membership__first_name__icontains=word) | Q(membership__last_name__icontains=word)
        )
    return rows


def _branches(params) -> list[int]:
    return [int(b) for b in params.getlist("branch") if str(b).isdigit()]


# Leaving -------------------------------------------------------------------------------------

LEAVING_TABS = {
    "requested": (Termination.Status.REQUESTED,),
    "agreed": (Termination.Status.AGREED,),
    "completed": (Termination.Status.COMPLETED,),
    "closed": (Termination.Status.WITHDRAWN, Termination.Status.DECLINED),
}
LEAVING_ORDER = {
    "requested": ("requested_at", "pk"),
    "agreed": ("last_day", "pk"),
    "completed": ("-left_on", "-pk"),
    "closed": ("-closed_at", "-pk"),
}


class TerminationViewSet(
    ModuleOn, LifecycleContext, mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet
):
    """People leaving: requests to answer, last days agreed with their handover list, people
    who left with their final payslip, and requests withdrawn or declined."""

    perm = READ_LEAVING
    perms_by_action = {
        action: Perm.HR_TERMINATE
        for action in (
            "create",
            "partial_update",
            "agree",
            "decline",
            "withdraw",
            "retry",
            "handover",
            "handover_item",
        )
    }
    serializer_class = s.TerminationSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Termination.objects.none()
        rows = (
            queries.terminations(self.company, branch_ids=self.branch_scope)
            .select_related(
                "membership__user",
                "membership__position",
                "membership__home_branch",
                "membership__role",
                "membership__company",
                "requested_by__user",
                "agreed_by__user",
                "closed_by__user",
                "completed_by__user",
                "company",
            )
            .prefetch_related("handover__done_by__user")
        )
        if self.action != "list":
            return rows
        params = self.request.query_params
        tab = params.get("status")
        if tab in LEAVING_TABS:
            rows = rows.filter(status__in=LEAVING_TABS[tab])
        kinds = [value for value in params.getlist("kind") if value in Termination.Kind]
        if kinds:
            rows = rows.filter(kind__in=kinds)
        if member := _int(params.get("member"), "member"):
            rows = rows.filter(membership_id=member)
        if branches := _branches(params):
            rows = rows.filter(membership__branches__in=branches).distinct()
        rows = _search(rows, params.get("q", ""))
        return rows.order_by(*LEAVING_ORDER.get(tab, ("-requested_at", "-pk")))

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                enum=list(LEAVING_TABS),
                description="A tab: closed = withdrawn or declined.",
            ),
            OpenApiParameter("kind", str, many=True, enum=list(Termination.Kind.values)),
            OpenApiParameter("member", int),
            OpenApiParameter("q", str),
            BRANCH_PARAM,
        ],
        responses=s.TerminationRowSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        rows = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(rows)
        found = list(page if page is not None else rows)
        context = self.get_serializer_context() | {"states": terminations.states_for(found)}
        data = s.TerminationRowSerializer(found, many=True, context=context).data
        return self.get_paginated_response(data) if page is not None else Response(data)

    @extend_schema(responses=s.TerminationSerializer)
    def retrieve(self, request, *args, **kwargs):
        return Response(self.full(self.get_object()))

    @extend_schema(responses=s.LeavingCountsSerializer)
    @action(detail=False, methods=["get"])
    def counts(self, request, company_id):
        rows = queries.terminations(self.company, branch_ids=self.branch_scope)
        found = {
            tab: rows.filter(status__in=statuses).count() for tab, statuses in LEAVING_TABS.items()
        }
        return Response(found)

    @extend_schema(request=s.LeaveStartSerializer, responses={201: s.TerminationSerializer})
    def create(self, request, company_id):
        serializer = s.LeaveStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        person = self.person(data["member_id"])
        termination = terminations.start(
            person,
            by=self.membership,
            kind=data["kind"],
            last_day=data["last_day"],
            reason=data.get("reason", ""),
            leave_days=data.get("leave_days"),
            final_payslip=data.get("final_payslip", True),
        )
        return Response(self.full(termination), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.LeaveUpdateSerializer, responses=s.TerminationSerializer)
    def partial_update(self, request, company_id, pk):
        termination = self.get_object()
        serializer = s.LeaveUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        termination = terminations.update(
            termination, by=self.membership, **serializer.validated_data
        )
        return Response(self.full(termination))

    @extend_schema(request=s.LeaveAgreeSerializer, responses=s.TerminationSerializer)
    @action(detail=True, methods=["post"])
    def agree(self, request, company_id, pk):
        termination = self.get_object()
        serializer = s.LeaveAgreeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        termination = terminations.agree(
            termination,
            by=self.membership,
            last_day=data.get("last_day"),
            leave_days=data.get("leave_days"),
            final_payslip=data.get("final_payslip"),
        )
        return Response(self.full(termination))

    @extend_schema(request=s.LeaveReasonSerializer, responses=s.TerminationSerializer)
    @action(detail=True, methods=["post"])
    def decline(self, request, company_id, pk):
        termination = self.get_object()
        reason = self.reason()
        termination = terminations.decline(termination, by=self.membership, reason=reason)
        return Response(self.full(termination))

    @extend_schema(request=s.LeaveReasonSerializer, responses=s.TerminationSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, company_id, pk):
        termination = self.get_object()
        reason = self.reason()
        termination = terminations.withdraw(termination, by=self.membership, reason=reason)
        return Response(self.full(termination))

    @extend_schema(request=None, responses=s.TerminationSerializer)
    @action(detail=True, methods=["post"])
    def retry(self, request, company_id, pk):
        termination = terminations.retry(self.get_object(), by=self.membership)
        return Response(self.full(termination))

    @extend_schema(request=s.HandoverAddSerializer, responses={201: s.TerminationSerializer})
    @action(detail=True, methods=["post"])
    def handover(self, request, company_id, pk):
        termination = self.get_object()
        serializer = s.HandoverAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        terminations.add_item(termination, by=self.membership, **serializer.validated_data)
        return Response(self.full(termination), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.HandoverSetSerializer, responses=s.TerminationSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"handover/(?P<item_id>\d+)")
    def handover_item(self, request, company_id, pk, item_id):
        termination = self.get_object()
        item = HandoverItem.objects.filter(termination=termination, pk=item_id).first()
        if item is None:
            raise NotFound
        if request.method == "DELETE":
            terminations.remove_item(item, by=self.membership)
        else:
            serializer = s.HandoverSetSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            terminations.set_item(item, by=self.membership, **serializer.validated_data)
        return Response(self.full(termination))

    def reason(self) -> str:
        serializer = s.LeaveReasonSerializer(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data.get("reason", "")

    def full(self, termination: Termination) -> dict:
        termination = self.get_queryset().get(pk=termination.pk)
        context = self.get_serializer_context()
        context["states"] = terminations.states_for([termination])
        current = termination.membership.status in hr_queries.CURRENT
        context["blockers"] = (
            integrations.offboard_blockers(termination.membership)
            if termination.is_open and current
            else []
        )
        return s.TerminationSerializer(termination, context=context).data


# Job changes ---------------------------------------------------------------------------------

CHANGE_TABS = {
    "proposed": (JobChange.Status.PROPOSED,),
    "upcoming": (JobChange.Status.APPROVED,),
    "applied": (JobChange.Status.APPLIED,),
    "closed": (JobChange.Status.REJECTED, JobChange.Status.CANCELLED),
}
CHANGE_ORDER = {
    "proposed": ("created_at", "pk"),
    "upcoming": ("effective_on", "pk"),
    "applied": ("-effective_on", "-pk"),
    "closed": ("-updated_at", "-pk"),
}


class JobChangeViewSet(
    ModuleOn, LifecycleContext, mixins.ListModelMixin, mixins.RetrieveModelMixin, OwnerViewSet
):
    """New positions, branches, departments and pay from a day: proposed, approved, applied on
    their day, and the ones turned down or called off."""

    perm = READ_CHANGES
    perms_by_action = {
        action: Perm.HR_MANAGE
        for action in ("create", "approve", "reject", "cancel", "retry", "current")
    }
    serializer_class = s.JobChangeSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return JobChange.objects.none()
        rows = queries.job_changes(self.company, branch_ids=self.branch_scope).select_related(
            "membership__user",
            "membership__position",
            "membership__home_branch",
            "membership__role",
            "membership__company",
            "proposed_by__user",
            "decided_by__user",
            "position",
            "branch",
            "department",
            "company",
        )
        if self.action != "list":
            return rows
        params = self.request.query_params
        tab = params.get("status")
        if tab in CHANGE_TABS:
            rows = rows.filter(status__in=CHANGE_TABS[tab])
        if member := _int(params.get("member"), "member"):
            rows = rows.filter(membership_id=member)
        if branches := _branches(params):
            rows = rows.filter(membership__branches__in=branches).distinct()
        rows = _search(rows, params.get("q", ""))
        return rows.order_by(*CHANGE_ORDER.get(tab, ("-effective_on", "-pk")))

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                enum=list(CHANGE_TABS),
                description="A tab: upcoming = approved, closed = rejected or cancelled.",
            ),
            OpenApiParameter("member", int),
            OpenApiParameter("q", str),
            BRANCH_PARAM,
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=s.JobChangeCountsSerializer)
    @action(detail=False, methods=["get"])
    def counts(self, request, company_id):
        rows = queries.job_changes(self.company, branch_ids=self.branch_scope)
        found = {
            tab: rows.filter(status__in=statuses).count() for tab, statuses in CHANGE_TABS.items()
        }
        return Response(found)

    @extend_schema(
        parameters=[OpenApiParameter("member", int, required=True)],
        responses=s.CurrentJobSerializer,
    )
    @action(detail=False, methods=["get"])
    def current(self, request, company_id):
        person = self.person(_int(request.query_params.get("member"), "member"))
        today = hr_queries.today(self.company)
        viewer = self.membership
        pay = (
            integrations.current_pay(person, on=today)
            if viewer.has_perm(Perm.PAYROLL_VIEW)
            else None
        )
        waiting = JobChange.objects.filter(membership=person, status__in=job_changes.OPEN).order_by(
            "effective_on"
        )
        departments = Department.objects.for_company(self.company).order_by("name")
        return Response(
            {
                "member": person_ref(person),
                "position": _named(person.position),
                "home_branch": branch_ref(person.home_branch),
                "branches": [
                    branch_ref(branch) for branch in person.branches.order_by("order", "pk")
                ],
                "department": _named(person.department),
                "role": person.role.name if person.role else None,
                "pay": pay,
                "may_change_pay": integrations.payroll_on(self.company)
                and viewer.has_perm(Perm.PAYROLL_MANAGE),
                "departments": [{"id": row.pk, "name": row.name} for row in departments],
                "open_changes": [
                    {
                        "id": row.pk,
                        "effective_on": row.effective_on,
                        "status": row.status,
                        "parts": list(row.parts or []),
                    }
                    for row in waiting
                ],
            }
        )

    @extend_schema(request=s.JobChangeWriteSerializer, responses={201: s.JobChangeSerializer})
    def create(self, request, company_id):
        serializer = s.JobChangeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        person = self.person(data["member_id"])
        fields = {}
        if "position_id" in data:
            fields["position"] = self.find(Position, data["position_id"], "position_id")
        if "branch_id" in data:
            fields["branch"] = self.find(Branch, data["branch_id"], "branch_id")
        if "department_id" in data:
            fields["department"] = self.find(Department, data["department_id"], "department_id")
        change = job_changes.propose(
            person,
            by=self.membership,
            effective_on=data["effective_on"],
            reason=data["reason"],
            pay_amount=data.get("pay_amount"),
            pay_type=data.get("pay_type") or "",
            approve=data.get("approve", False),
            **fields,
        )
        return Response(self.shown(change), status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.JobChangeSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, company_id, pk):
        change = job_changes.approve(self.get_object(), by=self.membership)
        return Response(self.shown(change))

    @extend_schema(request=s.JobChangeReasonSerializer, responses=s.JobChangeSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, company_id, pk):
        change = job_changes.reject(self.get_object(), by=self.membership, reason=self.reason())
        return Response(self.shown(change))

    @extend_schema(request=s.JobChangeReasonSerializer, responses=s.JobChangeSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, company_id, pk):
        change = job_changes.cancel(self.get_object(), by=self.membership, reason=self.reason())
        return Response(self.shown(change))

    @extend_schema(request=None, responses=s.JobChangeSerializer)
    @action(detail=True, methods=["post"])
    def retry(self, request, company_id, pk):
        change = job_changes.apply(self.get_object(), by=self.membership)
        return Response(self.shown(change))

    def find(self, model, pk, name: str):
        if pk is None:
            return None
        found = model.objects.filter(company=self.company, pk=pk).first()
        if found is None:
            raise ValidationError({name: [_("Pick one of this company's.")]})
        return found

    def reason(self) -> str:
        serializer = s.JobChangeReasonSerializer(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data.get("reason", "")

    def shown(self, change: JobChange) -> dict:
        return self.get_serializer(self.get_queryset().get(pk=change.pk)).data


def _named(row) -> dict | None:
    return {"id": row.pk, "name": row.name} if row is not None else None


class CareerView(ModuleOn, OwnerAPIView):
    """Person 360's career tab: hired, job changes (applied and to come), leaving."""

    perm = READ_CAREER

    @extend_schema(responses=s.CareerSerializer)
    def get(self, request, company_id, member_id):
        person = hr_queries.person(self.company, member_id, branch_ids=self.branch_scope)
        if person is None:
            raise NotFound
        found = queries.career(person)
        context = self.get_serializer_context() | {
            "today": hr_queries.today(self.company),
            "in_scope": True,
        }
        leavings = found["terminations"]
        context["states"] = terminations.states_for(leavings)
        return Response(
            {
                "hired_on": found["hired_on"],
                "changes": s.JobChangeSerializer(found["changes"], many=True, context=context).data,
                "leavings": s.TerminationRowSerializer(leavings, many=True, context=context).data,
            }
        )
