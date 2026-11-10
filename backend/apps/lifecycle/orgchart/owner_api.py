"""The org chart's owner endpoint (`lifecycle/org/`).

    GET lifecycle/org/      the company as one tree: owners, departments, branches, people,
                            open vacancies and what the viewer may do (hr.view or hr.manage)

Read only: a move dragged on the chart is a job change (`POST lifecycle/job-changes/`, R's
service), never applied here. Company- and branch-scoped (a manager sees their branches' part),
403 while HR is off.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from apps.console.base import OwnerAPIView
from apps.console.perms import AnyOf
from apps.lifecycle.orgchart import queries
from apps.lifecycle.orgchart.serializers import OrgChartSerializer
from apps.lifecycle.owner_api import ModuleOn
from apps.members.permissions import Perm

READ = AnyOf(Perm.HR_VIEW, Perm.HR_MANAGE)


class OrgChartView(ModuleOn, OwnerAPIView):
    perm = READ

    @extend_schema(responses=OrgChartSerializer, operation_id="lifecycle_org_chart")
    def get(self, request, company_id):
        return Response(OrgChartSerializer(queries.chart(self.company, self.membership)).data)
