"""Employee (mini app) endpoints of policies, under `/api/v1/companies/<id>/hr/…`
(docs/PLAN-OWNER.md §4.10, prefix E).

    GET   hr/policies/                              the rules that apply to me, what to sign first
    GET   hr/policies/{id}/                         one of them: the text in force, where I stand
    GET   hr/policies/{id}/file/                    a short-lived link to its file
    POST  hr/policies/versions/{id}/acknowledge/    "O‘qidim va roziman" (signing twice is fine)

Only the policies that apply to the person; anything else answers 404. A suspended person may
read them, not sign. While the HR module is off the endpoints answer 403.
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.hr.api import MemberView
from apps.hr.models import PolicyVersion
from apps.hr.policies import queries, services
from apps.hr.policies import serializers as s
from apps.hr.serializers import FileLinkSerializer


class MyPoliciesView(MemberView):
    """The rules that apply to me: late and waiting ones first, then the signed ones."""

    @extend_schema(responses=s.MyPolicySerializer(many=True))
    def get(self, request, company_id):
        day = queries.today(self.membership.company)
        rows = [s.my_policy_payload(item) for item in queries.mine(self.membership, day)]
        return Response(s.MyPolicySerializer(rows, many=True).data)


class PolicyStanding(MemberView):
    """A view about one of the person's rules."""

    def standing(self, pk):
        policy = queries.my_policy(self.membership, pk)
        if policy is None:
            raise NotFound
        day = queries.today(self.membership.company)
        row = queries.my_row(self.membership, policy)
        return queries.standing(policy, self.membership, row, day)


class MyPolicyView(PolicyStanding):
    """One rule to read: its text in force, and whether and when I signed it."""

    @extend_schema(responses=s.MyPolicyDetailSerializer)
    def get(self, request, company_id, pk):
        item = self.standing(pk)
        return Response(s.MyPolicyDetailSerializer(s.my_policy_payload(item, detail=True)).data)


class MyPolicyFileView(PolicyStanding):
    """A short-lived link to the rule's file (Telegram opens it outside the app)."""

    @extend_schema(responses=FileLinkSerializer)
    def get(self, request, company_id, pk):
        item = self.standing(pk)
        version = item.policy.current_version
        if not version.file:
            raise NotFound(_("This policy has no file."))
        return Response({"url": s.file_link(version, request.user)})


class SignPolicyView(PolicyStanding):
    """'I have read it and agree' for the version in force."""

    @extend_schema(request=None, responses=s.MyPolicyDetailSerializer)
    def post(self, request, company_id, pk):
        version = (
            PolicyVersion.objects.for_company(self.membership.company_id)
            .filter(pk=pk, published_at__isnull=False)
            .first()
        )
        if version is None or queries.my_policy(self.membership, version.policy_id) is None:
            raise NotFound
        services.acknowledge(version, by=self.membership)
        item = self.standing(version.policy_id)
        return Response(s.MyPolicyDetailSerializer(s.my_policy_payload(item, detail=True)).data)
