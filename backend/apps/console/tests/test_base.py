"""The owner endpoint base: who gets in, permission specs, audit, pulse bumps, ranges."""

import pytest
from django.core.cache import cache
from rest_framework import mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.console import pulse
from apps.console.base import (
    AnyOf,
    HasPerm,
    OwnerAPIView,
    OwnerCompanyAccess,
    OwnerViewSet,
    RangeMixin,
)
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.signin.tokens import OwnerAccessToken

pytestmark = pytest.mark.django_db


class ThingView(OwnerAPIView):
    perm = Perm.SALES_VIEW
    perms_by_action = {
        "post": Perm.SALES_MANAGE,
        "delete": AnyOf(Perm.FINANCE_MANAGE, Perm.SALES_MANAGE),
    }

    def get(self, request, company_id):
        return Response({"membership": self.membership.pk, "scope": self.branch_scope})

    def post(self, request, company_id):
        self.audit("console.thing_done", self.membership, size=3)
        self.bump("console.queue")
        return Response(status=201)

    def delete(self, request, company_id):
        return Response(status=204)


class RangeView(RangeMixin, OwnerAPIView):
    def get(self, request, company_id):
        return Response(self.range.as_dict())


class ThingViewSet(mixins.ListModelMixin, OwnerViewSet):
    perms_by_action = {"list": Perm.REPORTS_VIEW, "special": Perm.COMPANY_SETTINGS}

    def list(self, request, *args, **kwargs):
        return Response([])

    @action(detail=False)
    def special(self, request, company_id):
        return Response({})

    @action(
        detail=False,
        permission_classes=(IsAuthenticated, OwnerCompanyAccess, HasPerm.of(Perm.AUDIT_VIEW)),
    )
    def fixed(self, request, company_id):
        return Response({})


def call(view, membership, company_id, method="get", data=None):
    request = getattr(APIRequestFactory(), method)(
        "/",
        data,
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {OwnerAccessToken.for_user(membership.user)}",
    )
    return view(request, company_id=company_id)


thing = ThingView.as_view()


def test_an_approved_member_with_dashboard_access_gets_in(company, member):
    manager = member(company, "Manager")

    response = call(thing, manager, company.pk)

    assert response.status_code == 200
    assert response.data["membership"] == manager.pk


def test_another_companys_id_is_404(company, other_company, member):
    owner = member(company, "Owner")
    member(other_company, "Owner")

    assert call(thing, owner, other_company.pk).status_code == 404
    assert call(thing, owner, 999_999).status_code == 404


@pytest.mark.parametrize(
    "status",
    [
        Membership.Status.PENDING,
        Membership.Status.BLOCKED,
        Membership.Status.LEFT,
        Membership.Status.SUSPENDED,
    ],
)
def test_only_approved_members_get_in(company, member, status):
    owner = member(company, "Owner", status=status)

    assert call(thing, owner, company.pk).status_code == 404


def test_a_switched_off_company_is_404(company, member):
    owner = member(company, "Owner")
    company.is_active = False
    company.save()

    assert call(thing, owner, company.pk).status_code == 404


def test_without_dashboard_access_it_is_403(company, member):
    employee = member(company, "Employee")

    response = call(thing, employee, company.pk)

    assert response.status_code == 403
    assert "dashboard" in str(response.data["detail"])


def test_the_endpoint_permission_applies_per_method(company, member):
    accountant = member(company, "Accountant")  # sales.view, finance.manage; no sales.manage

    assert call(thing, accountant, company.pk).status_code == 200
    assert call(thing, accountant, company.pk, "post").status_code == 403
    assert call(thing, accountant, company.pk, "delete").status_code == 204  # AnyOf


def test_viewset_actions_have_their_own_permissions(company, member):
    fixed = ThingViewSet.as_view({"get": "fixed"}, **ThingViewSet.fixed.kwargs)  # as routers do
    manager = member(company, "Manager")  # reports.view; no company.settings, no audit.view

    assert call(ThingViewSet.as_view({"get": "list"}), manager, company.pk).status_code == 200
    assert call(ThingViewSet.as_view({"get": "special"}), manager, company.pk).status_code == 403
    assert call(fixed, manager, company.pk).status_code == 403
    owner = member(company, "Owner")
    assert call(fixed, owner, company.pk).status_code == 200


def test_branch_scope(company, member):
    owner = member(company, "Owner")
    branch = BranchFactory(company=company)
    employee_with_access = member(company, "Accountant")
    employee_with_access.role.permissions.remove(Perm.BRANCHES_ALL)
    employee_with_access.role.save()
    employee_with_access.branches.add(branch)

    assert call(thing, owner, company.pk).data["scope"] is None
    assert call(thing, employee_with_access, company.pk).data["scope"] == [branch.pk]


def test_writes_audit_as_the_member_and_bump_after_commit(
    company, member, django_capture_on_commit_callbacks
):
    owner = member(company, "Owner")
    cache.clear()

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        assert call(thing, owner, company.pk, "post").status_code == 201

    log = AuditLog.objects.get(action="console.thing_done")
    assert (log.company_id, log.actor_id, log.details) == (company.pk, owner.user_id, {"size": 3})
    assert len(callbacks) == 1
    assert pulse.versions(company.pk, ["console.queue"]) == {"console.queue": "1"}


def test_range_mixin_reads_the_query(company, member):
    owner = member(company, "Owner")
    request = APIRequestFactory().get(
        "/",
        {"from": "2026-10-01", "to": "2026-10-20", "compare": "prev"},
        HTTP_AUTHORIZATION=f"Bearer {OwnerAccessToken.for_user(owner.user)}",
    )

    response = RangeView.as_view()(request, company_id=company.pk)

    assert response.data == {
        "range": {"from": "2026-10-01", "to": "2026-10-20"},
        "compare": {"from": "2026-09-11", "to": "2026-09-30"},
    }


def test_range_mixin_answers_400_for_a_bad_range(company, member):
    owner = member(company, "Owner")
    request = APIRequestFactory().get(
        "/",
        {"preset": "forever"},
        HTTP_AUTHORIZATION=f"Bearer {OwnerAccessToken.for_user(owner.user)}",
    )

    response = RangeView.as_view()(request, company_id=company.pk)

    assert response.status_code == 400
    assert "range" in response.data
