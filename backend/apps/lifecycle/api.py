"""Employee (mini app) endpoints of the people lifecycle; routed in `urls.py` under
`/api/v1/companies/<id>/lifecycle/…` (docs/PLAN-OWNER.md §13.4, the mini app's "My record").

    GET   lifecycle/records/                  my records
    GET   lifecycle/records/{id}/             one (marks it read)
    POST  lifecycle/records/{id}/acknowledge/ "I was told"
    POST  lifecycle/records/{id}/explain/     {text}: my explanation

Only the person's own records; a suspended person may still read them. While the HR module is
off the endpoints answer 403.
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hr import queries as hr_queries
from apps.lifecycle import serializers as s
from apps.lifecycle import services
from apps.lifecycle.models import DisciplinaryRecord
from apps.members.api import IsCompanyMember
from apps.members.models import Membership


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
