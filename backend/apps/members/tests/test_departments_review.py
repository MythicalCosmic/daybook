"""Review of departments (dept/review): failing tests that pin down each finding on dept/core.

Each test failed on dept/core (304273b)."""

import contextlib

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.members import departments, services
from apps.members.models import Department, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner")


def fresh(member: Membership) -> Membership:
    """The member as a new request would load it (no cached team)."""
    return Membership.objects.select_related("role", "company", "user").get(pk=member.pk)


def people_url(company, suffix=""):
    return f"/api/v1/owner/companies/{company.pk}/people/{suffix}"


# Deleting a department whose sub-department has the same name ----------------------------------


def test_deleting_a_department_whose_part_has_the_same_name(company, owner):
    """Savdo > Savdo is allowed (the names are unique among siblings only). Deleting the outer
    one moves the inner one up while the outer row still holds the name, so the UPDATE breaks
    unique_department_name_per_parent: IntegrityError, a 500 on DELETE departments/{id}/. The
    clash check leaves the department itself out of `taken`. Moving the part up (the outer
    one is going away) or a clean 400 would both do."""
    outer = departments.create_department(company, by=owner, name="Savdo")
    inner = departments.create_department(company, by=owner, name="Savdo", parent=outer)

    try:
        departments.delete_department(outer, by=owner)
    except DomainError:
        return  # refused cleanly: a 400 with a message
    inner.refresh_from_db()
    assert inner.parent is None


# Placing an owner: the same rule as editing one -------------------------------------------------


def test_only_an_owner_puts_an_owner_into_a_department(company, member, owner):
    """`update_member` keeps "Only owners can change an owner"; `place` (POST
    departments/{id}/members/) doesn't check it, so a non-owner with members.manage moves the
    owner under a head of their choosing, themselves included, and from then on sees the
    owner's tasks and checks the owner's work."""
    role = AccessRoleFactory(
        company=company, permissions=[Perm.MEMBERS_MANAGE, Perm.BRANCHES_ALL, Perm.MEMBERS_VIEW]
    )
    hr = member.registered(company, role.name)
    sales = departments.create_department(company, by=owner, name="Savdo", head=hr)

    with pytest.raises(PermissionDenied):  # the person's page refuses (passes today)
        services.update_member(fresh(owner), by=fresh(hr), department=sales)
    with contextlib.suppress(PermissionDenied):
        departments.place(sales, by=fresh(hr), people=[fresh(owner)])

    owner.refresh_from_db()
    assert owner.department_id is None
    assert not departments.manages(fresh(hr), owner)


def test_only_an_owner_puts_an_owner_into_a_department_through_the_api(
    owner_api, company, member, owner
):
    role = AccessRoleFactory(
        company=company,
        permissions=[
            Perm.MEMBERS_MANAGE,
            Perm.MEMBERS_VIEW,
            Perm.BRANCHES_ALL,
            Perm.DASHBOARD_ACCESS,
        ],
    )
    hr = member.registered(company, role.name)
    sales = departments.create_department(company, by=owner, name="Savdo", head=hr)

    response = owner_api(hr).post(
        f"/api/v1/owner/companies/{company.pk}/departments/{sales.pk}/members/",
        {"member_ids": [owner.pk]},
        format="json",
    )

    assert response.status_code == 403
    owner.refresh_from_db()
    assert owner.department_id is None


def test_only_an_owner_puts_a_head_over_an_owner(company, member, owner):
    """The owner works in Rahbariyat. A non-owner who may edit the structure (members.manage,
    every branch, no task permission at all) makes themselves its head and from then on
    manages the owner and everyone below: sees their tasks, gives them work, accepts it. The
    indirect form of what "Only owners can change an owner" and the role rules (nobody grants
    rights they don't hold, `may_assign_role`) refuse elsewhere."""
    role = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_MANAGE, Perm.BRANCHES_ALL])
    hr = member.registered(company, role.name)
    top = departments.create_department(company, by=owner, name="Rahbariyat")
    departments.place(top, by=owner, people=[owner])

    with contextlib.suppress(PermissionDenied, DomainError):
        departments.update_department(top, by=fresh(hr), head=fresh(hr))

    assert not departments.manages(fresh(hr), owner)


# A head sitting in a department below one they head ---------------------------------------------


