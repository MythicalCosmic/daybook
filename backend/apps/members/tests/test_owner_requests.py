"""Join requests on the owner API and in Needs you."""

import pytest
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.console import registry
from apps.inbox.models import Notification
from apps.members import services
from apps.members.models import AccessRole, Membership
from apps.members.notifications import send_join_request
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory, PositionFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/companies/{cid}/join-requests/"


def url(company, suffix=""):
    return URL.format(cid=company.pk) + suffix


def asking(company, **kwargs):
    kwargs.setdefault("first_name", "Akmal")
    kwargs.setdefault("last_name", "Jo‘rayev")
    return MembershipFactory(
        company=company, onboarded_at=timezone.now(), user__phone="+998901239988", **kwargs
    )


def test_the_list_shows_requests_and_flags_former_employees(owner_api, company, member):
    owner = member.registered(company, "Owner")
    request = asking(company, position=PositionFactory(company=company, name="Cashier"))
    returning = asking(company, first_name="Jahongir")
    audit.record(
        AuditLog.Action.MEMBER_LEFT,
        company_id=company.pk,
        actor=owner.user,
        target=returning,
        terminated_on="2026-02-01",
    )

    response = owner_api(owner).get(url(company))

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.data}
    assert rows[request.pk]["position"]["name"] == "Cashier"
    assert rows[request.pk]["phone"] == "+998901239988"
    assert rows[request.pk]["former"] is None
    assert rows[returning.pk]["former"] == {"left_on": "2026-02-01", "how": "left"}


def test_approving_with_role_position_and_branches(
    owner_api, company, member, sent_messages, django_capture_on_commit_callbacks
):
    owner = member.registered(company, "Owner")
    chilonzor = company.branches.first()
    yunusobod = BranchFactory(company=company, name="Yunusobod")
    cashier_role = AccessRole.objects.get(company=company, name="Cashier")
    position = PositionFactory(company=company, name="Cashier")
    request = asking(company)

    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(owner).post(
            url(company, f"{request.pk}/approve/"),
            {
                "role_id": cashier_role.pk,
                "position_id": position.pk,
                "branch_ids": [chilonzor.pk, yunusobod.pk],
                "home_branch_id": yunusobod.pk,
            },
            format="json",
        )

    assert response.status_code == 200, response.data
    request.refresh_from_db()
    assert request.status == Membership.Status.APPROVED
    assert request.role == cashier_role and request.position == position
    assert request.home_branch == yunusobod
    assert set(request.branches.values_list("pk", flat=True)) == {chilonzor.pk, yunusobod.pk}
    # The person hears about it like after a bot approval.
    told = [m for m in sent_messages if m["chat_id"] == request.user.telegram_id]
    assert told and "was approved" in told[-1]["text"]


def test_approving_from_the_dashboard_closes_every_approvers_copy(
    owner_api, company, member, django_capture_on_commit_callbacks
):
    owner = member.registered(company, "Owner")
    manager = member.registered(company, "Manager")
    request = asking(company)
    with django_capture_on_commit_callbacks(execute=True):
        send_join_request(request.pk)
    assert Notification.objects.filter(kind="members.join", acted_at__isnull=True).count() == 2

    owner_api(manager).post(url(company, f"{request.pk}/approve/"), {}, format="json")

    assert not Notification.objects.filter(kind="members.join", acted_at__isnull=True).exists()
    assert registry.queue_total(owner) == 0


def test_rule_3_approving_gives_only_roles_the_approver_could_give(owner_api, company, member):
    hr = AccessRoleFactory(
        company=company,
        permissions=[Perm.DASHBOARD_ACCESS, Perm.MEMBERS_APPROVE, Perm.BRANCHES_ALL],
    )
    approver = member.registered(company, hr.name)
    manager_role = AccessRole.objects.get(company=company, name="Manager")
    owner_role = AccessRole.objects.get(company=company, is_owner=True)
    request = asking(company)

    for role in (manager_role, owner_role):
        response = owner_api(approver).post(
            url(company, f"{request.pk}/approve/"), {"role_id": role.pk}, format="json"
        )
        assert response.status_code == 403
    response = owner_api(approver).post(url(company, f"{request.pk}/approve/"), {}, format="json")
    assert response.status_code == 200
    request.refresh_from_db()
    assert request.role.is_default


def test_reject_with_a_reason(owner_api, company, member):
    owner = member.registered(company, "Owner")
    request = asking(company)

    response = owner_api(owner).post(
        url(company, f"{request.pk}/reject/"), {"reason": "No vacancy right now"}, format="json"
    )

    assert response.status_code == 204
    request.refresh_from_db()
    assert request.status == Membership.Status.REJECTED


def test_needs_you_items_carry_one_click_approve(company, member):
    owner = member.registered(company, "Owner")
    request = asking(company)

    [item] = registry.queue_items(owner, kind="members.join")

    assert item.id == request.pk
    assert [action.key for action in item.actions] == ["approve", "reject"]
    assert item.actions[0].endpoint == f"join-requests/{request.pk}/approve/"
    assert item.actions[0].body == {}


def test_with_several_branches_the_one_click_approve_uses_the_approvers_home_branch(
    company, member
):
    yunusobod = BranchFactory(company=company, name="Yunusobod")
    owner = member.registered(company, "Owner", home_branch=yunusobod)
    asking(company)

    [item] = registry.queue_items(owner, kind="members.join")

    assert item.actions[0].body == {"branch_ids": [yunusobod.pk], "home_branch_id": yunusobod.pk}
    assert "Yunusobod" in item.actions[0].label


def test_without_a_home_branch_there_is_no_one_click_approve(company, member):
    BranchFactory(company=company, name="Yunusobod")
    owner = member.registered(company, "Owner")
    asking(company)

    [item] = registry.queue_items(owner, kind="members.join")

    assert [action.key for action in item.actions] == ["reject"]
    assert item.url.startswith("people/requests?request=")


def test_permissions_and_tenancy(owner_api, company, other_company, member):
    worker = member.registered(company)
    stranger = member.registered(other_company, "Owner")
    request = asking(company)

    assert owner_api(worker).get(url(company)).status_code in (403, 404)
    assert owner_api(stranger).post(url(other_company, f"{request.pk}/approve/")).status_code == 404


def test_approve_service_refuses_branches_outside_the_scope(company, member):
    chilonzor = company.branches.first()
    yunusobod = BranchFactory(company=company, name="Yunusobod")
    role = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_APPROVE])
    approver = member.registered(company, role.name, home_branch=chilonzor)
    approver.branches.set([chilonzor])
    request = asking(company)

    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services.approve_request(request, by=approver, branches=[yunusobod])
