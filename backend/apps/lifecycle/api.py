"""Employee (mini app) endpoints of the people lifecycle; routed in `urls.py` under
`/api/v1/companies/<id>/lifecycle/…` (docs/PLAN-OWNER.md §13.4, the mini app's "My record",
"Resign" form and career timeline).

    GET   lifecycle/records/                  my records
    GET   lifecycle/records/{id}/             one (marks it read)
    POST  lifecycle/records/{id}/acknowledge/ "I was told"
    POST  lifecycle/records/{id}/explain/     {text}: my explanation

    GET   lifecycle/leaving/                  my leaving now (or the last closed one, 30 days)
    POST  lifecycle/leaving/                  {wished_last_day, reason}: I ask to leave
    POST  lifecycle/leaving/{id}/withdraw/    I stay after all (before my last day)
    POST  lifecycle/leaving/{id}/exit/        {reason, better, recommend}: my answers
    GET   lifecycle/career/                   my job changes, applied and to come

Only the person's own; a suspended person may still read them (changes are refused). While the
HR module is off the endpoints answer 403.
"""

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hr import queries as hr_queries
from apps.lifecycle import serializers as s
from apps.lifecycle import services, terminations
from apps.lifecycle.models import DisciplinaryRecord, JobChange, Termination
from apps.members.api import IsCompanyMember
from apps.members.models import Membership

# A declined or withdrawn request stays on the person's screen this long.
SHOW_CLOSED = timedelta(days=30)


class HROn(BasePermission):
    def has_permission(self, request, view):
        if not view.membership.company.has_feature("hr"):
            raise PermissionDenied(_("HR isn't switched on for this company."))
        return True


class MemberView(APIView):
    permission_classes = (IsAuthenticated, IsCompanyMember, HROn)
    allow_suspended = True
    membership: Membership

    def context(self) -> dict:
        return {"request": self.request, "today": hr_queries.today(self.membership.company)}

    def record(self, pk) -> DisciplinaryRecord:
        record = (
            DisciplinaryRecord.objects.filter(membership=self.membership, pk=pk)
            .select_related("issued_by__user")
            .first()
        )
        if record is None:
            raise NotFound
        return record


class MyRecordsView(MemberView):
    @extend_schema(responses=s.MyRecordSerializer(many=True))
    def get(self, request, company_id):
        rows = (
            DisciplinaryRecord.objects.filter(membership=self.membership)
            .select_related("issued_by__user")
            .order_by("-issued_on", "-pk")
        )
        return Response(s.MyRecordSerializer(rows, many=True, context=self.context()).data)


class MyRecordView(MemberView):
    @extend_schema(responses=s.MyRecordSerializer)
    def get(self, request, company_id, pk):
        record = self.record(pk)
        if record.read_at is None and self.membership.status == Membership.Status.APPROVED:
            record = services.mark_read(record, by=self.membership)
        return Response(s.MyRecordSerializer(record, context=self.context()).data)


class AcknowledgeView(MemberView):
    @extend_schema(request=None, responses=s.MyRecordSerializer)
    def post(self, request, company_id, pk):
        record = services.acknowledge(self.record(pk), by=self.membership)
        return Response(s.MyRecordSerializer(record, context=self.context()).data)


class ExplainView(MemberView):
    @extend_schema(request=s.ExplainSerializer, responses=s.MyRecordSerializer)
    def post(self, request, company_id, pk):
        record = self.record(pk)
        serializer = s.ExplainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.explain(
            record, by=self.membership, text=serializer.validated_data["text"]
        )
        return Response(s.MyRecordSerializer(record, context=self.context()).data)


# My leaving ----------------------------------------------------------------------------------


class LeavingView(MemberView):
    def mine(self, pk=None) -> Termination | None:
        rows = Termination.objects.filter(membership=self.membership).select_related(
            "agreed_by__user", "company", "membership__company"
        )
        if pk is not None:
            found = rows.filter(pk=pk).first()
            if found is None:
                raise NotFound
            return found
        current = rows.filter(status__in=terminations.OPEN).first()
        if current is not None:
            return current
        return (
            rows.filter(status__in=terminations.CLOSED, closed_at__gte=timezone.now() - SHOW_CLOSED)
            .order_by("-closed_at")
            .first()
        )

    def shown(self, termination: Termination | None) -> dict | None:
        if termination is None:
            return None
        context = self.context() | {"states": terminations.states_for([termination])}
        return s.MyLeavingSerializer(termination, context=context).data

    def state(self) -> dict:
        current = self.mine()
        return {
            "current": self.shown(current),
            "can_request": self.membership.status == Membership.Status.APPROVED
            and (current is None or not current.is_open),
            "notice_days": terminations.NOTICE_DAYS,
            "today": hr_queries.today(self.membership.company),
        }


class MyLeavingView(LeavingView):
    @extend_schema(responses=s.MyLeavingStateSerializer)
    def get(self, request, company_id):
        return Response(self.state())

    @extend_schema(request=s.LeaveRequestSerializer, responses={201: s.MyLeavingStateSerializer})
    def post(self, request, company_id):
        serializer = s.LeaveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        terminations.request(
            self.membership,
            by=self.membership,
            wished_last_day=data["wished_last_day"],
            reason=data.get("reason", ""),
        )
        return Response(self.state(), status=status.HTTP_201_CREATED)


class WithdrawLeavingView(LeavingView):
    @extend_schema(request=None, responses=s.MyLeavingStateSerializer)
    def post(self, request, company_id, pk):
        terminations.withdraw(self.mine(pk), by=self.membership)
        return Response(self.state())


class ExitAnswersView(LeavingView):
    @extend_schema(request=s.ExitAnswerSerializer, responses=s.MyLeavingStateSerializer)
    def post(self, request, company_id, pk):
        serializer = s.ExitAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        terminations.answer_exit(
            self.mine(pk),
            by=self.membership,
            reason=data["reason"],
            better=data.get("better", ""),
            recommend=data.get("recommend", ""),
        )
        return Response(self.state())


# My career -----------------------------------------------------------------------------------


class MyCareerView(MemberView):
    @extend_schema(responses=s.MyCareerSerializer)
    def get(self, request, company_id):
        from apps.lifecycle import integrations

        member = (
            Membership.objects.select_related("position", "home_branch", "department", "company")
            .filter(pk=self.membership.pk)
            .get()
        )
        changes = JobChange.objects.filter(
            membership=member,
            status__in=(JobChange.Status.APPLIED, JobChange.Status.APPROVED),
        ).order_by("-effective_on", "-pk")
        return Response(
            {
                "hired_on": integrations.hired_on(member),
                "position": member.position.name if member.position_id else None,
                "branch": member.home_branch.name if member.home_branch_id else None,
                "department": member.department.name if member.department_id else None,
                "changes": s.MyJobChangeSerializer(changes, many=True, context=self.context()).data,
            }
        )