def test_a_head_sitting_below_their_own_department_isnt_managed_from_below(company, member, owner):
    """The owner heads Rahbariyat and works in Savdo, under it (Bekzod heads Savdo). Bekzod
    then manages the owner (the owner is in his department) while the owner manages Bekzod:
    each is the other's head, so each checks the other's work. The chain of command must not
    loop: whoever heads a department above someone is never managed by them."""
    bekzod = member.registered(company, first_name="Bekzod")
    top = departments.create_department(company, by=owner, name="Rahbariyat", head=owner)
    sales = departments.create_department(company, by=owner, name="Savdo", parent=top, head=bekzod)
    departments.place(sales, by=owner, people=[owner, bekzod])

    assert departments.manages(fresh(owner), bekzod)  # the top head manages him (passes)
    assert departments.manager_of(fresh(bekzod)) == owner  # passes
    assert not departments.manages(fresh(bekzod), owner)
    assert departments.manager_of(fresh(owner)) is None


def test_a_head_who_also_heads_a_part_further_down_isnt_managed_from_between(
    company, member, owner
):
    """The same loop without placing anyone: the owner heads Rahbariyat and also Kechki smena,
    below Savdo (Bekzod's). `team_ids` adds the heads of every department below, so Bekzod
    manages the owner. A fix that only checks where people are placed misses this one (and
    moving a department the owner heads under Savdo makes it too)."""
    bekzod = member.registered(company, first_name="Bekzod")
    top = departments.create_department(company, by=owner, name="Rahbariyat", head=owner)
    sales = departments.create_department(company, by=owner, name="Savdo", parent=top, head=bekzod)
    departments.create_department(company, by=owner, name="Kechki smena", parent=sales, head=owner)
    departments.place(top, by=owner, people=[owner])
    departments.place(sales, by=owner, people=[bekzod])

    assert departments.manages(fresh(owner), bekzod)  # passes
    assert departments.manager_of(fresh(owner)) is None  # passes
    assert not departments.manages(fresh(bekzod), owner)


# Someone who leaves and comes back ---------------------------------------------------------------


def test_someone_who_left_and_comes_back_starts_outside_the_departments(company, member, owner):
    """Leaving clears the departments a person headed but not the one they were in, and a
    returning person "starts over" (request_access drops their role and team link) except for
    it: approved again, they are back under their old head, who sees their tasks at once."""
    head = member.registered(company, first_name="Bekzod")
    worker = member.registered(company, first_name="Alisher")
    sales = departments.create_department(company, by=owner, name="Savdo", head=head)
    departments.place(sales, by=owner, people=[worker])
    services.offboard(worker, by=owner.user, terminated_on=timezone.localdate())

    again, opened = services.request_access(worker.user, company)
    assert opened
    services.approve(again, by=owner.user)

    again.refresh_from_db()
    assert again.status == Membership.Status.APPROVED
    assert again.department_id is None
    assert worker.pk not in departments.team_ids(fresh(head))


# Pulse: the departments list shows counts and heads ----------------------------------------------


def test_moving_someone_from_their_page_refreshes_the_departments(
    owner_api, company, member, owner, django_capture_on_commit_callbacks
):
    """Department rows carry member_count and total_count, but PATCH people/{id}/ with
    department_id bumps only members.people (`place` bumps both): an open org chart keeps the
    old counts."""
    worker = member.registered(company)
    stock = departments.create_department(company, by=owner, name="Ombor")
    before = pulse.versions(company.pk, ["members.departments"])["members.departments"]

    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(owner).patch(
            people_url(company, f"{worker.pk}/"), {"department_id": stock.pk}, format="json"
        )

    assert response.status_code == 200, response.data
    assert pulse.versions(company.pk, ["members.departments"])["members.departments"] != before


def test_a_head_leaving_refreshes_the_departments(
    company, member, owner, django_capture_on_commit_callbacks
):
    """Leaving clears the departments they headed (`_wind_down`) without bumping
    members.departments: the org chart keeps showing a head who is gone."""
    head = member.registered(company, first_name="Bekzod")
    departments.create_department(company, by=owner, name="Savdo", head=head)
    before = pulse.versions(company.pk, ["members.departments"])["members.departments"]

    with django_capture_on_commit_callbacks(execute=True):
        services.offboard(head, by=owner.user, terminated_on=timezone.localdate())

    assert pulse.versions(company.pk, ["members.departments"])["members.departments"] != before


# A deep tree --------------------------------------------------------------------------------------


def test_a_very_deep_tree_still_answers(company, owner):
    """`Org.in_tree_order` walks the tree recursively, and `headed_by` (so `team_ids`, every
    head's task list, menu and review queue) goes through it: a chain about a thousand
    departments deep raises RecursionError. Nothing limits the depth."""
    parent = None
    for index in range(1100):
        parent = Department.objects.create(company=company, name=f"D{index}", parent=parent)
    Department.objects.filter(pk=parent.pk).update(head=owner)

    assert len(departments.Org(company.pk).in_tree_order()) == 1100
    assert departments.team_ids(fresh(owner)) == frozenset()
