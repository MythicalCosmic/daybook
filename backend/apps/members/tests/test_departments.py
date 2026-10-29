"""Departments: the company's structure as a tree, each department with a head who manages
everyone in it and below it."""

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.members import departments, services
from apps.members.audit_actions import MemberAction
from apps.members.models import Department, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner")


@pytest.fixture
def tree(company, member, owner):
    """Rahbariyat (the owner) > Savdo (Bekzod) > Kechki smena (Madina); Ombor (no head)."""
    bekzod = member.registered(company, first_name="Bekzod")
    madina = member.registered(company, first_name="Madina")
    alisher = member.registered(company, first_name="Alisher")
    gulnora = member.registered(company, first_name="Gulnora")
    otabek = member.registered(company, first_name="Otabek")
    top = departments.create_department(company, by=owner, name="Rahbariyat", head=owner)
    sales = departments.create_department(company, by=owner, name="Savdo", parent=top, head=bekzod)
    evening = departments.create_department(
        company, by=owner, name="Kechki smena", parent=sales, head=madina
    )
    stock = departments.create_department(company, by=owner, name="Ombor", parent=top)
    departments.place(top, by=owner, people=[owner])
    departments.place(sales, by=owner, people=[bekzod, alisher])
    departments.place(evening, by=owner, people=[madina, gulnora])
    departments.place(stock, by=owner, people=[otabek])
    people = {
        "owner": owner,
        "bekzod": bekzod,
        "madina": madina,
        "alisher": alisher,
        "gulnora": gulnora,
        "otabek": otabek,
    }
    for person in people.values():
        person.refresh_from_db()
    return {"top": top, "sales": sales, "evening": evening, "stock": stock, **people}


def fresh(member: Membership) -> Membership:
    """The member as a new request would load it (no cached team)."""
    return Membership.objects.select_related("role", "company", "user").get(pk=member.pk)


# Whom a head manages ------------------------------------------------------------------------


def test_a_head_manages_their_department_and_everything_below(tree):
    bekzod = fresh(tree["bekzod"])

    assert departments.team_ids(bekzod) == {
        tree["alisher"].pk,
        tree["madina"].pk,  # the head of the department below, too
        tree["gulnora"].pk,
    }
    assert departments.leads(bekzod)


def test_the_top_head_manages_everyone_and_nobody_manages_themselves(tree):
    owner = fresh(tree["owner"])
    madina = fresh(tree["madina"])

    team = departments.team_ids(owner)
    assert tree["otabek"].pk in team and tree["gulnora"].pk in team
    assert owner.pk not in team
    assert departments.team_ids(madina) == {tree["gulnora"].pk}
    assert not departments.manages(madina, tree["bekzod"])  # her own head
    assert not departments.leads(fresh(tree["alisher"]))


def test_a_persons_head_is_the_nearest_head_above_them(tree):
    assert departments.manager_of(tree["alisher"]) == tree["bekzod"]
    assert departments.manager_of(tree["gulnora"]) == tree["madina"]
    # Heading their own department, their head is the one above.
    assert departments.manager_of(tree["madina"]) == tree["bekzod"]
    assert departments.manager_of(tree["bekzod"]) == tree["owner"]
    # A department without a head: the head above it.
    assert departments.manager_of(tree["otabek"]) == tree["owner"]
    assert departments.manager_of(tree["owner"]) is None


def test_someone_in_no_department_who_heads_one_reports_above_it(company, member, owner, tree):
    lola = member.registered(company, first_name="Lola")
    departments.update_department(tree["stock"], by=owner, head=lola)

    assert departments.manager_of(fresh(lola)) == tree["owner"]
    assert departments.team_ids(fresh(lola)) == {tree["otabek"].pk}


def test_heads_who_left_or_are_suspended_dont_count(tree, owner):
    Membership.objects.filter(pk=tree["bekzod"].pk).update(status=Membership.Status.SUSPENDED)

    assert departments.manager_of(tree["alisher"]) == tree["owner"]
    assert departments.team_ids(fresh(tree["bekzod"])) == frozenset()


