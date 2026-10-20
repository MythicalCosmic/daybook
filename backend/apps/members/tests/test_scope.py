import pytest
from django.core.exceptions import ValidationError

from apps.companies.tests.factories import BranchFactory
from apps.members import scope
from apps.members.models import AccessRole, Membership
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def branches(company):
    return BranchFactory(company=company, name="Chilonzor"), BranchFactory(
        company=company, name="Yunusobod"
    )


def test_owners_see_every_branch(company, member, branches):
    owner = member(company, "Owner")
    owner.branches.set([branches[0]])

    assert scope.branch_ids(owner) is None


def test_branches_all_sees_every_branch(company, member):
    manager = member(company, "Manager")  # Manager holds branches.all

    assert scope.branch_ids(manager) is None


def test_others_see_their_own_branches(company, member, branches):
    worker = member(company)
    worker.branches.set(branches)

    assert scope.branch_ids(worker) == sorted(branch.pk for branch in branches)


def test_no_branches_means_no_branch_data(company, member):
    worker = member(company)

    assert scope.branch_ids(worker) == []


def test_a_role_without_branches_all_is_limited(company, member, branches):
    role = AccessRole.objects.create(company=company, name="Lead", permissions=["tasks.view_all"])
    lead = member(company, role_name="Lead")
    lead.branches.set([branches[1]])

    assert role.grants("tasks.view_all")
    assert scope.branch_ids(lead) == [branches[1].pk]


@pytest.mark.parametrize("status", [Membership.Status.SUSPENDED, Membership.Status.LEFT])
def test_members_who_arent_approved_see_nothing(company, member, branches, status):
    owner = member(company, "Owner", status=status)
    owner.branches.set(branches)

    assert scope.branch_ids(owner) == []


def test_prefetched_branches_are_used(company, member, branches, django_assert_num_queries):
    worker = member(company)
    worker.branches.set([branches[1]])
    worker = (
        Membership.objects.select_related("role").prefetch_related("branches").get(pk=worker.pk)
    )

    with django_assert_num_queries(0):
        assert scope.branch_ids(worker) == [branches[1].pk]


def test_allows():
    assert scope.allows(None, None)
    assert scope.allows(None, 7)
    assert scope.allows([7, 8], 7)
    assert not scope.allows([7, 8], 9)
    assert not scope.allows([7], None)  # rows without a branch need the full scope
    assert not scope.allows([], 7)


def test_restrict_by_branch(company, member, branches):
    worker = member(company)
    here = TaskFactory(company=company, assignee=worker, branch=branches[0])
    there = TaskFactory(company=company, assignee=worker, branch=branches[1])
    nowhere = TaskFactory(company=company, assignee=worker, branch=None)
    tasks = Task.objects.for_company(company)

    assert set(scope.restrict(tasks, None)) == {here, there, nowhere}
    assert set(scope.restrict(tasks, [branches[0].pk])) == {here}
    assert set(scope.restrict(tasks, [])) == set()


def test_restrict_people_by_any_shared_branch(company, member, branches):
    both = member(company)
    both.branches.set(branches)
    one = member(company)
    one.branches.set([branches[1]])
    none = member(company)
    people = Membership.objects.for_company(company).filter(pk__in=[both.pk, one.pk, none.pk])

    in_scope = list(scope.restrict(people, [b.pk for b in branches], field="branches"))
    assert sorted(m.pk for m in in_scope) == sorted([both.pk, one.pk])  # once each
    assert set(scope.restrict(people, [branches[0].pk], field="branches")) == {both}
    assert set(scope.restrict(people, None, field="branches")) == {both, one, none}


def test_restrict_through_a_relation(company, member, branches):
    worker = member(company, home_branch=branches[0])
    other = member(company, home_branch=branches[1])
    mine = TaskFactory(company=company, assignee=worker)
    TaskFactory(company=company, assignee=other)
    tasks = Task.objects.for_company(company)

    assert list(scope.restrict(tasks, [branches[0].pk], field="assignee__home_branch")) == [mine]


class TestMembershipBranches:
    def test_branches_of_another_company_are_refused(self, company, other_company, member):
        worker = member(company)
        foreign = BranchFactory(company=other_company)

        worker.home_branch = foreign
        with pytest.raises(ValidationError) as error:
            worker.full_clean()
        assert "home_branch" in error.value.message_dict

        worker.home_branch = None
        with pytest.raises(ValidationError) as error:
            worker.clean_branches([foreign])
        assert "branches" in error.value.message_dict

    def test_the_home_branch_is_one_of_their_branches(self, company, member, branches):
        worker = member(company, home_branch=branches[0])

        worker.clean_branches([branches[0], branches[1]])
        worker.clean_branches([])  # no branches yet: any home branch of the company
        with pytest.raises(ValidationError) as error:
            worker.clean_branches([branches[1]])
        assert "home_branch" in error.value.message_dict

    def test_clean_checks_the_saved_branches(self, company, member, branches):
        worker = member(company, home_branch=branches[0])
        worker.branches.set([branches[1]])

        with pytest.raises(ValidationError):
            worker.full_clean()

        worker.branches.add(branches[0])
        worker.full_clean()