def test_people_who_left_arent_anyones_team(tree):
    Membership.objects.filter(pk=tree["alisher"].pk).update(status=Membership.Status.LEFT)

    assert tree["alisher"].pk not in departments.team_ids(fresh(tree["bekzod"]))


def test_a_company_without_departments_has_no_teams(company, member, owner):
    worker = member.registered(company)

    assert departments.team_ids(fresh(owner)) == frozenset()
    assert departments.manager_of(worker) is None


def test_a_head_may_give_work_to_their_people_only(tree):
    madina = fresh(tree["madina"])

    assert list(departments.assignable(madina)) == [tree["gulnora"]]


def test_with_tasks_assign_a_head_also_picks_their_branch(company, member, tree):
    giver = AccessRoleFactory(company=company, permissions=[Perm.TASKS_ASSIGN, Perm.BRANCHES_ALL])
    Membership.objects.filter(pk=tree["madina"].pk).update(role=giver)

    picked = set(departments.assignable(fresh(tree["madina"])))

    assert tree["otabek"] in picked and tree["gulnora"] in picked
    assert fresh(tree["madina"]) not in picked


# Changing the structure -----------------------------------------------------------------------


def test_making_a_department_is_audited(company, owner):
    top = departments.create_department(company, by=owner, name="  Rahbariyat  ")

    assert top.name == "Rahbariyat"
    assert AuditLog.objects.filter(
        action=MemberAction.DEPARTMENT_CREATED, target_id=top.pk
    ).exists()


def test_names_are_unique_among_siblings(company, owner, tree):
    with pytest.raises(DomainError, match="already a department"):
        departments.create_department(company, by=owner, name="savdo", parent=tree["top"])
    with pytest.raises(DomainError, match="already a department"):
        departments.create_department(company, by=owner, name="RAHBARIYAT")
    # The same name elsewhere in the tree is fine.
    assert departments.create_department(company, by=owner, name="Ombor", parent=tree["sales"])


def test_a_department_cant_go_under_itself_or_its_own_part(owner, tree):
    with pytest.raises(DomainError, match="under itself"):
        departments.update_department(tree["sales"], by=owner, parent=tree["evening"])
    with pytest.raises(DomainError, match="under itself"):
        departments.update_department(tree["sales"], by=owner, parent=tree["sales"])


def test_moving_a_department_moves_who_manages_it(owner, tree):
    departments.update_department(tree["evening"], by=owner, parent=tree["stock"])

    assert departments.manager_of(tree["madina"]) == tree["owner"]  # Ombor has no head
    assert tree["gulnora"].pk not in departments.team_ids(fresh(tree["bekzod"]))
    row = AuditLog.objects.filter(action=MemberAction.DEPARTMENT_CHANGED).latest("pk")
    assert row.details["changes"] == {"parent": ["Savdo", "Ombor"]}


def test_the_head_must_be_a_current_member(company, member, owner, other_company, tree):
    stranger = member.registered(other_company)
    leaver = member.registered(company, status=Membership.Status.LEFT)

    for head in (stranger, leaver):
        with pytest.raises(DomainError, match="current member"):
            departments.update_department(tree["stock"], by=owner, head=head)


def test_deleting_moves_people_and_sub_departments_up(owner, tree):
    departments.delete_department(tree["sales"], by=owner)

    tree["evening"].refresh_from_db()
    tree["alisher"].refresh_from_db()
    assert tree["evening"].parent == tree["top"]
    assert tree["alisher"].department == tree["top"]
    assert not Department.objects.filter(pk=tree["sales"].pk).exists()


def test_deleting_a_top_department_leaves_its_people_in_none(owner, tree):
    departments.delete_department(tree["top"], by=owner)

    tree["owner"].refresh_from_db()
    tree["sales"].refresh_from_db()
    assert tree["owner"].department is None
    assert tree["sales"].parent is None


def test_deleting_refuses_when_a_sub_department_name_clashes(company, owner, tree):
    departments.create_department(company, by=owner, name="Kechki smena", parent=tree["top"])

    with pytest.raises(DomainError, match="Rename one of them first"):
        departments.delete_department(tree["sales"], by=owner)


def test_only_owners_and_managers_of_every_branch_change_the_structure(company, member, owner):
    scoped_role = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_MANAGE])
    scoped = member.registered(company, scoped_role.name)
    scoped.branches.add(company.branches.first())
    worker = member.registered(company)
    manager = member.registered(company, "Manager")  # sees every branch, no members.manage

    for who in (scoped, worker, manager):
        with pytest.raises(PermissionDenied):
            departments.create_department(company, by=who, name="Savdo")
    full = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_MANAGE, Perm.BRANCHES_ALL])
    assert departments.create_department(
        company, by=member.registered(company, full.name), name="Savdo"
    )


def test_placing_people_needs_them_in_your_branches(company, member, owner, tree):
    mine = company.branches.first()
    other = BranchFactory(company=company, name="Yunusobod")
    role = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_MANAGE])
    head = member.registered(company, role.name)
    head.branches.add(mine)
    near = member.registered(company)
    near.branches.add(mine)
    far = member.registered(company)
    far.branches.add(other)

    assert departments.place(tree["stock"], by=head, people=[near]) == 1
    with pytest.raises(PermissionDenied):
        departments.place(tree["stock"], by=head, people=[far])
    row = AuditLog.objects.filter(action=MemberAction.CHANGED, target_id=near.pk).latest("pk")
    assert row.details["changes"] == {"department": [None, "Ombor"]}


def test_editing_a_person_moves_them_between_departments(owner, tree):
    services.update_member(tree["alisher"], by=owner, department=tree["stock"])

    tree["alisher"].refresh_from_db()
    assert tree["alisher"].department == tree["stock"]
    row = AuditLog.objects.filter(action=MemberAction.CHANGED, target_id=tree["alisher"].pk).latest(
        "pk"
    )
    assert row.details["changes"]["department"] == ["Savdo", "Ombor"]


def test_a_head_who_leaves_leaves_their_department_without_a_head(owner, tree):
    services.offboard(
        tree["bekzod"], by=owner.user, terminated_on=timezone.localdate(), reason="resignation"
    )

    tree["sales"].refresh_from_db()
    assert tree["sales"].head is None


def test_a_new_head_works_in_their_department_when_in_none(company, member, owner):
    lola = member.registered(company, first_name="Lola")
    busy = member.registered(company, first_name="Bobur")
    other = departments.create_department(company, by=owner, name="Ombor")
    departments.place(other, by=owner, people=[busy])

    sales = departments.create_department(company, by=owner, name="Savdo", head=lola)
    hr = departments.create_department(company, by=owner, name="HR")
    departments.update_department(hr, by=owner, head=busy)

    lola.refresh_from_db()
    busy.refresh_from_db()
    assert lola.department == sales
    assert busy.department == other  # already somewhere: stays there


def test_heads_made_before_are_placed_in_the_highest_department_they_head(company, member, owner):
    import importlib

    from django.apps import apps

    lola = member.registered(company, first_name="Lola")
    busy = member.registered(company, first_name="Bobur")
    top = Department.objects.create(company=company, name="Rahbariyat", head=lola)
    Department.objects.create(company=company, name="Savdo", parent=top, head=lola)
    elsewhere = Department.objects.create(company=company, name="Ombor")
    Department.objects.create(company=company, name="HR", head=busy)
    Membership.objects.filter(pk=busy.pk).update(department=elsewhere)
    migration = importlib.import_module("apps.members.migrations.0014_seat_heads")

    migration.seat_heads(apps, None)

    lola.refresh_from_db()
    busy.refresh_from_db()
    assert lola.department == top
    assert busy.department == elsewhere
